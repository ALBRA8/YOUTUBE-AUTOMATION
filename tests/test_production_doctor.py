#!/usr/bin/env python3
"""Batería PRODUCTION DOCTOR V1.0 — diagnóstico + reparaciones deterministas.

Ejercita en HERMÉTICO (DB SQLite y OUTPUT en tmp, patrón test_flow_bridge):

  · taxonomía (regla 5): 8 clasificaciones, severidades, UNKNOWN→humano
  · capas A/B: production.json corrupto, unidades bloqueadas, paridad BD,
    pérdida de video_prompt en el Adapter (bug simulado por monkeypatch)
  · capa C: video_prompt verbatim (P1) y sanitización que altera la intención
  · capa D: lease vencido, claim inválido, agotado en queued, duplicados,
    huérfanos, done sin asset, dead (externo), cola incompleta, zombies
  · ciclo COMPLETO de la regla 7: AUDIT → FIX → re-audit → VERIFY
  · audit trail (regla 10): campos obligatorios con antes/después
  · regla 6: production.json y prompts creativos INTACTOS tras fix (SHA256)
  · regla 9: UNKNOWN + EXTERNAL_SERVICE_ERROR no disfrazados de PASS
  · CLI in-process: exit codes honestos 0/1/2

Uso:  cd yt_automation_v2 && python3 tests/test_production_doctor.py
      python3 -m pytest tests/test_production_doctor.py -q
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar la app: DB y OUTPUT a tmp ──────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="prod_doctor_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.DATA_DIR = _TMP / "data"
_cfg.OUTPUT_DIR = _TMP / "data" / "output"
_cfg.TMP_DIR = _TMP / "data" / "tmp"
_cfg.MUSIC_DIR = _TMP / "data" / "music"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR, _cfg.MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)
(_cfg.MUSIC_DIR / "falsa.mp3").write_bytes(b"\x00ID3falsa")  # audit_render limpio

import database as db  # noqa: E402  (lee config.DB_PATH ya parcheado)
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


def _ids(findings):
    return [f.id.split("#")[0] for f in findings]


# ── fixtures ─────────────────────────────────────────────────────────────────
_N = [0]


def _job(pid, kind, no, status="queued", attempts=0, max_attempts=None,
         lease=None, token=None, worker=None, asset=None, error=None,
         created="2026-01-01T00:00:00+00:00"):
    """Inserta una fila flow_jobs directa (id único por contador)."""
    _N[0] += 1
    max_attempts = max_attempts if max_attempts is not None \
        else (3 if kind == "image" else 2)
    with db.connect() as con:
        con.execute(
            """INSERT INTO flow_jobs(id, project_id, kind, scene_number, part,
               prompt, prompt_meta, status, attempts, max_attempts, error,
               asset_path, worker, job_token, lease_until, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"job_{_N[0]:04d}", pid, kind, no, 1, "prompt de prueba", "{}",
             status, attempts, max_attempts, error, asset, worker, token,
             lease, created, created))
        con.commit()


def _pipeline_job(pid, jid, status="running"):
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO jobs(id, project_id, kind, "
                    "status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    (jid, pid, "pipeline", status,
                     "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"))
        con.commit()


def _limpiar_cola():
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM jobs")
        con.commit()


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


PJSON_VALIDO = {
    "project": {"title": "Doctor demo", "format": "short"},
    "sequence": [
        {"id": "v1", "type": "scene", "narration": "Primera",
         "image_prompt": "red pan on marble, steam, no text",
         "video_prompt": "DOCTOR_SENTINEL_1 :: the pan slides left slowly",
         "duration": 5},
        {"id": "v2", "type": "scene", "narration": "Segunda",
         "image_prompt": "coffee cup close up, morning light, no text",
         "video_prompt": "DOCTOR_SENTINEL_2 :: the cup rotates into focus",
         "duration": 4},
    ],
    "auto_start": False,
}


def _crear_proyecto(pid, njson=PJSON_VALIDO):
    """Proyecto en BD + production.json en disco + escenas con production_unit."""
    from services.themes import STYLES
    from services import production_json as pj
    estilos = {s["id"] for s in STYLES}
    db.create_project(id=pid, title="Doctor demo", status="draft",
                      mode="production_json", style="auto", format="short")
    data = pj.parse_payload(json.dumps(njson, ensure_ascii=False))
    g, _av, _norm = pj.validate(data, estilos)
    db.replace_scenes(pid, g["escenas"])
    out = _cfg.OUTPUT_DIR / pid
    out.mkdir(parents=True, exist_ok=True)
    (out / "production.json").write_text(
        json.dumps(njson, ensure_ascii=False, indent=2), "utf-8")
    return pid


