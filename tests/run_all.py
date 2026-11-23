#!/usr/bin/env python3
"""Runner de las baterías canónicas de tests (fuente de verdad).

Ejecuta las baterías canónicas en orden, cada una en su PROPIO proceso python3
(aislamiento total de sys.modules), imprime un resumen por batería
(X OK · Y fallos) y un total. Exit code != 0 si alguna batería falla
o no puede ejecutarse.

Uso:  cd yt_automation_v2 && python3 tests/run_all.py

[CIERRE D1-D8] Funciones de operatividad verificables:

  D1 · AISLAMIENTO DEL DUEÑO: cada corrida crea un directorio temporal y
       exporta a cada hijo DATA_DIR / DB_PATH / OUTPUT_DIR / TMP_DIR /
       PROJECTS_DIR / MUSIC_DIR / TEMP_DIR (config.py los lee por variable
       de entorno con default histórico). La suite NUNCA muta
       backend/data/yt_automation.db ni escribe en data/output del dueño.
       En serie (--workers 1, default) los hijos comparten la SQLite
       temporal de la corrida (semántica secuencial histórica); con
       --workers N>1 cada batería recibe SU PROPIO directorio de datos
       (aislamiento duro entre baterías concurrentes).
  D3 · PARALELIZACIÓN OPT-IN: `--workers N` (default 1 = serie). Con N>1
       el aislamiento por batería es OBLIGATORIO y automático. La ganancia
       debe medirse en la máquina del dueño; nunca se anuncia sin medir.
  D4 · TIMEOUT POR BATERÍA: `--timeout-seg` (default env
       RUN_ALL_BATTERY_TIMEOUT_S o 300 s). Al vencer, se mata el ÁRBOL de
       procesos (taskkill /T /F en Windows; os.killpg SIGKILL en POSIX) y
       la batería se cuenta como fallo "<nombre>: TIMEOUT".
  D6 · REGISTRO CANÓNICO: EXCLUDED_BATTERIES (motivo escrito por batería)
       + batería guardián tests/test_registro_baterias.py: falla si aparece
       un test_*.py que no esté en BATERIAS ni en EXCLUDED_BATTERIES.
  D7 · --hermetica: antepone tests/hermetic_guard/ al PYTHONPATH de cada
       hijo; su sitecustomize parchea socket.getaddrinfo/connect y BLOQUEA
       la red externa de verdad (loopback permitido).
  D8 · SKIP visible: una batería con "0 OK · 0 fallos" NO es verde: se
       reporta como SKIP y se lista aparte en el total.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# [D5] la propia runner también puede correr a mano en consola cp1252
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
GUARDIA_RED_DIR = TESTS_DIR / "hermetic_guard"

BATERIAS = [
    "test_guion_json.py",        # contrato legacy guion_json + MCP (42 checks)
    "test_production_json.py",   # adapter Production JSON 2.16 (76 checks)
    "test_merge_216_pyav.py",    # merge/integración 2.16.x + fix PyAV (51 checks)
    "test_lanzar_preflight.py",  # preflight de lanzamiento vía MCP (29 checks)
    "test_flow_contract_p1.py",  # GOLDEN EXECUTION CONTRACT P1: video_prompt
                                 # del Creative Engine llega verbatim a Flow (44)
    "test_flow_bridge.py",       # FLOW BRIDGE v1: cola real claim/lease/
                                 # heartbeat/complete/fail + 6 endpoints (48)
    "test_golden_fixture.py",    # FIXTURE GOLDEN oficial: cadena completa con
                                 # DB (fixture → ingest → export → cola → QA)
    "test_qa_forensics.py",      # QA FORENSE de medios: pantalla negra/azul,
                                 # audio silencioso, propagación de warns (30)
    "test_production_doctor.py", # PRODUCTION DOCTOR V1.0: capas A-I, taxonomía,
                                 # reparaciones seguras, audit trail, SHA de lo
                                 # creativo invariante (54)
    "test_doctor_preflight.py",  # REAL FLOW PREFLIGHT: barrera antes de gastar
                                 # una prueba real con Google Flow; criterio
                                 # estricto video_prompt + STRUCTURAL ≠
                                 # RUNTIME NOT_DEMONSTRATED (38)
    "test_concurrencia.py",      # concurrencia: raza de claims, multi-proyecto,
                                 # token de una sola era, completes paralelos
                                 # (+ D2: completes con carga de CPU 3/3)
    "test_chaos.py",             # chaos: reinicio REAL de proceso, rollback,
                                 # doble complete, asset corrupto, zombie
    "test_10_escenas.py",        # ESCALA: proyecto de 10 escenas (19 jobs),
                                 # P1 verbatim + prompt de ~11KB + QA a escala
    "test_autopublish_generate.py", # pipeline _run completo con mocks +
                                 # QA gate real + autopublish (idempotencia v2.19)
    "test_burn_subtitles_resilience.py", # INT-012: burn_subtitles con preset
                                 # veryfast + timeout que degrada honesto en
                                 # vez de tumbar el pipeline (16)
    "test_typography.py",        # INT-021: tipografía Montserrat embarcada +
                                 # contraste dinámico WCAG >= 4.5 + fuente
                                 # (tabla name) + build_ass shorts/legacy +
                                 # matching libass A/B vía MD5 real (59)
    "test_mcp_manager.py",       # INT-022: MCP Connection Manager — cliente
                                 # stdio persistente (connect/handshake/
                                 # execute), inyección dinámica de notebook_id
                                 # (payload > .env), preflight AUTH_REQUIRED,
                                 # timeouts con limpieza y endpoints /api/mcp/* (38)
    "test_pipeline_orchestrator.py", # INT-023: Pipeline Orchestrator — handoff
                                 # NotebookLM → Agente → Flow con mocks herméticos:
                                 # pre-flight gatekeeper (aborta sin gastar
                                 # tokens), blueprint con motor existente +
                                 # contexto inyectado, consistencia de personaje
                                 # @{ref}, PARTIAL_FAILURES + retry SOLO de
                                 # escenas fallidas, endpoints /api/pipeline/* (55)
    "test_int023b_notebook_id.py", # INT-023.4 HOTFIX: propagación y auto-
                                 # descubrimiento de notebook_id — parser de
                                 # list_notebooks, FAIL-FAST MISSING_NOTEBOOK_ID
                                 # en execute (fin del TOOL_ERROR críptico del
                                 # servidor), pre-flight [0/3] auto-descubre o
                                 # aborta con PRE_FLIGHT_MISSING_NOTEBOOK_ID
                                 # antes de gastar tokens, fallback .env al
                                 # estado, endpoints /mcp/list-notebooks y
                                 # /pipeline/run sin id a nivel HTTP (~33)
    "test_int025_google_session.py",  # INT-025/026: sesión Google unificada
                                 # (google_profile_global) — launcher del Chrome
                                 # de login con perfil compartido + CDP en
                                 # FLOW_CDP_PORT (launch-auth-browser multi-
                                 # pestaña flow.google.com + notebooklm),
                                 # captura de cookies CDP → storage_state.json
                                 # de notebooklm-py (layouts moderno/legacy),
                                 # errores estables CHROME_*/PLAYWRIGHT_MISSING/
                                 # NO_GOOGLE_COOKIES, inyección del perfil en
                                 # _spawn, endpoints HTTP y contrato UI v2.24.0
                                 # (botón «Vincular Sesión Google (Login Único)»
                                 # + dropdown auto-poblado) (~78)
    "test_int024_assembler.py",  # INT-024: Asset Harvester & FFmpeg Video
                                 # Assembler — Stage 3.5 harvest a rutas
                                 # deterministas + manifest estricto validado,
                                 # duration math (trim/loop/kenburns),
                                 # captions .srt exactas, construcción de
                                 # comandos ffmpeg en dry-run (scale/crop/
                                 # stream_loop/zoompan/apad/volume=-20dB/
                                 # subtitles), gatekeeper del render en el
                                 # orquestador, endpoints /api/pipeline/*
                                 # y micro-render REAL de humo si hay ffmpeg (56)
    "test_memorydv.py",          # MemoryDV §memoria: storage/retrieval/
                                 # consolidación/isolation (36)
    "test_skills_autonomia.py",  # Skill Contract §skills + autonomía L0-L5
                                 # §26 (34)
    "test_security_hardening.py", # SEGURIDAD §30: path traversal, SSRF,
                                 # anti-inyección, auth /mcp, chmod token (47)
    "test_gobernanza.py",        # GOBERNANZA v2.19: QA gate del render,
                                 # anti zombie-loop, métricas §28, MCP
                                 # gobernanza, autonomía, publish_state (28)
    "test_bridge_e2e.py",        # E2E extensión: node --check + bridge.js real
                                 # contra backend mock (sandbox VM) (42)
    "test_extension_resolver.py", # RESOLVER/INYECTOR de editor (ext 2.2.2):
                                 # estrategias aisandbox/textarea/contenteditable/
                                 # slate-legacy, vetos, inserción por eventos,
                                 # verificación de valor y diagnóstico (70)
    "test_extension_tab_selector.py", # SELECTOR DE PESTAÑA FLOW ([bridge v3],
                                 # ext 2.2.3): fin del tabs[0] arbitrario —
                                 # orden de preferencia + sonda REAL de
                                 # executeScript + fallback entre candidatas (58)
    "test_extension_error_tile.py", # FIX error-tile ([error-tile v2], ext
                                 # 2.2.4): fin del falso positivo — el
                                 # flow-error-tile solo es fatal SIN evidencia
                                 # de resultados; código REAL en SW simulado (54)
    "test_flow_video_v3.py",     # FLOW VIDEO v3 ([video-window v3]+[attempt v3]
                                 # +[flow-adaptation v1.1], ext 2.3.1): ventana de
                                 # video 15 min configurable, JOB vs ATTEMPT,
                                 # P1/P2, taxonomía V1.1 A-I, retry limitado,
                                 # FLOW_ADAPTATION_REQUIRED; código REAL en SW
                                 # simulado + DB tmp (123)
    "test_flow_observability_v11.py", # FLOW OBSERVABILITY V1.1 (ext 2.3.1):
                                 # 4xx/5xx como evidencia cruda (fetch+XHR),
                                 # notificaciones flow_notification, taxonomía
                                 # A-I (watchdog ≠ proveedor), prioridad de
                                 # evidencia ④, cfg/audio/capturas,
                                 # P1/P2, byte-identidad del código creativo (59)
    "test_humos_infra.py",       # humos: lo declarado EXISTE en el repo (~50)
    "test_hands.py",             # HANDS V1.0 núcleo aislado: contratos,
                                 # permisos deny-by-default, workspace, sesiones,
                                 # locks, evidencia, waits, verificación,
                                 # recovery, kill switch, engine, runtime (121)
    "test_hands_operators.py",   # HANDS V1.0 operadores: desktop mock,
                                 # físico NOT_VERIFIED, flow operator, adaptador
                                 # bridge (contrato HTTP), integración futura
                                 # NOT CONNECTED, self-audit §40, clean-room (58)
    "test_hands_chaos.py",       # HANDS V1.0 chaos: timeouts, UI cambia,
                                 # permisos, BLOCKED, recovery agotado,
                                 # UNKNOWN honesto, kill switch, fichero lento,
                                 # descarga fallida, locks muertos (33)
    "test_live_boot.py",         # BOOT VIVO: uvicorn real + ciclo completo del
                                 # Flow Bridge por HTTP (boot + cycle smoke)
    "test_execution_contract.py",  # [execution-contract v1] spec schema 1.0
                                 # (sin invención: null/unknown), gate de
                                 # configuración CONFIG_* (§6), validación
                                 # contractual ffprobe (§13), máquina de
                                 # estados §9, ffprobe REAL de MP4s (69)
    "test_execution_transport.py", # [execution-contract v1] transporte §17-A:
                                 # Production JSON duration 8 → adapter 8 →
                                 # export 8 → job 8 → execution_spec 8 →
                                 # claim JSON; migración real de DB (54)
    "test_flow_contract_states.py",  # [execution-contract v1] estados §9 +
                                 # §17 C/D/E: progreso (sin rebobinar),
                                 # complete 8s CONTRACT_OK vs 5s
                                 # ASSET_INVALID terminal, CONFIG_* terminal
                                 # sin adaptación, PROVIDER_FAILURE intacto,
                                 # P1 inmutable (63)
    "test_hands_contract.py",    # HANDS ↔ Execution Contract: descubrimiento
                                 # honesto, control 5s→8s verificado, gate
                                 # CONFIG_* REFUSA generar (sin submit),
                                 # evidencia refs job_id, sin coordenadas,
                                 # ExecutionContractHandAdapter (55)
    "test_flow_config_gate.py",  # Extensión 2.4.0: flowConfigFn DOM-only
                                 # (semántico/a11y/texto, sin coordenadas),
                                 # gate espejo del backend (cross-check 7/7),
                                 # prefijos CONFIG_* exactos (68)
    # ── PHASE 1 · SECURITY HARDENING — runtime HTTP (httpx ASGI), Windows-safe:
    # sin Node/bash; reproducen los exploits de la auditoría contra la app real ──
    "security/test_project_path_security.py",  # C1/M5: exploit real %2e%2e del
                                 # canario + superficie completa de pid (36)
    "security/test_project_isolation.py",      # M3/M6/M9: IDOR padre/hijo, meta
                                 # system-owned, chat destructivo exacto (26)
    "security/test_csrf.py",     # M2: origen externo → 403; local/ext/sin-Origin ok (10)
    "security/test_docs_auth.py",  # M1: /docs /redoc /openapi.json con y sin clave (12)
    "security/test_ssrf.py",     # A1/A8: matriz SSRF completa + redirects
                                 # revalidados + sonda HTTP real loopback (~25)
    "security/test_job_identity.py",  # M7/M8/A6: worker+token+lease, binding
                                 # de ejecución, recuperación idempotente (~21)
    "security/test_input_limits.py",  # A7/A9/M10/M4/M11: zip bombs, techo de
                                 # unidades, JSON anidado, PIL, ledger (17)
    "security/test_config_security.py",  # A2/M6: .env newline injection +
                                 # system-owned metadata (16)
    "test_harness.py",           # YOUTUBE HARNESS CONTRACT V1: contrato
                                 # estricto, permisos, libro idempotente,
                                 # estados §9, puente legacy del chat
                                 # (INT-028), auth/CSRF heredados (~55)
    "test_int028_general_agent.py",  # INT-028: absorción del agente —
                                 # agent.py RETIRADO, services/general_agent.py
                                 # es el cerebro único (API pública idéntica:
                                 # plan/execute/M9), sin marca VÓRTICE activa,
                                 # puente AGENT_ACTION_TO_OPERATION consistente
                                 # con VALID_ACTIONS, /api/chat intacto (~50)
    "test_flow_batchexecute.py", # FLOW START FRAME F1 (ext 2.6.0): observación
                                 # PASIVA de batchexecute (WuwhI/eb1hJf/
                                 # jwpduf/as29s), Start Frame como huella fp,
                                 # pasividad init/stream, secretos jamás,
                                 # canales tRPC intactos, alcance git (64)
    "test_flow_startframe_fase2.py", # FLOW START FRAME F2 (ext 2.6.0): parser
                                 # ANIDADO — MEDIA_GENERATION_SETTINGS con VAL
                                 # como JSON string (JSON.parse 2º nivel),
                                 # aspectRatio numérico, startFrame plano
                                 # {mediaIdPresent, fingerprint}, ids por
                                 # huella, cropCoordinates, startImage hist.,
                                 # VAL malformado diagnóstico, T1..T10 (67)
    "test_registro_baterias.py", # [D6/D4/D7] GUARDIÁN del registro canónico:
                                 # cada tests/**/test_*.py ∈ BATERIAS ∪
                                 # EXCLUDED_BATTERIES (motivo escrito) +
                                 # aceptación D4 (timeout mata árbol) +
                                 # mecanismo D7 (red externa bloqueada,
                                 # loopback permitido)
]

# ── [D6] Registro canónico de baterías EXCLUIDAS de run_all ─────────────────
# Cada tests/**/test_*.py del árbol DEBE estar aquí (con motivo escrito) o en
# BATERIAS. El guardián (test_registro_baterias.py) hace cumplir esta regla.
EXCLUDED_BATTERIES: dict[str, str] = {
    "test_d4_timeout_sleep.py":
        "batería de ACEPTACIÓN D4 (timeout): duerme 400 s; SOLO se ejecuta "
        "vía `python tests/run_all.py --timeout-seg 5 -b tests/test_d4_timeout_sleep.py`",
    "test_brand_profiles.py":
        "pytest nativa (9 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_flow_mcp_bridge.py":
        "pytest nativa (21 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_flow_mcp_video.py":
        "pytest nativa (10 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_flow_startframe_eb1hjf.py":
        "batería de RELEASE de la extensión 2.6.0: sus guardias J2/J3 exigen árbol git LIMPIO (fallarían en desarrollo con cambios pendientes); su contenido (parser eb1hJf) está cubierto por test_flow_batchexecute.py y las regresiones F1/F2 por test_flow_startframe_fase2.py, ambas en BATERIAS. Vía manual: python tests/test_flow_startframe_eb1hjf.py",
    "test_int036_profile_heal_and_strict_auth.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int043_one_click_google_connect.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int044_viral_clipper.py":
        "pytest nativa (5 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int045_karaoke_subtitles.py":
        "pytest nativa (6 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int046_broll_overlay.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int047_pacing_controller.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int048_splitscreen.py":
        "pytest nativa (2 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int049_auto_emojis.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int050_sfx_transitions.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int051_progress_bar.py":
        "pytest nativa (2 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int052_speaker_switch.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int053_face_tracking.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int054_ugc_ads.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int055_ecommerce_overlays.py":
        "pytest nativa (7 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int057_virality_score.py":
        "pytest nativa (2 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int058_avatar_pip.py":
        "pytest nativa (5 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int061_ugc_hooks.py":
        "pytest nativa (5 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int062_callout_badges.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int064_invideo_dress.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int066_avatar_motion.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int068_multilang_dubber.py":
        "pytest nativa (4 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int069_nlm_studio.py":
        "pytest nativa (18 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int070_estudio_video_ia.py":
        "pytest nativa (16 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int071_chrome_window.py":
        "pytest nativa (22 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int071_google_hub.py":
        "pytest nativa (18 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int072_hf_lipsync.py":
        "pytest nativa (15 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int075_v2v_lipsync.py":
        "pytest nativa (14 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int077_ugc_pacing.py":
        "pytest nativa (11 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int078_ugc_typed_scenes.py":
        "pytest nativa (8 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int079_wizard_brand_bar.py":
        "pytest nativa (7 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int080_audit_fixes.py":
        "pytest nativa (16 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int081_sso_visible_window.py":
        "pytest nativa (15 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int082_mejoras_revista_vivo.py":
        "pytest nativa (15 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int083_preflight_lipsync.py":
        "pytest nativa (14 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int084_aliases_api.py":
        "pytest nativa (14 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int085_broadcast_quality.py":
        "pytest nativa (16 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int086_project_templates_and_workspace.py":
        "pytest nativa (15 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int087_template_selector_ui.py":
        "pytest nativa (7 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int088_app_modular_split.py":
        "pytest nativa (6 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int089_hf_telemetry.py":
        "pytest nativa (8 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int090_universos_y_workspace_ui.py":
        "pytest nativa (11 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int091_custom_folder_picker.py":
        "pytest nativa (10 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int092_ui_cleanup.py":
        "pytest nativa (10 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_int093_theme_coherence.py":
        "pytest nativa (7 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_live_execution.py":
        "script LIVE de la máquina del dueño (REPO_ROOT=D:/PROYECTOS hardcodeado; fija FLOW_MCP_ENABLED al importarse). Vía correcta: python tests/test_live_execution.py",
    "test_live_execution_2.py":
        "ídem live_execution (env + config a nivel de módulo). Vía: python tests/test_live_execution_2.py",
    "test_live_execution_c1.py":
        "ídem live_execution (INT-080; FLOW_MCP_ENABLED=True al importar). Vía: python tests/test_live_execution_c1.py",
    "test_live_execution_c2.py":
        "ídem live_execution (env + config a nivel de módulo). Vía: python tests/test_live_execution_c2.py",
    "test_project_video_inline.py":
        "pytest nativa (5 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_scene_asset_resolver.py":
        "pytest nativa (22 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_scene_surgical_regen.py":
        "pytest nativa (2 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_subtitle_presets.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_viral_hooks_generator.py":
        "pytest nativa (6 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
    "test_voice_gallery.py":
        "pytest nativa (3 tests): se ejecuta via `pytest tests/`; no es bateria standalone de run_all",
}

# ── [FIX-A] Baterías que pytest DEBE ignorar (veneno de colección) ──────────
# Única fuente de verdad compartida con tests/conftest.py (collect_ignore):
# scripts autoejecutables con sys.exit a nivel de módulo o que envenenan el
# proceso de colección. (La lista histórica vive aquí desde el cierre D6.)
PYTEST_IGNORADAS: tuple[str, ...] = (
    "security/test_config_security.py",
    "security/test_csrf.py",
    "security/test_docs_auth.py",
    "security/test_input_limits.py",
    "security/test_job_identity.py",
    "security/test_project_isolation.py",
    "security/test_project_path_security.py",
    "security/test_ssrf.py",
    "test_burn_subtitles_resilience.py",
    "test_gobernanza.py",
    "test_hands.py",
    "test_hands_chaos.py",
    "test_hands_contract.py",
    "test_hands_operators.py",
    "test_security_hardening.py",
    "test_typography.py",
    "test_int028_general_agent.py",
    "test_live_boot.py",
    "test_10_escenas.py",
    "test_live_execution.py",
    "test_live_execution_2.py",
    "test_live_execution_c1.py",
    "test_live_execution_c2.py",
)

_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")


# ── [D5] UTF-8 honesto en consolas cp1252 (aplicado también a cada batería) ──
def _reconfigure_utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _matar_arbol(proc: subprocess.Popen) -> None:
    """[D4] Mata el ÁRBOL completo de procesos de una batería colgada:
    Windows → taskkill /T /F; POSIX → killpg SIGKILL (la batería se lanza
    con start_new_session=True para tener su PROPIO grupo de procesos)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        pass


