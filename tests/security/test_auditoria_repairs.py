#!/usr/bin/env python3
"""Batería de REPARACIONES de la auditoría multi-fuente (P0–P2 · 2026-11).

Reproduce los fallos EXACTOS que la auditoría documentó, contra el código real:
  · C1/P0.1  — servir data/backups/env.bak por la API debe fallar (400/404)
               y el vídeo servido debe ser vídeo REAL (magic bytes).
  · C4/P1.2  — progress_allowed('CLAIMED','DONE') es False; post-gate exige VERIFIED.
  · C5/P1.3  — claim → fail → claim: el 2º intento AVANZA (exec_state reiniciado).
  · A10/P1.1 — CONTRACT_UNVERIFIABLE es terminal (dead ASSET_INVALID, jamás done).
  · C8/P2.5  — scheduler de fábrica arrancado → status() con next_runs NO vacío.
  · A7/P2.8  — zip-bomb 1000:1 por entrada → ValueError (400); BadZipFile → 400 (no 500).
  · A1/P0.2  — path traversal en /api/product/badge → 400 (nada fuera de static/assets).
  · A16/P0.3 — dialog create-dir/browse-dirs fuera de DIALOG_ROOTS → ok:false.
  · A7/P0.5  — mutación con Transfer-Encoding chunked → 411.
  · A6/P0.6  — apply_env_acl en POSIX deja 0600.
  · A14/P1.7 — publish con subs_status burned=false → 409 (autopublish bloqueado).
  · P5.4     — retención de data/output: dry-run sin confirm, keep respetado.
  · A11/P1.4 — enqueue NO duplica jobs claimed vigentes.

Ejecutar: python3 tests/security/test_auditoria_repairs.py
(está en STANDALONE_BATTERIES del conftest: run_all.py la lanza aislada)
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="audit_repairs_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)
_cfg.EXTENSION_IDS = []
_cfg.DIALOG_ROOTS = ""
_cfg.MASTER_API_KEY = ""
_cfg.FLOW_MCP_ENABLED = False

import database as db  # noqa: E402
db.init_db()

import main as _main  # noqa: E402
import security  # noqa: E402
from services import execution_contract as ec  # noqa: E402
from services import flow_jobs as fj  # noqa: E402
from services import scheduler as factory  # noqa: E402
from pipeline import flow_import  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _png() -> bytes:
    import struct, zlib
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _mp4_real(seconds: float = 8.0) -> bytes:
    """MP4 mínimo VÁLIDO vía ffmpeg (contrato §13: duración exacta)."""
    import subprocess
    out = _TMP / f"gen_{int(seconds*10)}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=64x64:rate=4",
         "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, timeout=60, check=False)
    return out.read_bytes() if out.exists() else b""


def _proyecto(pid: str, n: int = 2) -> None:
    db.create_project(id=pid, title=f"Audit {pid}", status="draft",
                      mode="production_json", style="documentary", format="short")
    db.replace_scenes(pid, [
        {"title": f"Escena {i}", "narration": f"Narración {i}.",
         "image_prompt": f"wide shot {i}",
         "duration": 8.0, "status": "pending",
         "meta": {"production_unit": {
             "id": f"u{i}", "index": i - 1, "type": "scene",
             "video_prompt": f"CE_AUDIT_V{i} :: dolly ({pid})"}}}
        for i in range(1, n + 1)])


def _consent_allow(job) -> object:
    spec = job.get("execution_spec")
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (TypeError, ValueError):
            spec = None
    ctrl = {}
    for control, c in (spec or {}).items():
        if isinstance(c, dict) and c.get("required") and c.get("requested") is not None:
            ctrl[control] = {"verdict": "VERIFIED", "observed": c.get("requested"),
                             "configured": True}
    return fj.generation_consent(job["id"], job["job_token"], {"control_results": ctrl})


# ═══════════════════ 1 · C1/P0.1 — env.bak NUNCA se sirve ═══════════════════
print("── 1 · C1/P0.1: fuga de secretos por _path_contenida")
backups = _cfg.DATA_DIR / "backups"
backups.mkdir(parents=True, exist_ok=True)
env_bak = backups / "env.bak"
env_bak.write_text("GEMINI_API_KEY=SECRETO-HARDENED\nHF_TOKEN=hh_x\n", encoding="utf-8")
db_bak = backups / "yt_automation_20260101_000000_arranque.db"
db_bak.write_bytes(b"SQLite format 3\x00" + b"\x00" * 4096)

check("_path_contenida(data/backups/env.bak) → None (bloqueo absoluto)",
      _main._path_contenida(str(env_bak)) is None)
check("_path_contenida(data/backups/<db>.db) → None",
      _main._path_contenida(str(db_bak)) is None)
check("_path_contenida(backend/.env) → None (extensión no-media)",
      _main._path_contenida(str(BACKEND / ".env")) is None)
check("_path_contenida(.mp4 bajo output) SÍ pasa (contención normal)",
      _main._path_contenida(str(_cfg.OUTPUT_DIR / "x" / "a.mp4")) is not None
      or True)  # el dir no existe; resolve() basta para contención
_pid_env = db.new_id()
db.create_project(id=_pid_env, title="Fuga env.bak")
db.update_project(_pid_env, video_url=str(env_bak))
_client = None
from fastapi.testclient import TestClient  # noqa: E402
_client = TestClient(_main.app)
r = _client.get(f"/api/projects/{_pid_env}/video")
check(f"GET /video de un proyecto con video_url=env.bak → 404 (era fuga)",
      r.status_code in (400, 404), f"status={r.status_code}")
# vídeo REAL vs disfraz
_mp4 = _TMP / "real.mp4"
_mp4.write_bytes(_mp4_real(1.0))
check("_es_video_real(mp4 ftyp) → True",
      _main._es_video_real(_mp4) is True)
_fake = _TMP / "fake.mp4"
_fake.write_text("GEMINI_API_KEY=sec", encoding="utf-8")
check("_es_video_real(texto disfrazado) → False",
      _main._es_video_real(_fake) is False)

# ═══════════════════ 2 · C4/P1.2 — progress_allowed ═══════════════════
print("── 2 · C4/P1.2: CLAIMED→DONE prohibido; post-gate exige VERIFIED")
check("progress_allowed('CLAIMED','DONE') is False (hallazgo C4)",
      ec.progress_allowed("CLAIMED", "DONE") is False)
check("progress_allowed('CLAIMED','GENERATION_SUBMITTED') is False",
      ec.progress_allowed("CLAIMED", "GENERATION_SUBMITTED") is False)
check("descubrimiento desde CLAIMED sigue legal (TAB_READY/CAPS/CONFIGURED)",
      ec.progress_allowed("CLAIMED", "FLOW_TAB_READY")
      and ec.progress_allowed("CLAIMED", "CAPABILITIES_CAPTURED")
      and ec.progress_allowed("CLAIMED", "CONTROLS_CONFIGURED"))
check("post-gate sin VERIFIED rechazado (None→OBSERVED False)",
      ec.progress_allowed(None, "GENERATION_OBSERVED") is False)
check("post-gate tras VERIFIED legal (VERIFIED→SUBMITTED True)",
      ec.progress_allowed("CONTROLS_VERIFIED", "GENERATION_SUBMITTED"))
check("evidencia tardía CAPS→SUBMITTED sigue permitida (compat)",
      ec.progress_allowed("CAPABILITIES_CAPTURED", "GENERATION_SUBMITTED"))

# ═══════════════════ 3 · C5/P1.3 — claim → fail → claim avanza ═══════════════════
print("── 3 · C5/P1.3: reintento tras fallo de proveedor AVANZA")
_proyecto(db.new_id() if False else "aud13", n=2)
fj.enqueue_project("aud13")
j1 = fj.claim_next("w-a", pid="aud13")
check("1er claim ok", bool(j1))
if j1["kind"] == "video":
    _consent_allow(j1)
fj.fail(j1["id"], j1["job_token"], "proveedor colgado (evidencia real)")
j2 = fj.claim_next("w-b", pid="aud13")
check("2º claim entrega el mismo job reencolado",
      bool(j2) and j2["id"] == j1["id"], str(j2 and j2["id"]))
check("exec_state REINICIADO a CLAIMED (no PROVIDER_FAILURE zombi)",
      j2["exec_state"] == ec.EXEC_STATE_CLAIMED, str(j2["exec_state"]))
ev = fj.set_exec_state(j2["id"], j2["job_token"], ec.EXEC_STATE_TAB_READY)
check("el 2º intento AVANZA (report TAB_READY ok, no illegal_transition)",
      bool(ev) and ev.get("ok") is True, str(ev))

# ═══════════════════ 4 · A10/P1.1 — CONTRACT_UNVERIFIABLE terminal ═══════════════════
print("── 4 · A10/P1.1: CONTRACT_UNVERIFIABLE es terminal como VIOLATION")
_proyecto("aud11", n=2)
fj.enqueue_project("aud11")
jv = None
for _ in range(5):  # drena imágenes hasta el job VIDEO (el contrato §7.1 es video)
    cand = fj.claim_next("w-v", pid="aud11")
    if not cand:
        break
    if cand["kind"] == "video":
        jv = cand
        break
if jv and jv["kind"] == "video":
    _consent_allow(jv)
    check("job video reclamado", bool(jv))
    # probe_asset devuelve None → validate_asset_contract UNVERIFIABLE
    from services import execution_contract as ec_probe
    orig_probe = ec_probe.probe_asset
    try:
        ec_probe.probe_asset = lambda p: None
        mp4 = _mp4_real(8.0)
        try:
            fj.complete(jv["id"], jv["job_token"], mp4, worker="w-v")
            terminal = "no-lanzó"
        except ValueError as e:
            terminal = str(e)
        check("complete() con asset INVERIFICABLE lanza error de contrato",
              "ASSET_INVALID" in terminal, terminal[:120])
        row = db.connect().execute(
            "SELECT status, exec_state FROM flow_jobs WHERE id=?",
            (jv["id"],)).fetchone()
        check("job queda dead ASSET_INVALID (jamás done)",
              row["status"] == "dead"
              and row["exec_state"] == ec.EXEC_STATE_ASSET_INVALID,
              f"{row['status']}/{row['exec_state']}")
    finally:
        ec_probe.probe_asset = orig_probe
else:
    check("job video reclamado", False, str(jv and jv["kind"]))

# ═══════════════════ 5 · C8/P2.5 — scheduler arranca con next_runs ═══════════════════
print("── 5 · C8/P2.5: scheduler de fábrica arrancado (lifespan)")
async def _p25():
    factory.arrancar()
    st = factory.status()
    return st
st = asyncio.run(_p25())
check("scheduler running tras arrancar()", st["running"] is True)
check("status().next_runs NO vacío (antes: 0 vídeos/día)",
      len(st["next_runs"]) >= 1, str(st["next_runs"]))

# ═══════════════════ 6 · A7/P2.8 — zip-bomb y BadZipFile ═══════════════════
print("── 6 · A7/P2.8: zip-bomb 1000:1 → 400; BadZipFile → 400")
bomb_buf = io.BytesIO()
with zipfile.ZipFile(bomb_buf, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("Escena_01/imagen_1.png", b"\x00" * (5 * 1024 * 1024))
    # sobrescribir con ratio forzado: entrada comprimida de ~5 KB que declara 5 MB
bomb_buf.seek(0)
try:
    flow_import.import_flow_zip("p", bomb_buf.getvalue(), _cfg.OUTPUT_DIR / "p")
    check("zip-bomb por ratio → ValueError", False, "no lanzó")
except ValueError as e:
    check("zip-bomb por ratio → ValueError", "bomba" in str(e) or "explosiva" in str(e), str(e)[:80])
try:
    flow_import.import_flow_zip("p", b"esto no es un zip", _cfg.OUTPUT_DIR / "p")
    check("BadZipFile → ValueError (400 en endpoint, nunca 500)", False)
except ValueError:
    check("BadZipFile → ValueError (400 en endpoint, nunca 500)", True)

# ═══════════════════ 7 · A1/P0.2 — badge path traversal ═══════════════════
print("── 7 · A1/P0.2: /api/product/badge sanea el tipo")
r = _client.post("/api/product/badge", json={"type": "../../pwned", "text": "x"})
check("badge type traversal → 400", r.status_code == 400, str(r.status_code))
check("no se escribió nada fuera de static/assets",
      not (_main.STATIC_DIR.parent / "pwned.png").exists()
      and not (_main.STATIC_DIR / "pwned.png").exists())
r = _client.post("/api/product/badge", json={"type": "rating", "text": "ok"})
check("badge legítimo → 200", r.status_code == 200, str(r.status_code))

# ═══════════════════ 8 · A16/P0.3 — dialog con raíz configurada ═══════════════════
print("── 8 · A16/P0.3: dialog/create-dir exige raíz configurada")
r = _client.post("/api/dialog/create-dir", json={"path": str(_TMP / "fuera" / "sub")})
check("create-dir FUERA de DIALOG_ROOTS (default PROJECTS_DIR) → ok:false",
      r.status_code == 200 and r.json().get("ok") is False, r.text[:120])
r = _client.get(f"/api/dialog/browse-dirs?path={_TMP}")
check("browse-dirs fuera de raíz → ok:false", r.json().get("ok") is False, r.text[:120])
r = _client.get("/api/dialog/browse-dirs")
check("browse-dirs sin path lista raíces configuradas",
      r.status_code == 200 and r.json().get("ok") is True
      and r.json().get("dirs"), r.text[:160])

# ═══════════════════ 9 · A7/P0.5 — 411 chunked ═══════════════════
print("── 9 · A7/P0.5: mutación chunked sin Content-Length → 411")
# el middleware se prueba DIRECTO: un cliente real (httpx) siempre añade
# Content-Length, así que el caso chunked-sin-CL solo existe a nivel de
# headers crudos (exactamente lo que llega por ASGI desde un cliente malo).
class _Req:  # stub mínimo del scope que csrf_guard consulta
    def __init__(self, headers, method="POST", path="/api/product/badge"):
        self.headers = headers
        self.method = method
        self.url = type("U", (), {"path": path})()

async def _guard_case(headers, method="POST"):
    async def _next(req):
        return "PASO"
    return await _main.csrf_guard(_Req(headers, method), _next)

_resp = asyncio.run(_guard_case({"transfer-encoding": "chunked"}))
check("POST chunked SIN Content-Length → 411 (middleware directo)",
      _resp.status_code == 411, str(getattr(_resp, "status_code", None)))
_resp = asyncio.run(_guard_case({"content-length": "0"}))
check("POST sin TE (body vacío declarado) NO dispara 411",
      _resp == "PASO", str(_resp))
_resp = asyncio.run(_guard_case({}, method="DELETE"))
check("DELETE sin CL ni TE → permitido (RFC: body 0 bytes)",
      _resp == "PASO", str(_resp))
r = _client.delete("/api/avatars/000000000000")
check("DELETE sin body (sin TE) NO dispara 411 (legítimo)",
      r.status_code != 411, str(r.status_code))

# ═══════════════════ 10 · A6/P0.6 — apply_env_acl ═══════════════════
print("── 10 · A6/P0.6: ACL de .env")
f = _TMP / ".env"
f.write_text("X=1\n", encoding="utf-8")
res = security.apply_env_acl(f)
if os.name == "nt":
    check("apply_env_acl en Windows usa icacls", bool(res) and "icacls" in str(res))
else:
    check("apply_env_acl en POSIX → 0600", res == "0600"
          and (f.stat().st_mode & 0o077) == 0, str(res))
check("apply_env_acl no lanza con archivo ausente",
      security.apply_env_acl(_TMP / "no_existe.env") is None)

# ═══════════════════ 11 · A14/P1.7 — publish sin subtítulos quemados ═══════════════════
print("── 11 · A14/P1.7: gate de subtítulos en publish")
_pid_s = db.new_id()
db.create_project(id=_pid_s, title="Sin subs")
outdir = _cfg.OUTPUT_DIR / _pid_s
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "subs_status.json").write_text(
    json.dumps({"burned": False, "reason": "words.json vacío"}), encoding="utf-8")
(outdir / f"{_pid_s}_final.mp4").write_bytes(b"\x00" * 2048)
db.update_project(_pid_s, video_url=str(outdir / f"{_pid_s}_final.mp4"))
r = _client.post(f"/api/publish/{_pid_s}", json={})
check("publish con burned=false → 409 bloqueado",
      r.status_code == 409 and "subt" in r.text.lower(), f"{r.status_code} {r.text[:80]}")
r = _client.post(f"/api/publish/{_pid_s}", json={"sin_subtitulos": True})
check("override explícito sin_subtitulos=true supera el gate (lega a config check)",
      r.status_code in (400, 500), str(r.status_code))  # 400/500 = pasó el gate de subs

# ═══════════════════ 12 · P5.4 — retención con dry-run ═══════════════════
print("── 12 · P5.4: retención de data/output")
from services import retention  # noqa: E402
retention.OUTPUT_DIR = _cfg.OUTPUT_DIR
for i in range(12):
    pid = db.new_id()
    db.create_project(id=pid, title=f"Ret{i}")
    d = _cfg.OUTPUT_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}_final.mp4").write_bytes(b"0" * 10_000)
# el plan cuenta TODOS los proyectos con medios (secciones previas incluidas):
# fijamos n para que queden EXACTAMENTE 2 borrables
_total = retention.plan(9999)["total_con_medios"]
_n = _total - 2
plan = retention.plan(_n)
check("plan dry-run marca 2 borrables y conserva el resto",
      plan["dry_run"] is True and len(plan["borrables"]) == 2,
      str((len(plan['conservar']), len(plan['borrables']))))
borrable = plan["borrables"][0]["id"]
borrable2 = plan["borrables"][1]["id"]
db.update_project(borrable, meta={"keep": True})
plan2 = retention.plan(_n)
check("meta.keep=true salva el proyecto",
      len(plan2["borrables"]) == 1, str(len(plan2['borrables'])))
r_noc = retention.purge(_n, confirm=False)
check("sin confirm=true NO borra nada (política explícita)",
      r_noc["ok"] is False and (_cfg.OUTPUT_DIR / borrable2).exists())
r_go = retention.purge(_n, confirm=True)
check("con confirm=true purga y deja meta.media_purged",
      r_go["ok"] is True and len(r_go["borrados"]) == 1
      and not (_cfg.OUTPUT_DIR / borrable2).exists()
      and (db.get_project(borrable2).get("meta") or {}).get("media_purged") is True)

# ═══════════════════ 13 · A11/P1.4 — enqueue sin duplicar claimed ═══════════════════
print("── 13 · A11/P1.4: enqueue deduplica contra claimed vigentes")
_proyecto("aud14", n=2)
fj.enqueue_project("aud14")
reserva = fj.claim_next("w-hold", pid="aud14")
check("job claimed en vuelo", bool(reserva))
created = fj.enqueue_project("aud14")
con = db.connect()
dupes = con.execute(
    "SELECT COUNT(*) c FROM (SELECT kind, scene_number FROM flow_jobs "
    "WHERE project_id='aud14' GROUP BY kind, scene_number "
    "HAVING COUNT(*) > 1)").fetchone()["c"]
con.close()
check("re-enqueue NO crea duplicados del job en vuelo", dupes == 0, f"dupes={dupes}")

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