def _borrar_proyecto(pid):
    db.delete_project(pid)
    shutil.rmtree(_cfg.OUTPUT_DIR / pid, ignore_errors=True)


# ═══ la batería ═══════════════════════════════════════════════════════════════
def main() -> int:
    global OK, FAIL
    OK, FAIL = 0, 0
    from services.production_doctor import audit, fix, verify, SAFE_REPAIRS
    from services.production_doctor.repairs import aplicar_reparaciones
    from services.production_doctor.core import (AuditTrail, Clasificacion,
                                                 DoctorReport, finding,
                                                 TESTS_POR_COMPONENTE,
                                                 cargar_ultimo_reporte)
    from services.production_doctor import layers

    print("── 1. taxonomía y núcleo (regla 5)")
    vals = {c.value for c in Clasificacion}
    check("8 clasificaciones del contrato", vals == {
        "BUG_CONFIRMED", "CONTRACT_VIOLATION", "DATA_ERROR", "CONFIG_ERROR",
        "ENVIRONMENT_ERROR", "EXTERNAL_SERVICE_ERROR", "TEST_FAILURE",
        "UNKNOWN"}, repr(vals))
    try:
        finding("X", "A", "c", "t", "DATA_ERROR", "fatal", {}, "x")
        check("finding() rechaza severidad inventada", False)
    except ValueError:
        check("finding() rechaza severidad inventada", True)
    f_un = finding("X", "A", "c", "t", "UNKNOWN", "warn", {}, "x")
    check("UNKNOWN marca HUMAN INVESTIGATION", f_un.requiere_humano is True)
    f_dn = finding("Y", "A", "c", "t", "DATA_ERROR", "warn", {}, "x")
    check("DATA_ERROR no requiere humano", f_dn.requiere_humano is False)
    check("la lista blanca de reparaciones es cerrada y conocida",
          set(SAFE_REPAIRS) == {
              "recover_expired_leases", "requeue_invalid_claimed",
              "deaden_exhausted_queued", "dedupe_flow_jobs",
              "delete_orphan_jobs", "rebuild_asset_mapping",
              "rebuild_job_queue", "ensure_directories", "cleanup_tmp",
              "fail_zombie_pipeline_jobs"}, repr(set(SAFE_REPAIRS)))

    print("── 2. audit trail persistente (regla 10)")
    trail = AuditTrail(base_dir=_TMP / "trail")
    for i in (1, 2):
        trail.append(finding_id=f"F{i}", diagnostico="d",
                     archivo_afectado="a.py", funcion_afectada="f",
                     cambio="c", motivo="m", test_ejecutado="t",
                     resultado_antes="A", resultado_despues="B")
    (trail.dir / "audit_trail.jsonl").open("a").write("{roto\n")
    entradas = trail.read_all()
    check("append + lectura tolerante a línea dañada", len(entradas) == 2,
          f"n={len(entradas)}")
    check("entrada con los 10 campos obligatorios",
          all(k in entradas[0] for k in (
              "timestamp", "finding_id", "diagnostico", "archivo_afectado",
              "funcion_afectada", "cambio", "motivo", "test_ejecutado",
              "resultado_antes", "resultado_despues")))
    DoctorReport(modo="audit", ts="t", findings=[f_un]).guardar()
    check("report persistido y recargable",
          (cargar_ultimo_reporte() or {}).get("modo") == "audit")

    print("── 3. capa A: production.json (INPUT)")
    _crear_proyecto("doc_sano")
    res_a = layers.audit_input()
    check("proyecto sano → capa A sin findings",
          not [f for f in res_a if "doc_sano" in f.id], repr(_ids(res_a)))
    (_cfg.OUTPUT_DIR / "doc_roto").mkdir(exist_ok=True)
    (_cfg.OUTPUT_DIR / "doc_roto" / "production.json").write_text("{corrupto")
    res_a = layers.audit_input()
    f_il = next((f for f in res_a
                 if f.id.startswith("DOC-A-JSON-ILEGIBLE")), None)
    check("JSON corrupto → DOC-A-JSON-ILEGIBLE DATA_ERROR",
          f_il is not None and f_il.clasificacion == "DATA_ERROR")
    check("el corrupto NO tiene auto-reparación (es el original creativo)",
          f_il is not None and f_il.reparacion_accion is None)
    roto2 = json.loads(json.dumps(PJSON_VALIDO))
    del roto2["sequence"][1]["image_prompt"]
    _crear_proyecto("doc_bloq", roto2)
    res_a = layers.audit_input()
    fb = next((f for f in res_a
               if f.id.startswith("DOC-A-BLOQUEADAS#doc_bloq")), None)
    check("unidad sin image_prompt → DOC-A-BLOQUEADAS", fb is not None)
    check("evidencia nombra sequence[1] e image_prompt",
          fb is not None and any("image_prompt" in x and "sequence[1]" in x
                                 for x in fb.evidencia.get("faltantes", [])))
    check("sin auto-fix: el Creative Engine debe completar el JSON",
          fb is not None and fb.reparacion_accion is None)
    _borrar_proyecto("doc_bloq")   # no contamina capas C/D posteriores
    # paridad BD ↔ sequence con proyecto efímero
    _crear_proyecto("doc_paridad")
    db.replace_scenes("doc_paridad", db.get_scenes("doc_paridad")[:1])
    res_a = layers.audit_input()
    check("escenas BD ≠ sequence → DOC-A-PARIDAD CONTRACT_VIOLATION",
          any(f.id.startswith("DOC-A-PARIDAD#doc_paridad")
              and f.clasificacion == "CONTRACT_VIOLATION" for f in res_a))
    _borrar_proyecto("doc_paridad")

    print("── 4. capa B: ADAPTER (pérdida de campos del contrato)")
    res_b = layers.audit_adapter()
    check("adapter real sin pérdidas en proyectos sanos",
          not [f for f in res_b if "doc_sano" in f.id], repr(_ids(res_b)))
    from services import production_json as pj
    real_validate = pj.validate

    def validate_roto(data, estilos, production_id=None):
        g, av, norm = real_validate(data, estilos, production_id=production_id)
        for e in g.get("escenas", []):
            pu = (e.get("meta") or {}).get("production_unit") or {}
            pu["video_prompt"] = None          # ← pérdida simulada del adapter
        return g, av, norm

    pj.validate = validate_roto
    try:
        res_b = layers.audit_adapter()
    finally:
        pj.validate = real_validate
    check("pérdida de video_prompt → DOC-B-VP-PERDIDO CONTRACT_VIOLATION",
          any(f.id.startswith("DOC-B-VP-PERDIDO") and "doc_sano" in f.id
              for f in res_b), repr(_ids(res_b)))
    check("clasificado como CONTRACT_VIOLATION severity error",
          all(f.clasificacion == "CONTRACT_VIOLATION" and f.severidad == "error"
              for f in res_b if f.id.startswith("DOC-B-")))

    print("── 5. capa C: FLOW EXPORT (P1 verbatim)")
    _limpiar_cola()
    res_c = layers.audit_export()
    check("export real con sentinelas → capa C sin findings",
          not [f for f in res_c if "doc_sano" in f.id], repr(_ids(res_c)))
    import pipeline.flow_export as fe
    real_build = fe.build_script_json

    def build_alterado(*a, **kw):
        data = real_build(*a, **kw)
        for s in data.get("scenes", []):
            if isinstance(s.get("video_prompt"), dict):
                s["video_prompt"]["motion"] = "TEMPLATE DEL MÉTODO (sustituido)"
        return data

    fe.build_script_json = build_alterado
    try:
        res_c = layers.audit_export()
    finally:
        fe.build_script_json = real_build
    fa = [f for f in res_c if f.id.startswith("DOC-C-VP-ALTERADO")]
    check("motion sustituido → DOC-C-VP-ALTERADO (solo escena 1; la última "
          "es SOLO-imagen por diseño)",
          len(fa) == 1 and "doc_sano" in fa[0].id, repr(_ids(res_c)))
    check("evidencia muestra creative vs exportado",
          all("creative" in f.evidencia and "exportado" in f.evidencia
              for f in fa))

    def build_omite(*a, **kw):
        data = real_build(*a, **kw)
        for s in data.get("scenes", []):
            s.pop("video_prompt", None)
        return data

    fe.build_script_json = build_omite
    try:
        res_c = layers.audit_export()
    finally:
        fe.build_script_json = real_build
    fa_u = [f for f in res_c if f.id.startswith("DOC-C-VP-AUSENTE")]
    check("video_prompt omitido → DOC-C-VP-AUSENTE (solo escena 1)",
          len(fa_u) == 1 and "#doc_sano#1" in fa_u[0].id, repr(_ids(res_c)))

    print("── 6. capa D: estados de la cola (FLOW JOBS)")
    _limpiar_cola()
    # cola espejo del export: image1, image2 y video1 (video2 NO: la última
    # escena es SOLO-imagen por diseño del método 9+8)
    for kind, no in (("image", 1), ("image", 2), ("video", 1)):
        _job("doc_sano", kind, no, status="queued")
    res_d = layers.audit_jobs()
    check("cola completa y sana → capa D sin findings",
          not [f for f in res_d if f.id.startswith("DOC-D-")],
          repr(_ids(res_d)))
    _limpiar_cola()
    _job("doc_sano", "video", 2, status="claimed",
         lease="2020-01-01T00:00:00+00:00", token="tok", worker="w1")
    res_d = layers.audit_jobs()
    fv = next((f for f in res_d if f.id == "DOC-D-LEASE-VENCIDO"), None)
    check("lease vencido detectado con evidencia", fv is not None
          and fv.evidencia.get("count") == 1)
    check("lease vencido → reparación recover_expired_leases",
          fv is not None and fv.reparacion_accion == "recover_expired_leases")
    _limpiar_cola()
    _job("doc_sano", "image", 1, status="claimed")   # sin token ni lease
    res_d = layers.audit_jobs()
    check("claimed sin lease/token → BUG_CONFIRMED + requeue_invalid_claimed",
          any(f.id == "DOC-D-CLAIM-INVALIDO"
              and f.clasificacion == "BUG_CONFIRMED"
              and f.reparacion_accion == "requeue_invalid_claimed"
              for f in res_d), repr(_ids(res_d)))
    _limpiar_cola()
    _job("doc_sano", "video", 1, status="queued", attempts=2, max_attempts=2)
    res_d = layers.audit_jobs()
    check("queued agotado → BUG_CONFIRMED + deaden_exhausted_queued",
          any(f.id == "DOC-D-AGOTADO-EN-QUEUED"
              and f.clasificacion == "BUG_CONFIRMED" for f in res_d),
          repr(_ids(res_d)))
    _limpiar_cola()
    for created in ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
                    "2026-01-03T00:00:00+00:00"):
        _job("doc_sano", "image", 1, status="queued", created=created)
    res_d = layers.audit_jobs()
    fd = next((f for f in res_d if f.id == "DOC-D-DUPLICADOS"), None)
    check("duplicados detectados (3 copias, 1 clave)", fd is not None
          and fd.evidencia.get("count") == 1)
    _limpiar_cola()
    _job("proj_borrado", "image", 1, status="queued")
    _job("doc_sano", "image", 1, status="done", asset="/no/existe.png")
    _job("doc_sano", "video", 1, status="dead", error="WebM rechazado (422)")
    _job("doc_sano", "video", 2, status="dead", error="timeout de Flow")
    res_d = layers.audit_jobs()
    check("huérfanos de proyecto borrado → delete_orphan_jobs",
          any(f.id == "DOC-D-HUERFANOS"
              and f.reparacion_accion == "delete_orphan_jobs" for f in res_d),
          repr(_ids(res_d)))
    check("done sin asset → DATA_ERROR SIN auto-fix (remedio: re-encolar)",
          any(f.id == "DOC-D-DONE-SIN-ASSET"
              and f.reparacion_accion is None for f in res_d))
    fd_dead = next((f for f in res_d if f.id == "DOC-D-DEAD"), None)
    check("dead → EXTERNAL_SERVICE_ERROR con evidencia de errores reales",
          fd_dead is not None
          and fd_dead.clasificacion == "EXTERNAL_SERVICE_ERROR"
          and fd_dead.evidencia.get("count") == 2)
    _limpiar_cola()
    _job("doc_sano", "image", 1, status="queued")
    _job("doc_sano", "image", 2, status="queued")
    res_d = layers.audit_jobs()
    fc = next((f for f in res_d if f.id == "DOC-D-COLA-INCOMPLETA"), None)
    check("cola incompleta (falta video1; video2 no se espera por diseño)",
          fc is not None and fc.evidencia.get("count") == 1
          and "doc_sano:video:1" in fc.evidencia.get("muestra", [])
          and fc.reparacion_accion == "rebuild_job_queue",
          repr(fc.evidencia if fc else None))
    _limpiar_cola()
    _pipeline_job("doc_sano", "job_stale")
    res_d = layers.audit_jobs(in_process=False)
    fs = next((f for f in res_d if f.id == "DOC-D-RUNNING-STALE"), None)
    check("running stale fuera de proceso → UNKNOWN + HUMAN INVESTIGATION",
          fs is not None and fs.clasificacion == "UNKNOWN"
          and fs.requiere_humano and fs.reparacion_accion is None)

    print("── 7. ciclo COMPLETO (regla 7): AUDIT → FIX → re-audit → VERIFY")
    _limpiar_cola()
    _job("doc_sano", "video", 1, status="claimed",
         lease="2020-01-01T00:00:00+00:00", token="t", worker="w")
    _job("doc_sano", "image", 1, status="claimed")
    _job("doc_sano", "video", 2, status="queued", attempts=2, max_attempts=2)
    _job("proj_borrado", "image", 1, status="queued")
    _pipeline_job("doc_sano", "job_z")
    sha_antes = _sha256(_cfg.OUTPUT_DIR / "doc_sano" / "production.json")
    rep_audit = audit(probe_http=False)
    check("AUDIT ve los 4 estados rotos",
          {"DOC-D-LEASE-VENCIDO", "DOC-D-CLAIM-INVALIDO",
           "DOC-D-AGOTADO-EN-QUEUED", "DOC-D-HUERFANOS"}
          <= set(_ids(rep_audit.findings)), repr(_ids(rep_audit.findings)))
    rep_fix = fix(ejecutar_tests=False)
    reparados = [f for f in rep_fix.findings if f.reparado]
    check("FIX reparó todos los findings reparables",
          len(reparados) >= 5
          and all(f.reparacion_accion for f in reparados),
          f"reparados={len(reparados)}: {[f.id for f in reparados]}")
    check("FIX no marcó reparado lo irreparable (dead/done-sin-asset/UNKNOWN)",
          all(not f.reparado for f in rep_fix.findings
              if f.reparacion_accion is None))
    res_d2 = layers.audit_jobs(in_process=False)
    check("re-audit de capa D → los 4 estados rotos DESAPARECIERON",
          not [f for f in res_d2 if f.id in (
              "DOC-D-LEASE-VENCIDO", "DOC-D-CLAIM-INVALIDO",
              "DOC-D-AGOTADO-EN-QUEUED", "DOC-D-HUERFANOS")],
          repr(_ids(res_d2)))
    trail_entradas = AuditTrail().read_all()
    check("cada reparación dejó entrada de audit trail",
          len(trail_entradas) >= 5, f"n={len(trail_entradas)}")
    check("trail con archivo .py y función afectada reales",
          all(e.get("archivo_afectado", "").endswith(".py")
              and e.get("funcion_afectada") for e in trail_entradas))
    check("trail con antes/después no vacíos",
          all(e.get("resultado_antes") and e.get("resultado_despues")
              for e in trail_entradas))
    # regla 6: lo creativo NO se tocó
    sha_despues = _sha256(_cfg.OUTPUT_DIR / "doc_sano" / "production.json")
    check("production.json INTACTO tras fix (SHA256 idéntico)",
          sha_antes == sha_despues)
    vps = [((e.get("meta") or {}).get("production_unit") or {})
           .get("video_prompt") for e in db.get_scenes("doc_sano")]
    check("video_prompts creativos INTACTOS en BD tras fix",
          all("DOCTOR_SENTINEL" in (v or "") for v in vps), repr(vps))
    # VERIFY: re-ejecuta capa D limpia
    with db.connect() as con:
        con.execute("DELETE FROM jobs")
        con.commit()
    rep_verify = verify(capas=["D"], componentes=["flow_jobs"],
                        ejecutar_tests=False)
    check("VERIFY re-ejecuta capa D y reporta findings actuales",
          rep_verify.verify.get("capas_ejecutadas") == ["D"])
    check("VERIFY sin findings D recurrentes (cola quedó limpia)",
          not [f for f in rep_verify.findings if f.id.startswith("DOC-D-")],
          repr(_ids(rep_verify.findings)))
    from services.production_doctor.core import REPO_ROOT
    faltan_mapa = [t for ts in TESTS_POR_COMPONENTE.values() for t in ts
                   if not (REPO_ROOT / t).exists()]
    check("TESTS_POR_COMPONENTE apunta a baterías reales del repo",
          not faltan_mapa, repr(faltan_mapa))

    print("── 8. demostración extra + capa G (mapping derivado)")
    _limpiar_cola()
    db.create_project(id="demo", title="Demo", status="draft", mode="idea")
    _job("demo", "video", 1, status="claimed",
         lease="2020-01-01T00:00:00+00:00", token="t", worker="w")
    hallados = [f for f in layers.audit_jobs()
                if f.id == "DOC-D-LEASE-VENCIDO"]
    acciones, _comps = aplicar_reparaciones(hallados)
    queda = [f for f in layers.audit_jobs() if f.id == "DOC-D-LEASE-VENCIDO"]
    print(f"  · FALLO plantado → diagnóstico: {hallados[0].titulo}")
    print(f"  · FIX: {acciones[0]['cambio'][:90]}")
    print(f"  · VERIFY: {'cola limpia ✓' if not queda else 'SIGUE ROTO ✗'}")
    check("demostración E2E: fallo→diagnóstico→fix→verify",
          hallados and acciones and not queda)
    _borrar_proyecto("demo")
    # capa G: image_path perdido con candidato en flow/
    flow_dir = _cfg.OUTPUT_DIR / "doc_sano" / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)
    (flow_dir / "Escena_01_flow.png").write_bytes(b"\x89PNG\r\n\x1a\nfalsa")
    with db.connect() as con:
        con.execute("UPDATE scenes SET image_path='/perdido/Escena_01.png' "
                    "WHERE project_id='doc_sano' AND idx=0")
        con.commit()
    res_g = layers.audit_assets()
    fg = next((f for f in res_g
               if f.id.startswith("DOC-G-IMAGEN-PERDIDA")), None)
    check("image_path perdido con candidato → rebuild_asset_mapping",
          fg is not None and fg.reparacion_accion == "rebuild_asset_mapping"
          and fg.evidencia.get("candidato_en_flow") is True)
    fix(ejecutar_tests=False)
    with db.connect() as con:
        ip = con.execute("SELECT image_path FROM scenes "
                         "WHERE project_id='doc_sano' AND idx=0").fetchone()
    check("FIX re-aplicó el mapping (image_path restaurado al asset real)",
          ip is not None and ip["image_path"]
          and "Escena_01_flow" in ip["image_path"],
          repr(dict(ip) if ip else None))

    print("── 9. capas E/I sobre el repo REAL (estático, sin HTTP)")
    res_e = layers.audit_extension(probe_http=False)
    check("extensión real 2.2.0 → sin findings críticos",
          not [f for f in res_e if f.severidad == "critical"],
          repr(_ids(res_e)))
    ext_real = layers.EXTENSION_DIR
    ext_fake = _TMP / "ext_rota"
    shutil.copytree(ext_real, ext_fake, dirs_exist_ok=True)
    m = json.loads((ext_fake / "manifest.json").read_text())
    m.pop("host_permissions", None)
    (ext_fake / "manifest.json").write_text(json.dumps(m))
    layers.EXTENSION_DIR = ext_fake
    try:
        res_e = layers.audit_extension(probe_http=False)
    finally:
        layers.EXTENSION_DIR = ext_real
    check("manifest sin host_permissions → CONFIG_ERROR critical",
          any(f.id == "DOC-E-HOST-PERMISSIONS" and f.severidad == "critical"
              for f in res_e), repr(_ids(res_e)))
    res_i = layers.audit_render()
    check("entorno real (ffmpeg+ffprobe+disco+music) → capa I sin critical",
          not [f for f in res_i if f.severidad == "critical"],
          repr(_ids(res_i)))

    print("── 10. CLI in-process: exit codes honestos")
    import services.production_doctor.__main__ as docmain
    code = docmain.main(["audit", "--json"])
    check("audit con errores graves presentes → exit 1 (no disfraza)",
          code == 1, f"exit={code}")
    # limpieza total para el caso exit 0
    _limpiar_cola()
    for pid in ("doc_sano", "doc_bloq"):
        try:
            _borrar_proyecto(pid)
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(_cfg.OUTPUT_DIR / "doc_roto", ignore_errors=True)
    code = docmain.main(["audit", "--json"])
    check("audit limpio → exit 0", code == 0, f"exit={code}")
    try:
        docmain.main(["modo_inventado"])
        check("modo inválido → exit 2", False)
    except SystemExit as e:
        check("modo inválido → exit 2", e.code == 2)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_bateria_production_doctor():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