def _slug(nombre: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre)


def _env_hijo(data_dir: Path, hermetica: bool) -> dict:
    """[D1/D7] Entorno de corrida aislado para cada hijo:
    · rutas de config por variable de entorno (config.py las lee con default
      histórico → cero ruptura fuera de la suite);
    · encoding UTF-8 estable para hijos y nietos;
    · si hermetica: sitecustomize de guardia de red primero en PYTHONPATH."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("output", "tmp", "projects", "music", "temp_renders"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DATA_DIR"] = str(data_dir)
    env["DB_PATH"] = str(data_dir / "yt_automation.db")
    env["OUTPUT_DIR"] = str(data_dir / "output")
    env["TMP_DIR"] = str(data_dir / "tmp")
    env["PROJECTS_DIR"] = str(data_dir / "projects")
    env["MUSIC_DIR"] = str(data_dir / "music")
    env["TEMP_DIR"] = str(data_dir / "temp_renders")
    if hermetica:
        previa = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(GUARDIA_RED_DIR) \
            + (os.pathsep + previa if previa else "")
    return env


def _ejecutar(nombre: str, ruta: Path, env: dict, timeout_seg: int) -> dict:
    """Ejecuta UNA batería con timeout y kill de árbol. Devuelve un dict
    con el resultado clasificado (ok/fail/skip/timeout/crash)."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, str(ruta)], cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=env, stdin=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"))
    interrumpida = False
    try:
        out, err = proc.communicate(timeout=timeout_seg)
    except subprocess.TimeoutExpired:
        interrumpida = True
        _matar_arbol(proc)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = "", ""
    dur = time.perf_counter() - t0
    res = {"nombre": nombre, "ok": 0, "fail": 0, "skip": False,
           "timeout": interrumpida, "crash": False, "detalle": "",
           "duracion": dur, "exit": proc.returncode if proc.returncode is not None else -9}
    if interrumpida:
        res["fail"] = 1
        res["detalle"] = f"TIMEOUT (> {timeout_seg}s): árbol de procesos eliminado"
        return res
    texto = out or ""
    coincidencias = _RESUMEN.findall(texto)
    if coincidencias:
        ok, fail = (int(n) for n in coincidencias[-1])
        detalle = f"{ok} OK · {fail} fallos"
        if ok == 0 and fail == 0:
            res["skip"] = True              # [D8] 0 checks NO es verde
            detalle += "  ⚠ SKIP (0 checks)"
        res["ok"], res["fail"] = ok, fail
    else:
        res["crash"] = True
        res["fail"] = 1
        detalle = "SIN RESUMEN (¿crash?)"
    res["detalle"] = detalle
    return res


