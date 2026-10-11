"""
PHASE 1 · M7/M8 — REGRESIÓN RUNTIME de la identidad de jobs y del binding.

Un job reclamado queda ligado a (job_id, worker_id, job_token, lease):
heartbeat/complete/fail verifican los CUATRO — el token SOLO ya no
autoriza. Y el asset done persiste binding_json (binding v1 verificable
de la ejecución; identidad Flow = not_verifiable, no inventada). Runtime
HTTP real contra la cola Flow completa. Windows-safe.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_job_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
import main as _main  # noqa: E402
import httpx  # noqa: E402

OK, FAIL = 0, 0
WA, WB = "w-aaaaaaaa", "w-bbbbbbbb"

# PNG real 1x1 generado con PIL (un asset corrupto debe morir en 422 —
# el validador del contrato NO negoció con bytes inválidos)
import io as _io  # noqa: E402
from PIL import Image as _Img  # noqa: E402

_buf = _io.BytesIO()
_Img.new("RGB", (1, 1), (10, 200, 10)).save(_buf, format="PNG")
PNG = _buf.getvalue()


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _new_job(scene: int) -> str:
    jid = db.new_id()
    with db.connect() as con:
        con.execute("""INSERT INTO flow_jobs(id, project_id, kind, scene_number,
                       prompt, status, attempts, max_attempts, lease_cycles,
                       created_at, updated_at)
                       VALUES(?,?,?,?,?,'queued',0,3,0,datetime('now'),datetime('now'))""",
                    (jid, _PID, "image", scene, "prompt de prueba"))
    return jid


_PID = db.create_project(title="JOBID", mode="idea", meta={})["id"]
J1, J2, J3, J4 = _new_job(1), _new_job(2), _new_job(3), _new_job(4)
BASE = "/api/extension/flow/jobs"


async def _cycle():
    out = {}
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        # ── claim worker A ──
        r = await c.get(f"{BASE}/next", params={"worker": WA})
        out["claim"] = r
        job = (r.json() or {}).get("job", {})
        out["job_id"] = job.get("id")
        out["token"] = job.get("job_token")
        out["worker_en_job"] = job.get("worker")

        # heartbeat sin worker → 400 (M7: identidad obligatoria en el API)
        out["hb_noworker"] = await c.post(
            f"{BASE}/{J1}/heartbeat", params={"token": out["token"]})
        # heartbeat de worker B con token de A → 409
        out["hb_wb"] = await c.post(
            f"{BASE}/{J1}/heartbeat", params={"token": out["token"], "worker": WB})
        # heartbeat legítimo → 200
        out["hb_wa"] = await c.post(
            f"{BASE}/{J1}/heartbeat", params={"token": out["token"], "worker": WA})
        # complete de worker B con token de A → 409
        out["comp_wb"] = await c.post(
            f"{BASE}/{J1}/complete", params={"token": out["token"], "worker": WB},
            content=PNG)
        # complete con token INCORRECTO → 409
        out["comp_tokmalo"] = await c.post(
            f"{BASE}/{J1}/complete", params={"token": "f" * 32, "worker": WA},
            content=PNG)
        # complete legítimo → 200 + binding
        out["comp_wa"] = await c.post(
            f"{BASE}/{J1}/complete", params={"token": out["token"], "worker": WA},
            content=PNG)

        # ── fail: worker B rechazado, worker A aceptado ──
        r2 = await c.get(f"{BASE}/next", params={"worker": WA})
        job2 = (r2.json() or {}).get("job", {})
        out["tok2"] = job2.get("job_token")
        out["fail_wb"] = await c.post(
            f"{BASE}/{J2}/fail", params={"token": out["tok2"], "worker": WB},
            json={"error": "x"})
        out["fail_wa"] = await c.post(
            f"{BASE}/{J2}/fail", params={"token": out["tok2"], "worker": WA},
            json={"error": "error de prueba"})
    return out


T = asyncio.run(_cycle())

check("claim devuelve job con worker propio",
      T["worker_en_job"] == WA and T["job_id"] == J1)
check("heartbeat SIN worker → 400 (el token solo NO autoriza, M7)",
      T["hb_noworker"].status_code == 400, str(T["hb_noworker"].status_code))
check("heartbeat worker B + token A → 409 (rechazo)",
      T["hb_wb"].status_code == 409, str(T["hb_wb"].status_code))
check("heartbeat worker A + token A → 200", T["hb_wa"].status_code == 200)
check("complete worker B + token A → 409 (rechazo)",
      T["comp_wb"].status_code == 409, str(T["comp_wb"].status_code))
check("complete token incorrecto → 409",
      T["comp_tokmalo"].status_code == 409)
check("complete worker A + token A → 200 (flujo legítimo intacto)",
      T["comp_wa"].status_code == 200, T["comp_wa"].text[:120])
check("fail worker B + token A → 409", T["fail_wb"].status_code == 409)
check("fail worker A + token A → 200", T["fail_wa"].status_code == 200)

# ── M8: binding_json persistido y honesto ──
row = None
with db.connect() as con:
    r = con.execute("SELECT binding_json, status FROM flow_jobs WHERE id=?", (J1,)).fetchone()
    row = json.loads(r["binding_json"]) if r and r["binding_json"] else None
check("done persistió binding_json", row is not None)
if row:
    check("binding: worker del claim", row.get("worker") == WA)
    check("binding: albra_project_id = proyecto del job",
          row.get("albra_project_id") == _PID)
    check("binding: asset_sha256 presente", len(row.get("asset_sha256", "")) == 64)
    check("binding: identidad Flow = not_verifiable (NO inventada)",
          row.get("flow_identity_state") == "not_verifiable")

# ── lease vencida → rechazo incluso para el worker dueño ──
with db.connect() as con:
    con.execute("""UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00'
                   WHERE id=?""", (J3,))
async def _lease():
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        tok = None
        r = await c.get(f"{BASE}/next", params={"worker": WA})
        job = (r.json() or {}).get("job", {})
        # el claim recupera J3 (lease vencida) → vuelve a queued con lease NUEVA;
        # para probar el rechazo usamos J4: lo reclamamos y VENCIMOS su lease
        jid4 = job.get("id")
        tok4 = job.get("job_token")
        with db.connect() as con2:
            con2.execute("UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00' WHERE id=?",
                         (jid4,))
        hb = await c.post(f"{BASE}/{jid4}/heartbeat",
                          params={"token": tok4, "worker": WA})
        comp = await c.post(f"{BASE}/{jid4}/complete",
                            params={"token": tok4, "worker": WA}, content=PNG)
        fl = await c.post(f"{BASE}/{jid4}/fail",
                          params={"token": tok4, "worker": WA}, json={"error": "x"})
        return hb, comp, fl


HB4, COMP4, FAIL4 = asyncio.run(_lease())
check("heartbeat con lease VENCIDA → 409 (aunque el token siga en la fila)",
      HB4.status_code == 409, str(HB4.status_code))
check("complete con lease VENCIDA → 409", COMP4.status_code == 409)
check("fail con lease VENCIDA → 409", FAIL4.status_code == 409)

# ── A6: la consulta de estado desatasca leases vencidas (idempotente) ──
with db.connect() as con:
    con.execute("""UPDATE flow_jobs SET status='claimed', worker=?, job_token=?,
                   lease_until='2000-01-01T00:00:00' WHERE id=?""", (WA, "e" * 32, J3))
async def _status():
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        s = await c.get(f"{BASE}/status/{_PID}")
        s2 = await c.get(f"{BASE}/status/{_PID}")  # idempotente
        with db.connect() as con:
            st = con.execute("SELECT status FROM flow_jobs WHERE id=?", (J3,)).fetchone()
        return s.status_code, s2.status_code, st["status"]


S1, S2, ST3 = asyncio.run(_status())
check("status/{pid} → 200 y desatasca la lease vencida de J3 (A6)",
      S1 == 200 and ST3 in ("queued", "dead"), f"{S1}/{ST3}")
check("recuperación IDEMPOTENTE (segunda consulta estable)", S2 == 200)

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
