#!/usr/bin/env python3
"""Runner de las baterías canónicas de tests (fuente de verdad).

Ejecuta las baterías canónicas, cada una en su PROPIO proceso python3
(aislamiento total de sys.modules), imprime un resumen por batería
(X OK · Y fallos) y un total. Exit code != 0 si alguna batería falla
o no puede ejecutarse.

[P6.2] PARALELIZACIÓN: cada batería paga 11–17 s de import de backend al
arrancar (Windows); en serie eran ~65 baterías × arranque. Las herméticas
son subprocess I/O-bound y corren en un ThreadPoolExecutor (default
max_workers = cpu−1); las NON_HERMETIC_BATTERIES van en SERIE al final.
Los hijos respetan PYTHONIOENCODING/utf-8 y PYTHONDONTWRITEBYTECODE=1.
Flags:
  --serial        comportamiento clásico (todas en serie)
  --workers N     sobreescribe el nº de workers del pool
  --hermetic/--ci solo herméticas (CI)
Uso:  cd yt_automation_v2 && python3 tests/run_all.py
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

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
    "security/test_sqli.py",     # AUDITORÍA 2026-11: SQLi por nombre de
                                 # columna — lista blanca por tabla (22)
    "security/test_auditoria_repairs.py",  # REPARACIONES P0-P2 (2026-11-20):
                                 # C1 env.bak, C4 CLAIMED→DONE, C5 claim→fail
                                 # →claim, A10 UNVERIFIABLE terminal, C8
                                 # scheduler, A7 zip-bomb/411, A1 badge, A16
                                 # dialog, A6 ACL, A14 gate subs, P5.4 (44)
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
    # ── MINIDRAMAS (PASO 0.2) — tests pytest-nativos registrados como
    # baterías: su __main__ imprime el resumen "N OK · M fallos" que este
    # runner parsea (plugin de conteo). Herméticas (sin DNS ni internet).
    "test_minidrama_clip_validator.py",  # Validador editorial Fase E (43):
                                 # dialogue estructurado {personaje,texto}
                                 # como fuente de verdad, heurística rayas/
                                 # verbo de habla, aviso DIALOGO_SIN_COMILLAS,
                                 # párrafo único, MAYÚSCULAS, duración
    "test_observador_piloto.py", # Observador del piloto mínimo Gate 0/3 (12):
                                 # veredicto PASS/FAIL/NOT_DEMONSTRATED
                                 # honesto, MP4 con ffprobe local,
                                 # barrido de secretos con redacción
    # ── U-SERIES · PANEL MCP HONESTO (U1-U7) — herméticas con dobles ──
    "test_u1_mcp_resumen.py",    # U1: GET /api/mcp/resumen — agregador solo
                                 # lectura del ecosistema Google; todo_
                                 # conectado SOLO con las 4 piezas ok (14)
    "test_u_panel_ecosistema.py", # U2-U5: tarjeta única con semáforo de U1,
                                 # Conectar todo, bloque Avanzado, cuaderno
                                 # por nicho y gate del Run Full Pipeline
    "test_u6_catalogo_contrato.py", # U6/S2: contrato del paquete REAL
                                 # notebooklm-mcp-server v0.1.15 + trinquete
                                 # de tools del código vs catálogo real
    "test_w3_rutas_verificadas.py", # W3: guardia estática de rutas verificadas
                                 # por el dueño en su máquina (4)
    "test_bb_stage1_notebook_query.py", # BB1-BB2: default notebook_query, fallback
                                 # y parsing status/answer (7)
    "test_bb5_pipeline_guards.py", # BB5: aborto BLUEPRINT_DEMO, max_scenes trimming
                                 # y validación/escritura atómica de _sync_auth_json (5)
    "test_bc_contexto_local.py",  # BC: Contexto local de respaldo por nicho,
                                 # fallback de auth error y PIPELINE_CONTEXT_SOURCE=local (5)
    "test_bd_gemini_models_and_bl.py", # BD: Filtrado de cookies BASE_URL, build label
                                 # vivo y cadena de modelos Gemini con fallback ante 404 (6)
    "test_be_flow_cdp_stability.py",   # BE: Flags CDP de fondo, calentamiento de Stage 3
                                 # y reintento acotado ante connectOverCDP: Timeout (5)
    "test_bg_gemini_errors_and_external_blueprint.py", # BG1-BG2: resiliencia Gemini
                                 # (429 sin retry mismo modelo → fallbacks, 503 con
                                 # esperas 5/15 s, 404 inmediato) + mensaje honesto en
                                 # BLUEPRINT_DEMO ("Gemini falló: <motivo real>", sin
                                 # la sugerencia fija) + puerta DECLARADA de blueprint
                                 # externo (validación estricta INVALID_BLUEPRINT,
                                 # etapa 2 sin Gemini, engine "external:<label>",
                                 # blueprint_source "external") (39)
]

_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")


NON_HERMETIC_BATTERIES = {
    # test_live_boot.py arranca uvicorn real y ejecuta scripts bash (.sh)
    # contra puertos de red del sistema; requiere entorno de host.
    "test_live_boot.py",
}

def main(baterias: list[str] | None = None, argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:] if argv is None else argv
    hermetic = "--hermetic" in args or "--ci" in args
    serial = "--serial" in args
    workers = None
    if "--workers" in args:
        i = args.index("--workers")
        if i + 1 < len(args):
            workers = max(1, int(args[i + 1]))
    # [P6.2] selección por nombre: los argv que no son flags son baterías
    posiciones = [a for a in args if not a.startswith("--")
                  and not (a.isdigit() and "--workers" in args)]
    posiciones = [a for a in posiciones if (TESTS_DIR / a).exists()]
    if posiciones:
        baterias = posiciones
    if baterias is not None:
        lista = baterias
    elif hermetic:
        lista = [b for b in BATERIAS if b not in NON_HERMETIC_BATTERIES]
    else:
        lista = BATERIAS

    # [P6.2] reparto: herméticas en pool; no-herméticas SIEMPRE en serie al
    # final. --serial restaura el comportamiento clásico (todo en serie).
    if serial:
        en_paralelo, en_serie = [], lista
    else:
        en_paralelo = [b for b in lista if b not in NON_HERMETIC_BATTERIES]
        en_serie = [b for b in lista if b in NON_HERMETIC_BATTERIES]

    total_ok = 0
    total_fail = 0
    fallidas: list[str] = []
    resultados: dict[str, tuple[int, int, int, str]] = {}

    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"  # [P6.2] sin .pyc en los hijos

    def _ejecutar(nombre: str):
        proc = subprocess.run(
            [sys.executable, str(TESTS_DIR / nombre)],
            cwd=str(TESTS_DIR.parent), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=child_env,
        )
        return nombre, proc

    def _procesar(nombre: str, proc) -> None:
        nonlocal total_ok, total_fail
        coincidencias = _RESUMEN.findall(proc.stdout or "")
        if coincidencias:
            ok, fail = (int(n) for n in coincidencias[-1])
            if proc.returncode != 0 and fail == 0:
                fail = 1
            detalle = f"{ok} OK · {fail} fallos"
        else:
            ok, fail = 0, 1
            detalle = "SIN RESUMEN (¿crash?)"
        verde = proc.returncode == 0 and fail == 0
        resultados[nombre] = (ok, fail, proc.returncode, detalle)
        total_ok += ok
        total_fail += fail
        if not verde:
            fallidas.append(nombre)

    n_herm = len(en_paralelo)
    if n_herm and not serial:
        max_w = workers or max(1, (os.cpu_count() or 2) - 1)
        print(f"[P6.2] herméticas en paralelo: {n_herm} baterías × "
              f"{max_w} workers · no-herméticas en serie al final", flush=True)
        idx = {n: i for i, n in enumerate(en_paralelo)}
        completadas = 0
        with ThreadPoolExecutor(max_workers=max_w) as ex:
            futs = {ex.submit(_ejecutar, n): n for n in en_paralelo}
            for fut in as_completed(futs):
                nombre, proc = fut.result()
                _procesar(nombre, proc)
                completadas += 1
                ok, fail, rc, det = resultados[nombre]
                print(f"[{completadas}/{n_herm}] {nombre}: {det} · exit {rc}"
                      + ("" if rc == 0 and fail == 0 else "  ✗ FALLA"), flush=True)
        for n in en_paralelo:  # detalle completo en orden canónico
            ok, fail, rc, det = resultados[n]
            print(f"  · {n}: {det}")

    for i, nombre in enumerate(en_serie, 1):
        print(f"\n──────── [serie {i}/{len(en_serie)}] {nombre} ────────")
        nombre_out, proc = _ejecutar(nombre)
        _procesar(nombre_out, proc)
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        ok, fail, rc, det = resultados[nombre]
        print(f"  → {nombre}: {det} · exit {rc}"
              + ("" if rc == 0 and fail == 0 else "  ✗ FALLA"))

    print(f"\n═══ TOTAL: {total_ok} OK · {total_fail} fallos "
          f"en {len(lista)} baterías ═══")
    if fallidas:
        print("Baterías en rojo: " + ", ".join(fallidas))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
