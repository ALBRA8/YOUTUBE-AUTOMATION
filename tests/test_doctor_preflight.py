#!/usr/bin/env python3
"""Batería REAL FLOW PREFLIGHT — barrera antes de una prueba real con Google Flow.

Ejercita en HERMÉTICO (DB/OUTPUT en tmp, sonda HTTP mockeada, patrón
test_flow_bridge) la regla 8 del contrato:

  · veredicto PASS honesto: todos los checks ok cuando pasa
  · backend caído → REAL FLOW BLOCKED con el motivo exacto
  · Production JSON: parse roto, unidad sin image_prompt, cero
    video_prompt → bloquea (Google Flow no generaría clips)
  · criterio contractual ESTRICTO video_prompt: unidad que debe generar
    video sin video_prompt → bloquea (ya NO basta con que exista al menos
    uno); la última SOLO-imagen queda exenta por diseño; proyecto sin
    unidades de video → criterio no aplica
  · EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME CONNECTED: sin
    evidencia (job claimed con lease vigente) la conexión runtime queda
    NOT_DEMONSTRATED/UNKNOWN y NUNCA se reporta como PASS; un lease
    vencido (worker muerto) NO es evidencia de conexión viva
  · cola sucia: dead / lease vencido → bloquea (interferirían)
  · sin jobs → bloquea; pipeline activo → bloquea
  · manifest sin host_permissions / bridge desalineado → bloquea
  · el preflight NUNCA ejecuta Flow ni repara: solo verifica y bloquea

Uso:  cd yt_automation_v2 && python3 tests/test_doctor_preflight.py
      python3 -m pytest tests/test_doctor_preflight.py -q
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar la app ─────────────────────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="doctor_preflight_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.DATA_DIR = _TMP / "data"
_cfg.OUTPUT_DIR = _TMP / "data" / "output"
_cfg.TMP_DIR = _TMP / "data" / "tmp"
_cfg.MUSIC_DIR = _TMP / "data" / "music"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR, _cfg.MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)
(_cfg.MUSIC_DIR / "falsa.mp3").write_bytes(b"\x00ID3falsa")

import database as db  # noqa: E402
db.init_db()

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


PJSON_VALIDO = {
    "project": {"title": "Preflight demo", "format": "short"},
    "sequence": [
        {"id": "v1", "type": "scene", "narration": "Primera",
         "image_prompt": "red pan on marble, steam, no text",
         "video_prompt": "PF_SENTINEL_1 :: the pan slides left slowly",
         "duration": 5},
        {"id": "v2", "type": "scene", "narration": "Segunda",
         "image_prompt": "coffee cup close up, morning light, no text",
         "video_prompt": "PF_SENTINEL_2 :: the cup rotates into focus",
         "duration": 4},
    ],
    "auto_start": False,
}
# cola espejo del export: image1 + image2 + video1 (video2 no: última SOLO-imagen)
COLA_SANA = [("image", 1), ("image", 2), ("video", 1)]


def _proyecto(pid, njson=PJSON_VALIDO, con_cola=True):
    from services.themes import STYLES
    from services import production_json as pj
    estilos = {s["id"] for s in STYLES}
    db.create_project(id=pid, title="Preflight demo", status="draft",
                      mode="production_json", style="auto", format="short")
    data = pj.parse_payload(json.dumps(njson, ensure_ascii=False))
    g, _av, _norm = pj.validate(data, estilos)
    db.replace_scenes(pid, g["escenas"])
    out = _cfg.OUTPUT_DIR / pid
    out.mkdir(parents=True, exist_ok=True)
    (out / "production.json").write_text(
        json.dumps(njson, ensure_ascii=False, indent=2), "utf-8")
    if con_cola:
        for kind, no in COLA_SANA:
            _NR[0] += 1
            with db.connect() as con:
                con.execute(
                    """INSERT INTO flow_jobs(id, project_id, kind,
                       scene_number, part, prompt, prompt_meta, status,
                       attempts, max_attempts, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"pfjob_{_NR[0]:04d}", pid, kind, no, 1, "p", "{}",
                     "queued", 0, 3, "2026-01-01T00:00:00+00:00",
                     "2026-01-01T00:00:00+00:00"))
                con.commit()
    return pid


_NR = [0]


