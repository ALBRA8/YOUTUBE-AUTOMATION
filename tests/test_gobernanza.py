#!/usr/bin/env python3
"""Batería de GOBERNANZA (v2.19) — contratos del PROMPT 07 vivos en código.

Cubre: QA gate del render (§render: FAILED, nunca exitoso por existencia),
anti zombie-loop por lease_cycles (§reintentos: no reintentar infinitamente),
gancho MemoryDV de la cola, métricas §observabilidad (tasas + persistencia),
tools MCP de gobernanza, autonomía L0-L5 integrada y estados de publicación.
"""
import asyncio
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="gobernanza_test_"))
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


# ── 1. QA gate del render (§21: FAILED si el producto es inválido) ───────
print("── 1. _gate_qa_final (orchestrator)")
from pipeline import orchestrator as orch  # noqa: E402

_pid = db.create_project(title="QA gate test", mode="idea")["id"]
_final_malo = _cfg.OUTPUT_DIR / _pid / "final_malo.mp4"
_final_malo.parent.mkdir(parents=True, exist_ok=True)
_final_malo.write_bytes(b"<html>no soy un video</html>" * 100)
try:
    orch._gate_qa_final(_pid, _final_malo)
    check("render inválido → RuntimeError", False, "no lanzó")
except RuntimeError as e:
    check("render inválido → RuntimeError", "QA del render final FALLÓ" in str(e))
meta_qa = (db.get_project(_pid).get("meta") or {}).get("qa_final") or {}
check("meta.qa_final persistida con worst=error",
      meta_qa.get("worst") == "error" and bool(meta_qa.get("flags")))

_final_bueno = _cfg.OUTPUT_DIR / _pid / "final_bueno.mp4"
r = subprocess.run(
    ["ffmpeg", "-y", "-v", "error",
     "-f", "lavfi", "-i", "color=c=0xFF8C00:s=256x256:d=3.5",
     "-f", "lavfi", "-i", "sine=frequency=440:d=3.5",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
     "-shortest", str(_final_bueno)], capture_output=True, text=True)
check("MP4 sano fabricado (ffmpeg lavfi)", r.returncode == 0)
try:
    orch._gate_qa_final(_pid, _final_bueno)
    meta_qa2 = (db.get_project(_pid).get("meta") or {}).get("qa_final") or {}
    check("render sano pasa el gate", meta_qa2.get("worst") in ("ok", "warn"))
except RuntimeError as e:
    check("render sano pasa el gate", False, str(e)[:120])

# degradación de subtítulos sube como warn
(_cfg.OUTPUT_DIR / _pid / "subs_status.json").write_text(json.dumps(
    {"burned": False, "reason": "prueba: copiado sin subtítulos"}), encoding="utf8")
try:
    orch._gate_qa_final(_pid, _final_bueno)
    meta_qa3 = (db.get_project(_pid).get("meta") or {}).get("qa_final") or {}
    hay_warn_subs = any("NO quemados" in f.get("msg", "")
                        for f in meta_qa3.get("flags", []))
    check("subs no quemados → warn en meta.qa_final (no silencio)",
          hay_warn_subs and meta_qa3.get("worst") == "warn")
except RuntimeError:
    check("subs no quemados → warn en meta.qa_final (no silencio)",
          False, "gate lanzó con solo-warn (no debe)")

