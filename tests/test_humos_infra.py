#!/usr/bin/env python3
"""Batería de HUMOS de infraestructura — «lo declarado EXISTE».

Antecedente: se llegó a reportar como terminado un Flow Bridge (cola SQLite,
bridge.js, endpoints v2.16.2) que NUNCA estuvo en el repo. Esta batería hace
imposible repetirlo: verifica QUE TODO LO QUE DECLARAMOS EXISTE DE VERDAD,
en el código fuente, ANTES de discutir si funciona.

Verifica (por lectura de fuente / AST, sin ejecutar el sistema):
  1. Flow Bridge backend: tabla flow_jobs en SCHEMA, BEGIN IMMEDIATE en el
     motor, helpers de lease/token, convención de assets.
  2. Los 6 endpoints /api/extension/flow/jobs* registrados en main.py + CORS.
  3. P1 del Golden Execution Contract sigue blindado en flow_export.py
     (el video_prompt del Creative Engine es fuente primaria).
  4. Extensión: extension/bridge.js existe con el ciclo poll→claim→heartbeat
     →complete/fail; background.js lo carga con importScripts y tiene los
     puntos de anclaje [bridge v1]; manifest.json es JSON válido con
     permisos de storage/alarms.
  5. Auto-render: el complete dispara orchestrator.start_flow_render.
  6. Las baterías canónicas existen (runner sincronizado).

Uso:  cd yt_automation_v2 && python3 tests/test_humos_infra.py
      python3 -m pytest tests/test_humos_infra.py -q
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def src(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    print("── 1. Flow Bridge backend (cola real, no fantasma)")
    db_src = src(BACKEND / "database.py")
    check("tabla flow_jobs en el SCHEMA de database.py",
          "CREATE TABLE IF NOT EXISTS flow_jobs" in db_src)
    check("columnas del contrato (job_token, lease_until, attempts)",
          all(k in db_src for k in ("job_token", "lease_until", "attempts",
                                    "max_attempts", "asset_path")))
    check("índice por proyecto/estado",
          "idx_flow_jobs_project" in db_src)

    fj_src = src(BACKEND / "services" / "flow_jobs.py")
    check("services/flow_jobs.py EXISTE (motor de la cola)", bool(fj_src))
    check("claim atómico con BEGIN IMMEDIATE",
          "BEGIN IMMEDIATE" in fj_src)
    check("lease por tipo (imagen 8 min · video 15 min)",
          '"image": 8 * 60' in fj_src and '"video": 15 * 60' in fj_src)
    check("reintentos imagen 3 · video 2 → dead",
          '"image": 3' in fj_src and '"video": 2' in fj_src)
    check("nonce del job_token (uuid)",
          "uuid.uuid4().hex" in fj_src)
    check("validación de imagen con PIL", "PIL" in fj_src
          or "from PIL import" in fj_src)
    check("validación de video con ffprobe",
          "probe_duration" in fj_src)
    check("convención de assets flow/Escena_NN_flow.* y Escena_NN_video_*",
          "Escena_{no:02d}_flow" in fj_src
          and "Escena_{no:02d}_video_" in fj_src)
    check("prompts SOLO desde build_script_json (única fuente)",
          "from pipeline.flow_export import" in fj_src
          and "build_script_json(" in fj_src)
    check("recuperación de leases expirados",
          "lease_until < ?" in fj_src or "lease_until <" in fj_src)

    print("── 2. los 6 endpoints /api/extension/flow/jobs* en main.py")
    main_src = src(BACKEND / "main.py")
    rutas = [
        '"/api/extension/flow/jobs/enqueue"',
        '"/api/extension/flow/jobs/next"',
        '"/api/extension/flow/jobs/{job_id}/heartbeat"',
        '"/api/extension/flow/jobs/{job_id}/complete"',
        '"/api/extension/flow/jobs/{job_id}/fail"',
        '"/api/extension/flow/jobs/status/{pid}"',
    ]
    for r in rutas:
        check(f"ruta {r} registrada", r in main_src)
    check("CORS configurado para la extensión (CORSMiddleware)",
          "CORSMiddleware" in main_src)

    print("── 3. P1 del Golden Execution Contract sigue blindado")
    fx_src = src(BACKEND / "pipeline" / "flow_export.py")
    check("_creative_video_prompt existe (fuente primaria del Creative Engine)",
          "def _creative_video_prompt(" in fx_src)
    check("el creative prompt gana antes que ai_stages/plantillas",
          fx_src.find("creative = _creative_video_prompt(sc)") != -1
          and fx_src.find("creative = _creative_video_prompt(sc)")
          < fx_src.find("ai_stages[k][\"video_prompt_en\"]"))
    check("batería P1 existe", (ROOT / "tests" / "test_flow_contract_p1.py")
          .exists())

    print("── 4. extensión: bridge.js de verdad (no fantasma)")
    bridge_path = ROOT / "extension" / "bridge.js"
    bridge_src = src(bridge_path)
    check("extension/bridge.js EXISTE", bridge_path.exists(),
          "«bridge.js fue reportado y no existía» — esta vez sí")
    for fn in ("bridgeClaimNext", "bridgeHeartbeat", "bridgeComplete",
               "bridgeFail", "bridgeEnqueue", "bridgeStatus", "bridgeTick",
               "bridgeLoop"):
        check(f"bridge.js implementa {fn}()", fn in bridge_src)
    check("bridge.js habla con la cola real (endpoint next)",
          "/api/extension/flow/jobs/next" in bridge_src)
    check("bridge.js envía X-API-Key (auth_guard)", "X-API-Key" in bridge_src)
    check("bridge.js heartbeat ~30s",
          re.search(r"30[_\s*]*000|30_000|30\s*\*\s*1000", bridge_src)
          is not None)

    bg_src = src(ROOT / "extension" / "background.js")
    check("background.js carga bridge.js vía importScripts",
          re.search(r"importScripts\([^)]*bridge\.js", bg_src) is not None)
    check("background.js tiene anclajes [bridge v1] (grep-auditable)",
          "[bridge v1]" in bg_src)
    check("background.js resuelve jobs del puente (__bridgeHandleJob)",
          "__bridgeHandleJob" in bg_src)

    manifest_path = ROOT / "extension" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ok_manifest = True
    except Exception:  # noqa: BLE001
        manifest = {}
        ok_manifest = False
    check("manifest.json es JSON válido", ok_manifest)
    check("manifest MV3 con permisos storage+alarms (keepalive del puente)",
          manifest.get("manifest_version") == 3
          and "storage" in manifest.get("permissions", [])
          and "alarms" in manifest.get("permissions", []))

    print("── 5. auto-render al completar el proyecto")
    check("main.py dispara orchestrator.start_flow_render en el complete",
          "start_flow_render" in main_src
          and "auto_render" in main_src)
    orch_src = src(BACKEND / "pipeline" / "orchestrator.py")
    check("orchestrator.start_flow_render existe (async)",
          "async def start_flow_render" in orch_src)
    check("condición renderable (todas las escenas con imagen)",
          "renderable" in fj_src)

    print("── 6. runner de baterías sincronizado")
    runner_src = src(ROOT / "tests" / "run_all.py")
    for b in ("test_flow_contract_p1.py", "test_flow_bridge.py",
              "test_humos_infra.py", "test_production_json.py",
              "test_guion_json.py", "test_merge_216_pyav.py",
              "test_lanzar_preflight.py"):
        check(f"run_all incluye {b}", b in runner_src)

    print("── 7. ESTADO_REAL.md documentado")
    check("ESTADO_REAL.md existe en la raíz del repo",
          (ROOT / "ESTADO_REAL.md").exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_humos_infra():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
