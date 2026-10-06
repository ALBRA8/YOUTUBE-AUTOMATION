#!/usr/bin/env python3
"""Batería CHAOS — el Flow Bridge sobrevive a fallas reales.

Escenarios de falla inyectada (el sistema debe quedar CONSISTENTE en todos):

  1. REINICIO REAL DE PROCESO: un subprocess python independiente (nuevo
     intérprete, nueva conexión) reabre la MISMA base SQLite y reclama un job.
     La cola persiste en disco: nada se pierde al reiniciar el backend.
  2. Rollback atómico: si guardar el asset explota A MITAD de la transacción,
     el job sigue claimed con su token válido (ni done ni borrado) y el
     reintento del worker funciona.
  3. Doble complete: el segundo llega con el job ya done → 409 (None), el
     asset no se sobreescribe con una segunda mano.
  4. Asset corrupto: HTML/basura → ValueError (422), el intento se conserva,
     fail() lo re-encola y al agotar max_attempts muere en dead.
  5. Dead → re-enqueue: recrea el job con attempts=0 (segunda oportunidad
     limpia) y conserva los done.
  6. Heartbeat/complete sobre estados imposibles (done, queued, inexistente)
     → None, nunca corrupción.
  7. Carrera zombie: lease vencido + viejo worker intenta complete después
     de que otro reclamó → pierde limpio (409).

Uso:  cd yt_automation_v2 && python3 tests/test_chaos.py
      python3 -m pytest tests/test_chaos.py -q
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="chaos_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
from services import flow_jobs as fj  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (200, 40, 90)).save(buf, format="PNG")
    return buf.getvalue()


def _proyecto(pid: str, n: int = 2) -> None:
    db.create_project(id=pid, title=f"Chaos {pid}", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, [
        {"title": f"Escena {i}", "narration": f"Narración {i}.",
         "image_prompt": f"wide shot stage {i}, golden hour, no text",
         "duration": 0.0, "status": "pending",
         "meta": {"production_unit": {
             "id": f"u{i}", "index": i - 1, "type": "scene",
             "video_prompt": (f"CE_CHAOS_V{i} :: pan, {pid}"
                              if i < n else None)}}}
        for i in range(1, n + 1)])


_RESTART_SCRIPT = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    sys.path.insert(0, os.environ["CHAOS_BACKEND"])
    import config
    config.DB_PATH = Path(os.environ["CHAOS_DB"])
    import database as db
    from services import flow_jobs as fj
    job = fj.claim_next("w-restart-proc")
    st = fj.status_for_project(os.environ["CHAOS_PID"])
    print(json.dumps({
        "claimed": job["id"] if job else None,
        "kind": job["kind"] if job else None,
        "counts": st["counts"],
    }))
""")