# ── 2. anti zombie-loop: lease_cycles acota la recuperación (§17) ────────
print("── 2. lease_cycles (anti reintentos infinitos)")
def _insert_job(cycles: int, lease_vencido: bool) -> str:
    jid = "job_" + db.new_id()
    lease = (_iso_pasado if lease_vencido else _iso_futuro)
    with db.connect() as con:
        con.execute(
            """INSERT INTO flow_jobs(id, project_id, kind, scene_number, part,
               prompt, status, attempts, max_attempts, lease_cycles, worker,
               job_token, lease_until, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, _pid, "video", 1, 1, "p", "claimed", 0,
             fj.MAX_ATTEMPTS["video"], cycles, "w-zombie", "tok",
             lease, db.now(), db.now()))
    return jid

_now = datetime.now(timezone.utc)
_iso_pasado = (_now - timedelta(hours=1)).isoformat(timespec="seconds")
_iso_futuro = (_now + timedelta(hours=1)).isoformat(timespec="seconds")

j1 = _insert_job(fj.MAX_LEASE_CYCLES - 2, True)   # ciclos de sobra → queued
n = fj.recover_expired()
with db.connect() as con:
    con_row = con.execute("SELECT * FROM flow_jobs WHERE id=?", (j1,)).fetchone()
check("lease vencido con ciclos disponibles → queued",
      con_row["status"] == "queued"
      and con_row["lease_cycles"] == fj.MAX_LEASE_CYCLES - 1)
check("recuperado contado en el barrido", n >= 1)

j2 = _insert_job(fj.MAX_LEASE_CYCLES - 1, True)    # último ciclo → dead
fj.recover_expired()
with db.connect() as con:
    con_row = con.execute("SELECT * FROM flow_jobs WHERE id=?", (j2,)).fetchone()
check("zombie-loop cerrado: agotó lease_cycles → dead",
      con_row["status"] == "dead"
      and "lease expirado" in (con_row["error"] or ""))
check("pérdida de lease NO consume attempts",
      con_row["attempts"] == 0)

j3 = _insert_job(0, False)  # lease VIGENTE → intocable
fj.recover_expired()
with db.connect() as con:
    con_row = con.execute("SELECT * FROM flow_jobs WHERE id=?", (j3,)).fetchone()
check("lease vigente no se toca", con_row["status"] == "claimed")

# re-enqueue conserva trabajo en vuelo (claimed con lease vivo)
src = Path(fj.__file__).read_text(encoding="utf-8")
check("enqueue_project NO borra claimed con lease vigente",
      "status IN ('queued','dead')" in src and "lease_until < ?" in src)

# ── 3. gancho MemoryDV de la cola (fallos → observaciones) ───────────────
print("── 3. MemoryDV hook en flow_jobs")
from services import memorydv as mem  # noqa: E402
mem.MEMORY_DIR = _TMP / "memorydv"
antes = (mem.stats().get("per_type") or {}).get("EPISODIC", 0)
fj._mem_obs("Google Flow falla con 429 en video escena 3 (prueba gobernanza)",
            "job_test_hook")
despues = (mem.stats().get("per_type") or {}).get("EPISODIC", 0)
check("fail() deja observación episódica", despues == antes + 1)

# ── 4. métricas §observabilidad: tasas honestas + persistencia ───────────
print("── 4. métricas (tasas + persist_snapshot)")
from services import metrics as mx  # noqa: E402
mx.SNAPSHOTS_PATH = _TMP / "metrics" / "snapshots.jsonl"
snap = mx.snapshot()
tasas = snap.get("rates") or {}
esperadas = {"production_success_rate", "step_success_rate",
             "provider_failure_rate", "retry_rate", "qa_failure_rate",
             "publish_failure_rate", "cost_per_production"}
check("snapshot.rates incluye tasas §28", esperadas <= set(tasas))
check("tasas no medibles quedan null (honestidad)",
      tasas.get("queue_latency") is None and tasas.get("recovery_rate") is None)
check("tasas medibles son float|None",
      all(v is None or isinstance(v, (int, float)) for v in tasas.values()))
rec1 = mx.persist_snapshot()
rec2 = mx.persist_snapshot()
check("persist_snapshot escribe JSONL con ts+rates",
      rec1 and rec2 and mx.SNAPSHOTS_PATH.exists()
      and len(mx.SNAPSHOTS_PATH.read_text().strip().splitlines()) == 2)

# ── 5. MCP de gobernanza (memoria/skills) por el dispatch real ──────────
print("── 5. MCP: tools de gobernanza")
from services import mcp_server  # noqa: E402
nombres = {t["name"] for t in mcp_server.TOOLS}
check("25 tools con las 3 nuevas",
      len(mcp_server.TOOLS) == 25
      and {"memoria_resumen", "memoria_consolidar", "skills_validar"} <= nombres)
res_mem = asyncio.run(mcp_server._dispatch(
    "memoria_resumen", {"texto": "gobernanza"}))
check("memoria_resumen responde stats+registros+candidatos",
      "stats" in res_mem and "registros" in res_mem and "candidatos" in res_mem)
res_con = asyncio.run(mcp_server._dispatch("memoria_consolidar", {}))
check("memoria_consolidar responde sin promover nada solo",
      isinstance(res_con, dict) and "candidates_created" in json.dumps(res_con))
res_sk = asyncio.run(mcp_server._dispatch("skills_validar", {}))
check("skills_validar → registro válido (targets reales)",
      res_sk.get("ok") is True and not res_sk.get("errores"))

# ── 6. autonomía integrada (publicación = external, self-improve no salta) ──
print("── 6. autonomía")
from services import autonomy as aut  # noqa: E402
check("publicar exige L3 (side effect externo)",
      not aut.check("publish_video")["allowed"] if aut.current_level() < 3
      else aut.ACTION_LEVELS["publish_video"] == 3)
check("doctor fix exige L4 (sensible)",
      aut.ACTION_LEVELS.get("doctor_fix") == 4)
check("self-improve exige L5", aut.ACTION_LEVELS.get("self_improve") == 5)
try:
    aut.assert_no_bypass("publish_video", granted_by="self_improve")
    check("self-improve no autoriza publishing", False, "no lanzó")
except ValueError:
    check("self-improve no autoriza publishing", True)

# ── 7. estados de publicación + gancho de cierre en orchestrator ────────
print("── 7. publicación y cierre observables")
src_o = Path(orch.__file__).read_text(encoding="utf-8")
check("autopublish: job kind=publish + publish_state",
      'kind="publish"' in src_o and '"PUBLISHING"' in src_o)
check("autopublish OMITIDO si QA final con errores",
      "autopublish OMITIDO" in src_o)
check("cierre deja episodio MemoryDV + snapshot métricas",
      "_memoria_episodio" in src_o and "persist_snapshot" in src_o)
check("script fallback registrado (script_engine en meta)",
      "script_engine" in src_o)

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
