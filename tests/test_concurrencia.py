#!/usr/bin/env python3
"""Batería CONCURRENCIA — el claim atómico aguanta trabajadores en paralelo.

Lo que garantiza el Flow Bridge cuando N extensiones/worker corren a la vez:

  1. Raza de claims: 8 workers con BEGIN IMMEDIATE se lanzan SIMULTÁNEAMENTE
     sobre una cola de 8 jobs → cada job se entrega EXACTAMENTE una vez,
     sin dobles claims, tokens todos distintos.
  2. Aislamiento multi-proyecto: workers con filtro project_id jamás reciben
     jobs de otro proyecto; workers globales drenan ambas colas.
  3. Token de una sola era: tras recuperar un lease vencido y re-entregar el
     job a otro worker, el token VIEJO ya no sirve (heartbeat/complete/fail
     → 409 None) y el NUEVO sí.
  4. Completes concurrentes de jobs distintos: todos aplican, la cola queda
     consistente (sin jobs fantasma ni assets cruzados).
  5. Enqueue mientras se reclama: añadir jobs en caliente no rompe claims.

Uso:  cd yt_automation_v2 && python3 tests/test_concurrencia.py
      python3 -m pytest tests/test_concurrencia.py -q
"""
import io
import shutil
import sys
import tempfile
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="concurrency_test_"))
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


def _proyecto(pid: str, n: int = 3) -> int:
    """Crea proyecto con n escenas; devuelve nº de jobs esperados
    (n imágenes + n-1 videos: la última escena es solo-imagen)."""
    db.create_project(id=pid, title=f"Conc {pid}", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, [
        {"title": f"Escena {i}", "narration": f"Narración {i}.",
         "image_prompt": f"wide shot stage {i}, golden hour, no text",
         "duration": 0.0, "status": "pending",
         "meta": {"production_unit": {
             "id": f"u{i}", "index": i - 1, "type": "scene",
             "video_prompt": (f"CE_CONC_V{i} :: dolly, {pid}"
                              if i < n else None)}}}
        for i in range(1, n + 1)])
    return n + (n - 1)


def _drain(worker: str, pid: str | None = None) -> list[dict]:
    out = []
    while True:
        j = fj.claim_next(worker, pid=pid)
        if not j:
            break
        out.append(j)
    return out