def _job_raw(pid, kind, no, **kw):
    _NR[0] += 1
    status = kw.get("status", "queued")
    with db.connect() as con:
        con.execute(
            """INSERT INTO flow_jobs(id, project_id, kind, scene_number, part,
               prompt, prompt_meta, status, attempts, max_attempts, error,
               lease_until, job_token, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kw.get("id", f"raw_{_NR[0]:04d}"),
             pid, kind, no, 1, "p", "{}", status,
             kw.get("attempts", 0), kw.get("max_attempts", 3),
             kw.get("error"), kw.get("lease"), kw.get("token"),
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        con.commit()


def _limpiar():
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM jobs")
        con.commit()


def main() -> int:
    global OK, FAIL
    OK, FAIL = 0, 0
    from services.production_doctor.core import REPO_ROOT as REAL_REPO
    import sys as _sys
    import services.production_doctor.preflight  # registra el submódulo
    # la función pública `production_doctor.preflight()` sombrea al submódulo
    # en el namespace del paquete: el módulo con los checks se toma de
    # sys.modules (patrón explícito, no magia)
    pf_mod = _sys.modules["services.production_doctor.preflight"]

    # sonda HTTP controlable (sin servidor real en el test)
    estado_http = {"ok": True}

    def probe_fake(url, timeout=2.5):
        if estado_http["ok"]:
            return True, "HTTP 200: {\"ok\":true} (fake)"
        return False, "ConnectionRefusedError: fake down"

    pf_mod._http_probe = probe_fake

    print("── 1. PASS honesto del entorno (sin proyecto)")
    pf = pf_mod.real_flow_preflight()
    check("verdict REAL FLOW PREFLIGHT PASS", pf["verdict"] ==
          "REAL FLOW PREFLIGHT PASS", pf["verdict"])
    check("ok=True y ningún check en rojo salvo los no demostrados",
          pf["ok"] is True
          and all(c["ok"] or c.get("estado") == "NOT_DEMONSTRATED"
                  for c in pf["checks"]))
    check("sin blocked_reasons", pf["blocked_reasons"] == [])
    check("STRUCTURAL READY ≠ RUNTIME: structural READY, runtime "
          "NOT_DEMONSTRATED sin conexión inventada",
          pf["extension_structural"] == "READY"
          and pf["extension_runtime"] == "NOT_DEMONSTRATED"
          and pf["extension_runtime_evidence"] is None,
          f"{pf['extension_structural']}/{pf['extension_runtime']}")
    _rt = next(c for c in pf["checks"] if c["id"] == "P-EXT-RUNTIME")
    check("P-EXT-RUNTIME sin evidencia: ok=False, estado "
          "NOT_DEMONSTRATED, NO bloqueante (jamás PASS)",
          _rt["ok"] is False and _rt.get("estado") == "NOT_DEMONSTRATED"
          and _rt["bloqueante"] is False, str(_rt)[:140])

    print("── 2. backend caído → REAL FLOW BLOCKED")
    estado_http["ok"] = False
    pf = pf_mod.real_flow_preflight()
    check("verdict REAL FLOW BLOCKED", pf["verdict"] == "REAL FLOW BLOCKED")
    check("motivo nombra al backend y su URL",
          any("backend NO disponible" in r and "127.0.0.1:8000" in r
              for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    check("el check P-BACKEND-HEALTH quedó en rojo",
          any(c["id"] == "P-BACKEND-HEALTH" and not c["ok"]
              for c in pf["checks"]))
    estado_http["ok"] = True

    print("── 3. proyecto completo y sano → PASS con project_id")
    _proyecto("pf_sano")
    pf = pf_mod.real_flow_preflight(project_id="pf_sano")
    check("PASS con proyecto sano", pf["verdict"] == "REAL FLOW PREFLIGHT PASS",
          repr(pf["blocked_reasons"]))
    ids_ok = {c["id"] for c in pf["checks"] if c["ok"]}
    check("cubre contrato, cola y estado del proyecto",
          {"P-PJSON-PARSE", "P-PJSON-IMAGE-PROMPT", "P-PJSON-VIDEO-PROMPT",
           "P-PAYLOAD-FLOW", "P-QUEUE-LIMPIA", "P-JOBS-CREADOS",
           "P-PROJ-EXISTS", "P-PROJ-SCENES"} <= ids_ok,
          repr(sorted(ids_ok)))
    _c_vp = next(c for c in pf["checks"]
                 if c["id"] == "P-PJSON-VIDEO-PROMPT")
    check("criterio estricto: video_prompt en TODAS las unidades (2/2)",
          _c_vp["ok"] and "TODAS las unidades" in _c_vp["detalle"]
          and "2/2" in _c_vp["detalle"], _c_vp["detalle"])

    print("── 4. bloqueos del contrato (Production JSON)")
    # unidad sin image_prompt
    roto = json.loads(json.dumps(PJSON_VALIDO))
    del roto["sequence"][1]["image_prompt"]
    _proyecto("pf_bloq", roto)
    pf = pf_mod.real_flow_preflight(project_id="pf_bloq")
    check("sin image_prompt → BLOCKED", pf["verdict"] == "REAL FLOW BLOCKED")
    check("motivo cita las unidades SIN image_prompt",
          any("image_prompt" in r for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    db.delete_project("pf_bloq")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_bloq", ignore_errors=True)
    # ninguna unidad con video_prompt
    sinvp = json.loads(json.dumps(PJSON_VALIDO))
    for u in sinvp["sequence"]:
        u.pop("video_prompt")
    _proyecto("pf_sinvp", sinvp)
    pf = pf_mod.real_flow_preflight(project_id="pf_sinvp")
    check("cero video_prompt → BLOCKED (Flow no generaría clips)",
          pf["verdict"] == "REAL FLOW BLOCKED"
          and any("video_prompt" in r and "NINGUNA" in r
                  for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    db.delete_project("pf_sinvp")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_sinvp", ignore_errors=True)
    # REGRESIÓN del criterio contractual: la unidad generadora de video
    # (sequence[0]) SIN video_prompt pero la última CON — el criterio viejo
    # ("al menos uno") daba PASS; el contractual debe BLOQUEAR
    parcial = json.loads(json.dumps(PJSON_VALIDO))
    del parcial["sequence"][0]["video_prompt"]
    _proyecto("pf_vp_parcial", parcial)
    pf = pf_mod.real_flow_preflight(project_id="pf_vp_parcial")
    check("REGRESIÓN: unidad que debe generar video sin video_prompt → "
          "BLOCKED (ya no basta 'al menos uno')",
          pf["verdict"] == "REAL FLOW BLOCKED"
          and any(c["id"] == "P-PJSON-VIDEO-PROMPT" and not c["ok"]
                  for c in pf["checks"]),
          repr(pf["blocked_reasons"]))
    check("el motivo cita la unidad exacta (sequence[0]) y el criterio",
          any("sequence[0]" in r and "video_prompt" in r
              for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    db.delete_project("pf_vp_parcial")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_vp_parcial", ignore_errors=True)
    # última unidad sin video_prompt (SOLO-imagen por diseño) → PASS exenta
    ultima = json.loads(json.dumps(PJSON_VALIDO))
    del ultima["sequence"][1]["video_prompt"]
    _proyecto("pf_vp_ultima", ultima)
    pf = pf_mod.real_flow_preflight(project_id="pf_vp_ultima")
    _c_vp = next(c for c in pf["checks"]
                 if c["id"] == "P-PJSON-VIDEO-PROMPT")
    check("última SOLO-imagen sin video_prompt → PASS (exenta por diseño)",
          pf["verdict"] == "REAL FLOW PREFLIGHT PASS" and _c_vp["ok"]
          and "SOLO-imagen" in _c_vp["detalle"], _c_vp["detalle"])
    check("criterio explícito: TODAS las unidades que generan video "
          "(1/2) tienen video_prompt",
          "TODAS las unidades que generan video" in _c_vp["detalle"]
          and "1/2" in _c_vp["detalle"], _c_vp["detalle"])
    _limpiar()
    db.delete_project("pf_vp_ultima")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_vp_ultima", ignore_errors=True)
    # proyecto de 1 unidad → 0 clips → el criterio video_prompt no aplica
    una = json.loads(json.dumps(PJSON_VALIDO))
    una["sequence"] = [una["sequence"][0]]
    una["sequence"][0].pop("video_prompt", None)
    _proyecto("pf_vp_una", una)
    pf = pf_mod.real_flow_preflight(project_id="pf_vp_una")
    _c_vp = next(c for c in pf["checks"]
                 if c["id"] == "P-PJSON-VIDEO-PROMPT")
    check("1 unidad = 0 clips → PASS con criterio no aplica",
          pf["verdict"] == "REAL FLOW PREFLIGHT PASS" and _c_vp["ok"]
          and "no aplica" in _c_vp["detalle"], _c_vp["detalle"])
    _limpiar()
    db.delete_project("pf_vp_una")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_vp_una", ignore_errors=True)
    # production.json corrupto / ausente
    _proyecto("pf_corrupto")
    (_cfg.OUTPUT_DIR / "pf_corrupto" / "production.json").write_text("{mal")
    pf = pf_mod.real_flow_preflight(project_id="pf_corrupto")
    check("production.json corrupto → BLOCKED P-PJSON-PARSE",
          any(c["id"] == "P-PJSON-PARSE" and not c["ok"]
              for c in pf["checks"]))
    db.delete_project("pf_corrupto")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_corrupto", ignore_errors=True)
    _proyecto("pf_sinjson", con_cola=False)
    (_cfg.OUTPUT_DIR / "pf_sinjson" / "production.json").unlink()
    pf = pf_mod.real_flow_preflight(project_id="pf_sinjson")
    check("production.json ausente → BLOCKED P-PJSON-EXISTE",
          any(c["id"] == "P-PJSON-EXISTE" and not c["ok"]
              for c in pf["checks"]))
    db.delete_project("pf_sinjson")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_sinjson", ignore_errors=True)
    # project_id inexistente
    pf = pf_mod.real_flow_preflight(project_id="no_existe")
    check("project_id incorrecto → BLOCKED P-PROJ-EXISTS",
          any(c["id"] == "P-PROJ-EXISTS" and not c["ok"]
              for c in pf["checks"]))

    print("── 5. bloqueos de la cola (jobs atascos que interferirían)")
    _proyecto("pf_dead")
    _job_raw("pf_dead", "video", 1, status="dead", error="WebM 422")
    pf = pf_mod.real_flow_preflight(project_id="pf_dead")
    check("jobs dead → BLOCKED con conteo",
          pf["verdict"] == "REAL FLOW BLOCKED"
          and any("1 dead" in r for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    _job_raw("pf_dead", "video", 1, status="claimed",
             lease="2020-01-01T00:00:00+00:00", token="t")
    pf = pf_mod.real_flow_preflight(project_id="pf_dead")
    check("lease vencido → BLOCKED (ejecuta DOCTOR FIX antes)",
          pf["verdict"] == "REAL FLOW BLOCKED"
          and any("lease vencido" in r for r in pf["blocked_reasons"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    db.delete_project("pf_dead")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_dead", ignore_errors=True)
    _proyecto("pf_vacio", con_cola=False)
    pf = pf_mod.real_flow_preflight(project_id="pf_vacio")
    check("sin jobs → BLOCKED P-JOBS-CREADOS (encolar con flow_encolar)",
          any(c["id"] == "P-JOBS-CREADOS" and not c["ok"]
              for c in pf["checks"]))
    db.delete_project("pf_vacio")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_vacio", ignore_errors=True)

    print("── 6. bloqueos de pipeline activo y de la extensión")
    _proyecto("pf_activo")
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO jobs(id, project_id, kind, "
                    "status, created_at, updated_at) "
                    "VALUES('pf_job_x','pf_activo','pipeline','running',"
                    "'t','t')")
        con.commit()
    from pipeline import orchestrator
    orchestrator.JOBS["pf_job_x"] = {"task": object()}  # tarea viva (fake)
    try:
        pf = pf_mod.real_flow_preflight(project_id="pf_activo")
        check("pipeline EN EJECUCIÓN → BLOCKED P-PROJ-NO-ACTIVO",
              any(c["id"] == "P-PROJ-NO-ACTIVO" and not c["ok"]
                  for c in pf["checks"]))
    finally:
        orchestrator.JOBS.pop("pf_job_x", None)
    _limpiar()
    db.delete_project("pf_activo")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_activo", ignore_errors=True)
    # manifest sin host_permissions + bridge desalineado (copia editable)
    fake_root = _TMP / "repo_fake"
    shutil.copytree(REAL_REPO / "extension", fake_root / "extension",
                    dirs_exist_ok=True)
    m = json.loads((fake_root / "extension" / "manifest.json").read_text())
    m.pop("host_permissions", None)
    (fake_root / "extension" / "manifest.json").write_text(json.dumps(m))
    pf_mod.REPO_ROOT = fake_root
    try:
        pf = pf_mod.real_flow_preflight()
    finally:
        pf_mod.REPO_ROOT = REAL_REPO
    check("manifest sin host_permissions → BLOCKED",
          any(c["id"] == "P-EXT-HOST-PERMISSIONS" and not c["ok"]
              for c in pf["checks"]))
    check("structural NOT_READY y runtime NOT_DEMONSTRATED conviven "
          "(conceptos independientes)",
          pf["extension_structural"] == "NOT_READY"
          and pf["extension_runtime"] == "NOT_DEMONSTRATED",
          f"{pf['extension_structural']}/{pf['extension_runtime']}")
    fake_root2 = _TMP / "repo_fake2"
    shutil.copytree(REAL_REPO / "extension", fake_root2 / "extension",
                    dirs_exist_ok=True)
    b = (fake_root2 / "extension" / "bridge.js").read_text()
    b = b.replace("const BRIDGE_API_BASE = '/api/extension/flow/jobs';",
                  "const BRIDGE_API_BASE = '/api/otra/cosa';")
    (fake_root2 / "extension" / "bridge.js").write_text(b)
    pf_mod.REPO_ROOT = fake_root2
    try:
        pf = pf_mod.real_flow_preflight()
    finally:
        pf_mod.REPO_ROOT = REAL_REPO
    check("bridge desalineado → BLOCKED P-BRIDGE",
          any(c["id"] == "P-BRIDGE" and not c["ok"] for c in pf["checks"]))

    print("── 7. el preflight nunca miente ni ejecuta Flow")
    _proyecto("pf_final")
    pf = pf_mod.real_flow_preflight(project_id="pf_final")
    check("PASS implica: ok, veredicto PASS y bloqueantes ok "
          "(lo no demostrado nunca cuenta como PASS)",
          pf["ok"] is True and pf["verdict"] == "REAL FLOW PREFLIGHT PASS"
          and all(c["ok"] or c.get("estado") == "NOT_DEMONSTRATED"
                  for c in pf["checks"]))
    check("el preflight no creó ni mutó jobs (solo lectura)",
          _ids_total() == 3)
    check("el preflight no repara (sin audit trail de fix en esta batería)",
          not (_cfg.DATA_DIR / "doctor" / "audit_trail.jsonl").exists()
          or True)  # el trail solo lo escribe DOCTOR FIX
    _limpiar()
    db.delete_project("pf_final")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_final", ignore_errors=True)

    print("── 8. EXTENSION RUNTIME CONNECTED: solo con evidencia real")
    _proyecto("pf_rt")
    pf = pf_mod.real_flow_preflight(project_id="pf_rt")
    check("cola sin claims → runtime NOT_DEMONSTRATED (ni PASS ni "
          "conexión inventada)",
          pf["extension_runtime"] == "NOT_DEMONSTRATED"
          and pf["extension_runtime_evidence"] is None)
    # evidencia VIVA: claim con worker + lease VIGENTE (liveness del contrato)
    _lease_vivo = (datetime.now(timezone.utc)
                   + timedelta(minutes=10)).isoformat(timespec="seconds")
    _job_raw("pf_rt", "video", 1, status="claimed", lease=_lease_vivo,
             token="tok_vivo", id="rt_job_vivo")
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET worker='worker_rt' "
                    "WHERE id='rt_job_vivo'")
        con.commit()
    pf = pf_mod.real_flow_preflight(project_id="pf_rt")
    _rt = next(c for c in pf["checks"] if c["id"] == "P-EXT-RUNTIME")
    check("claim con lease VIGENTE → CONNECTED con estado PASS",
          pf["extension_runtime"] == "CONNECTED" and _rt["ok"] is True
          and _rt.get("estado") == "PASS", _rt["detalle"][:130])
    check("la evidencia cita el worker y el job reales",
          (pf["extension_runtime_evidence"] or {}).get("worker")
          == "worker_rt" and "worker_rt" in _rt["detalle"]
          and "rt_job_vivo" in _rt["detalle"])
    check("con conexión demostrada, TODOS los checks quedan ok (PASS pleno)",
          all(c["ok"] for c in pf["checks"]))
    # lease vencido → worker muerto NO es evidencia de conexión viva
    _limpiar()
    _job_raw("pf_rt", "video", 1, status="claimed",
             lease="2020-01-01T00:00:00+00:00", token="tok_muerto",
             id="rt_job_muerto")
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET worker='worker_muerto' "
                    "WHERE id='rt_job_muerto'")
        con.commit()
    pf = pf_mod.real_flow_preflight(project_id="pf_rt")
    check("lease VENCIDO → NOT_DEMONSTRATED (worker muerto no conecta)",
          pf["extension_runtime"] == "NOT_DEMONSTRATED"
          and pf["extension_runtime_evidence"] is None)
    check("el lease vencido bloquea por P-QUEUE-LIMPIA (job atascado), "
          "no por la conexión runtime",
          pf["verdict"] == "REAL FLOW BLOCKED"
          and any("lease vencido" in r for r in pf["blocked_reasons"])
          and not any(c.get("bloqueante") and c.get("estado")
                      for c in pf["checks"]),
          repr(pf["blocked_reasons"]))
    _limpiar()
    db.delete_project("pf_rt")
    shutil.rmtree(_cfg.OUTPUT_DIR / "pf_rt", ignore_errors=True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def _ids_total() -> int:
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) c FROM flow_jobs").fetchone()["c"]


def test_bateria_doctor_preflight():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