def _seleccionar(args) -> list[Path]:
    """Resuelve la selección de baterías (posicionales de BATERIAS + rutas
    explícitas -b). Devuelve rutas absolutas."""
    rutas: list[Path] = []
    if args.listar:
        print(f"BATERIAS ({len(BATERIAS)}):")
        for b in BATERIAS:
            print(f"  {b}")
        print(f"EXCLUDED_BATTERIES ({len(EXCLUDED_BATTERIES)}): con motivo escrito")
        sys.exit(0)
    for arg in args.baterias:
        cand = arg if arg.endswith(".py") else arg + ".py"
        if cand not in BATERIAS:
            print(f"[run_all] '{arg}' no está en BATERIAS. Usa --listar.", file=sys.stderr)
            sys.exit(2)
        rutas.append(TESTS_DIR / cand)
    for extra in args.bateria_ruta:
        rutas.append(Path(extra).resolve())
    if not rutas:
        rutas = [TESTS_DIR / b for b in BATERIAS]
    return rutas


def main(argv=None) -> int:
    _reconfigure_utf8()
    ap = argparse.ArgumentParser(
        description="Runner canónico de baterías (D1 aislado del dueño, "
                    "D3 workers opt-in, D4 timeout, D7 hermética, D8 skip visible)")
    ap.add_argument("baterias", nargs="*",
                    help="nombres de BATERIAS (con o sin .py); vacío = todas")
    ap.add_argument("-b", "--bateria-ruta", action="append", default=[],
                    help="ruta explícita de una batería fuera del registro "
                         "(p.ej. aceptación D4)")
    ap.add_argument("-w", "--workers", type=int, default=1,
                    help="paralelización OPT-IN (default 1 = serie; con N>1 "
                         "cada batería recibe su propio directorio de datos)")
    ap.add_argument("-t", "--timeout-seg", type=int, default=None,
                    help="timeout por batería (default env "
                         "RUN_ALL_BATTERY_TIMEOUT_S o 300 s)")
    ap.add_argument("--hermetica", action="store_true",
                    help="bloquea la red externa de los hijos vía "
                         "sitecustomize (loopback permitido)")
    ap.add_argument("--serial", action="store_true",
                    help="alias histórico: la ejecución YA es serie por defecto")
    ap.add_argument("--conservar-tmp", action="store_true",
                    help="no borra el directorio temporal de corrida")
    ap.add_argument("--listar", action="store_true",
                    help="lista BATERIAS y sale")
    args = ap.parse_args(argv)

    timeout_seg = args.timeout_seg if args.timeout_seg is not None \
        else int(os.getenv("RUN_ALL_BATTERY_TIMEOUT_S", "300") or "300")
    workers = max(1, args.workers)
    rutas = _seleccionar(args)
    rundir = Path(tempfile.mkdtemp(prefix="runall_d1_"))
    modo = f"serie" if workers == 1 else f"paralelo ({workers} workers)"
    print(f"[run_all] {len(rutas)} baterías · {modo} · timeout {timeout_seg}s "
          f"· hermetica={args.hermetica} · datos aislados: {rundir}")

    resultados: list[dict] = []

    if workers == 1:
        # [D1] serie: UNA SQLite temporal compartida por toda la corrida
        # (semántica secuencial histórica, aislada del dueño)
        env = _env_hijo(rundir / "data", args.hermetica)
        for i, ruta in enumerate(rutas, 1):
            nombre = ruta.relative_to(TESTS_DIR).as_posix() \
                if ruta.is_relative_to(TESTS_DIR) else ruta.name
            print(f"\n──────── [{i}/{len(rutas)}] {nombre} ────────", flush=True)
            res = _ejecutar(nombre, ruta, env, timeout_seg)
            resultados.append(res)
            verde = (not res["fail"]) and (not res["skip"])
            print(f"  → {nombre}: {res['detalle']} · exit {res['exit']} "
                  f"· {res['duracion']:.1f}s"
                  + ("" if verde else "  ✗ FALLA"), flush=True)
    else:
        # [D3] paralelo OPT-IN: cada batería con SU PROPIO data dir
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for ruta in rutas:
                nombre = ruta.relative_to(TESTS_DIR).as_posix() \
                    if ruta.is_relative_to(TESTS_DIR) else ruta.name
                env = _env_hijo(rundir / "data" / _slug(nombre), args.hermetica)
                futures[pool.submit(_ejecutar, nombre, ruta, env, timeout_seg)] = nombre
            for fut in as_completed(futures):
                res = fut.result()
                resultados.append(res)
                verde = (not res["fail"]) and (not res["skip"])
                print(f"\n──────── {res['nombre']} ────────\n"
                      f"  → {res['nombre']}: {res['detalle']} · exit {res['exit']} "
                      f"· {res['duracion']:.1f}s"
                      + ("" if verde else "  ✗ FALLA"), flush=True)

    total_ok = sum(r["ok"] for r in resultados)
    total_fail = sum(max(r["fail"], 0) for r in resultados)
    total_skip = sum(1 for r in resultados if r["skip"])
    fallidas = [r["nombre"] for r in resultados if r["fail"]]
    skips = [r["nombre"] for r in resultados if r["skip"]]

    print(f"\n═══ TOTAL: {total_ok} OK · {total_fail} fallos"
          f" · {total_skip} SKIP en {len(resultados)} baterías ═══")
    if skips:
        print("SKIP (0 checks — NO es verde): " + ", ".join(skips))
    if fallidas:
        print("Baterías en rojo: " + ", ".join(fallidas))
    if args.conservar_tmp:
        print(f"[run_all] datos de la corrida conservados en: {rundir}")
    else:
        shutil.rmtree(rundir, ignore_errors=True)
    # convención del repo: exit 0 = todo verde; exit != 0 = hay baterías en rojo
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