def main() -> int:
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM scenes")
        con.execute("DELETE FROM projects")

    print("── 1. RAZA de claims: 8 workers simultáneos, 8 jobs")
    esperados = _proyecto("proj_conc_a", n=5)  # 5 img + 4 vid = 9… ajustamos
    # n=5 → 5 imágenes + 4 videos = 9 jobs; para la raza usamos exactamente 9
    fj.enqueue_project("proj_conc_a")
    resumen = {"ok": 0, "err": 0, "jobs": [], "lock": threading.Lock()}

    def _worker(idx: int, barrier: threading.Barrier):
        try:
            barrier.wait(timeout=15)
            j = fj.claim_next(f"w-razo-{idx}")
            with resumen["lock"]:
                if j:
                    resumen["ok"] += 1
                    resumen["jobs"].append(
                        {"id": j["id"], "token": j["job_token"],
                         "worker": f"w-razo-{idx}", "kind": j["kind"],
                         "scene": j["scene_number"]})
                else:
                    resumen["err"] += 1  # sin job para este worker (9>8: ok)
        except Exception as e:  # noqa: BLE001
            with resumen["lock"]:
                resumen["err"] += 1
                resumen["jobs"].append({"error": str(e)[:120]})

    n_workers = 8
    barrier = threading.Barrier(n_workers)
    threads = [threading.Thread(target=_worker, args=(i, barrier))
               for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    ids = [j["id"] for j in resumen["jobs"] if "id" in j]
    toks = [j["token"] for j in resumen["jobs"] if "token" in j]
    check("8 workers → 8 claims exitosos (sin errores)",
          resumen["ok"] == 8 and resumen["err"] == 0,
          f"ok={resumen['ok']} err={resumen['err']}")
    check("todos los ids de job DISTINTOS (cero dobles claims)",
          len(ids) == len(set(ids)), f"unicos={len(set(ids))}/{len(ids)}")
    check("todos los tokens DISTINTOS", len(toks) == len(set(toks)))
    jrows = _drain("w-drena")
    ids2 = ids + [j["id"] for j in jrows]
    check("la cola entera (=9 jobs) se reparte sin repetir NINGUNO",
          len(ids2) == len(set(ids2)) == esperados,
          f"total={len(ids2)} esperados={esperados}")

    print("── 2. AISLAMIENTO multi-proyecto con filtro pid")
    _proyecto("proj_conc_b", n=2)
    _proyecto("proj_conc_c", n=2)
    fj.enqueue_project("proj_conc_b")
    fj.enqueue_project("proj_conc_c")
    jb = _drain("w-b", pid="proj_conc_b")
    check("worker filtrado a B solo recibe jobs de B",
          jb and all(j["project_id"] == "proj_conc_b" for j in jb),
          str({j["project_id"] for j in jb}))
    check("B drena EXACTAMENTE su cola (3 jobs)", len(jb) == 3, str(len(jb)))
    jc = _drain("w-c", pid="proj_conc_c")
    check("C solo recibe jobs de C", all(j["project_id"] == "proj_conc_c"
                                         for j in jc))
    todo = jb + jc
    check("sin fugas entre proyectos en los claims filtrados",
          len({j["project_id"] for j in todo}) == 2)

    print("── 3. token de una sola era (lease vencido re-entregado)")
    jd = _drain("w-viejo", pid="proj_conc_b")  # B ya drenada… re-encolamos
    if not jd:
        fj.enqueue_project("proj_conc_b")
        jd = _drain("w-viejo", pid="proj_conc_b")
    job = jd[0]
    with db.connect() as con:  # worker "muere" sin heartbeat
        con.execute("UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00+00:00' "
                    "WHERE id=?", (job["id"],))
    jn = fj.claim_next("w-nuevo", pid="proj_conc_b")
    check("job re-entregado a worker nuevo tras lease vencido",
          jn and jn["id"] == job["id"] and jn["worker"] == "w-nuevo")
    check("heartbeat con token VIEJO → None (409)",
          fj.heartbeat(job["id"], job["job_token"]) is None)
    check("complete con token VIEJO → None (409)",
          fj.complete(job["id"], job["job_token"], _png()) is None)
    check("fail con token VIEJO → None (409)",
          fj.fail(job["id"], job["job_token"], "viejo") is None)
    check("heartbeat con token NUEVO → ok",
          bool(fj.heartbeat(jn["id"], jn["job_token"])))

    print("── 4. completes CONCURRENTES de jobs distintos")
    fj.enqueue_project("proj_conc_c")  # recrea los no-done de C para la carrera
    blancos = _drain("w-pre2", pid="proj_conc_c")
    results = []

    def _completa(j):
        try:
            payload = _png() if j["kind"] == "image" else _mp4()
            r = fj.complete(j["id"], j["job_token"], payload)
            results.append((j["id"], bool(r)))
        except Exception as e:  # noqa: BLE001
            results.append((j["id"], f"EXC:{e}"[:60]))

    ts = [threading.Thread(target=_completa, args=(j,)) for j in blancos]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    ok_comp = sum(1 for _, r in results if r is True)
    check(f"completes paralelos: {ok_comp}/{len(blancos)} aplicados sin error",
          ok_comp == len(blancos), str(results)[:150])
    with db.connect() as con:
        q = con.execute("SELECT COUNT(*) c FROM flow_jobs WHERE "
                        "project_id='proj_conc_c' AND status='done'"
                        ).fetchone()["c"]
    check("colas consistentes: todos los jobs de C en done",
          q == 3, f"done={q}")

    print("── 5. enqueue EN CALIENTE mientras otro worker reclama")
    _proyecto("proj_conc_d", n=3)
    fj.enqueue_project("proj_conc_d")
    capturados = []

    def _reclamante():
        capturados.append(fj.claim_next("w-caliente", pid="proj_conc_d"))

    t = threading.Thread(target=_reclamante)
    t.start()
    res_hot = fj.enqueue_project("proj_conc_d")  # re-enqueue en paralelo
    t.join(timeout=15)
    check("claim en curso sobrevive a un enqueue simultáneo",
          bool(capturados and capturados[0]), str(res_hot)[:80])
    check("re-enqueue en caliente respeta done y recrea el resto",
          res_hot["created"] >= 1, str(res_hot)[:100])

    print("── 6. limpieza")
    shutil.rmtree(_TMP, ignore_errors=True)
    check("tmp eliminado", not _TMP.exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _mp4() -> bytes:
    import subprocess
    out = _TMP / "conc_clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0xFF8C00:s=64x64:d=1.0",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(out)],
        check=True, capture_output=True, timeout=60)
    return out.read_bytes()


def test_concurrencia():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