def main() -> int:
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM scenes")
        con.execute("DELETE FROM projects")

    print("── 1. REINICIO REAL DE PROCESO (subprocess nuevo intérprete)")
    _proyecto("proj_chaos_1", n=2)          # 2 img + 1 vid = 3 jobs
    fj.enqueue_project("proj_chaos_1")
    env = {**os.environ,
           "CHAOS_BACKEND": str(BACKEND),
           "CHAOS_DB": str(_cfg.DB_PATH),
           "CHAOS_PID": "proj_chaos_1"}
    script = _TMP / "_restart_probe.py"
    script.write_text(_RESTART_SCRIPT, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script)], env=env,
                          capture_output=True, text=True, timeout=120)
    check("subprocess de reinicio corre sin error", proc.returncode == 0,
          proc.stderr[-200:] if proc.returncode else "")
    out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout else {}
    check("el proceso NUEVO ve la cola persistida (2 queued: ya reclamó 1)",
          out.get("counts", {}).get("queued") == 2, str(out))
    check("el proceso NUEVO reclama un job de la cola en disco",
          bool(out.get("claimed")), str(out)[:120])
    with db.connect() as con:
        n_claimed = con.execute(
            "SELECT COUNT(*) c FROM flow_jobs WHERE status='claimed'"
        ).fetchone()["c"]
    check("1 job claimed por el proceso nuevo (reinicio no perdió nada)",
          n_claimed == 1, str(n_claimed))

    print("── 2. rollback atómico si el guardado explota a mitad")
    _proyecto("proj_chaos_2", n=1)          # 1 job de imagen
    fj.enqueue_project("proj_chaos_2")
    j = fj.claim_next("w-chaos")
    original_save = fj._save_image

    def _save_explode(*a, **k):
        raise RuntimeError("disco lleno a mitad de la escritura")

    fj._save_image = _save_explode
    try:
        fj.complete(j["id"], j["job_token"], _png())
        check("complete con fallo de disco → excepción", False)
    except RuntimeError:
        check("complete con fallo de disco → excepción", True)
    finally:
        fj._save_image = original_save
    check("job SIGUE claimed tras el rollback (ni done ni queued)",
          fj.heartbeat(j["id"], j["job_token"]) is not None)
    with db.connect() as con:
        st = con.execute("SELECT status FROM flow_jobs WHERE id=?",
                         (j["id"],)).fetchone()["status"]
    check("estado en DB = claimed (transacción revertida limpia)",
          st == "claimed", st)
    res_retry = fj.complete(j["id"], j["job_token"], _png())
    check("reintento del MISMO worker con el MISMO token → ok",
          bool(res_retry and res_retry["ok"]), str(res_retry)[:100])

    print("── 3. doble complete → 409 limpio")
    with db.connect() as con:
        asset1 = con.execute("SELECT asset_path FROM flow_jobs WHERE id=?",
                             (j["id"],)).fetchone()["asset_path"]
    check("segundo complete con el mismo token → None",
          fj.complete(j["id"], j["job_token"], _png()) is None)
    with db.connect() as con:
        asset2 = con.execute("SELECT asset_path FROM flow_jobs WHERE id=?",
                             (j["id"],)).fetchone()["asset_path"]
    check("el asset NO fue sobreescrito por el segundo complete",
          asset1 == asset2)

    print("── 4. asset corrupto → 422 + intentos + dead")
    _proyecto("proj_chaos_3", n=1)
    fj.enqueue_project("proj_chaos_3")
    jc = fj.claim_next("w-chaos")
    try:
        fj.complete(jc["id"], jc["job_token"], b"<html>Error de Flow</html>")
        check("HTML de Flow rechazado (ValueError)", False)
    except ValueError:
        check("HTML de Flow rechazado (ValueError)", True)
    check("token sigue válido tras el 422 (worker puede reintentar el envío)",
          fj.heartbeat(jc["id"], jc["job_token"]) is not None)
    rf1 = fj.fail(jc["id"], jc["job_token"], "Flow devolvió HTML")
    check("fallo 1/3 imagen → queued", rf1["status"] == "queued"
          and rf1["attempts"] == 1, str(rf1))
    jc2 = fj.claim_next("w-chaos")
    check("re-entregado con attempts visibles al worker",
          jc2["id"] == jc["id"] and jc2["attempts"] == 1)
    fj.fail(jc2["id"], jc2["job_token"], "otra vez HTML")
    jc3 = fj.claim_next("w-chaos")
    rf3 = fj.fail(jc3["id"], jc3["job_token"], "tercer HTML")
    check("fallo 3/3 imagen → DEAD", rf3["status"] == "dead", str(rf3))
    check("cola del proyecto sin jobs útiles → claim None",
          fj.claim_next("w", pid="proj_chaos_3") is None)

    print("── 5. dead → re-enqueue (segunda oportunidad limpia)")
    res_re = fj.enqueue_project("proj_chaos_3")
    check("re-enqueue recrea el dead con attempts=0",
          res_re["created"] == 1, str(res_re))
    jd = fj.claim_next("w-chaos")
    check("job recreado reclamable y con attempts reiniciados",
          jd and jd["attempts"] == 0, str(jd)[:100])
    check("complete del job recreado → ok",
          bool(fj.complete(jd["id"], jd["job_token"], _png())))

    print("── 6. estados imposibles: nunca corrupción")
    done_job = jd
    check("heartbeat sobre job done → None",
          fj.heartbeat(done_job["id"], done_job["job_token"]) is None)
    check("complete sobre job done → None",
          fj.complete(done_job["id"], done_job["job_token"], _png()) is None)
    check("claim sobre cola drenada → None",
          fj.claim_next("w-chaos", pid="proj_chaos_3") is None)
    _proyecto("proj_chaos_4", n=1)
    fj.enqueue_project("proj_chaos_4")
    jq = fj.claim_next("w-chaos")
    check("complete sobre job NUNCA reclamado (sin token) → None",
          fj.complete(jq["id"], "token-inexistente", _png()) is None)
    check("heartbeat de job inexistente → None",
          fj.heartbeat("no-existe", "x") is None)
    fj.fail(jq["id"], jq["job_token"], "limpieza")  # re-encola para §7

    print("── 7. carrera zombie: lease vencido + viejo complete tarde")
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00+00:00' "
                    "WHERE id=?", (jq["id"],))
    jz = fj.claim_next("w-nuevo", pid=jq["project_id"])  # recuperación perezosa
    check("zombie re-asignado al worker nuevo",
          jz and jz["id"] == jq["id"] and jz["worker"] == "w-nuevo")
    check("viejo worker llega tarde con su token → None (409)",
          fj.complete(jq["id"], jq["job_token"], _png()) is None)
    check("worker nuevo completa sin problema",
          bool(fj.complete(jz["id"], jz["job_token"], _png())))

    print("── 8. limpieza")
    shutil.rmtree(_TMP, ignore_errors=True)
    check("tmp eliminado", not _TMP.exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_chaos():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
