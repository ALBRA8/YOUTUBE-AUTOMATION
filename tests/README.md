# Tests canónicos · fuente de verdad

Baterías autoejecutables del proyecto. Sin credenciales y sin red externa
(la única excepción es `test_live_boot.py`, que levanta uvicorn en
127.0.0.1 en un sandbox aislado). Viven DENTRO del repo: cada batería
resuelve el backend relativo al propio repositorio (`tests/../backend`),
sin rutas absolutas.

## Qué cubre cada batería

| Batería | Área | Checks |
|---|---|---|
| `test_guion_json.py` | Contrato **legacy guion_json**: spec 2.11, `parse_payload` (fences), `validate` (alias EN, sanitización de image_prompt, límites duros), ingest sin LLM contra la SQLite real de desarrollo, rama del orquestador (por fuente) y dispatch MCP (25 tools). | 42 |
| `test_production_json.py` | **Adapter Production JSON 2.16.1**: spec, `parse_payload`, `validate` estructural (aliases, extras/continuity verbatim), `validate_execution` (nivel 2, unidades bloqueadas), `validate_only` (dry-run) e `ingest` con DB fake (sha256, tts_skip, preflight en meta). | 76 |
| `test_merge_216_pyav.py` | **Merge/integración 2.16.x + fix PyAV**: (A) MCP 2.16.1 auditado por AST sin imports pesados, (B) adapter real con DB fake, (C) fix PyAV por strings de fuente (requirements/tts_step/doctor/main), (D) compatibilidad cruzada Adapter↔pipeline↔MCP. | 51 |
| `test_lanzar_preflight.py` | **Preflight de lanzamiento**: flujo real `submit_production_json` → `lanzar_proyecto` vía `mcp_server._dispatch` (DB fake + `orchestrator._run` grabado). El draft con unidades sin `image_prompt` se acepta pero NO se lanza; no-regresión legacy (sin production.json), JSON corrupto/borrado. | 29 |
| `test_flow_contract_p1.py` | **GOLDEN EXECUTION CONTRACT P1**: el `video_prompt` del Creative Engine llega **verbatim** al payload de Flow (transformación/genérico y artesano), gana sobre `ai_stages` y plantillas, `duration_target` al export, campos del contrato preservados, sanitización no muta. | 44 |
| `test_flow_bridge.py` | **Flow Bridge v1**: motor de cola (`services/flow_jobs.py`) claim atómico/lease/heartbeat/complete/fail, 6 endpoints vía httpx ASGI, validación PIL/ffprobe, mapeo de escenas + auto-render (mock), re-enqueue idempotente. | 48 |
| `test_golden_fixture.py` | **Fixture Golden oficial**: cadena completa con DB REAL — fixture → ingest → roundtrip meta JSON → script.json (P1 verbatim) → cola → claim → complete → Video QA. | 30 |
| `test_qa_forensics.py` | **QA forense de medios**: fabrica assets enfermos y verifica detección REAL — pantalla negra, pantalla azul, audio completamente silencioso (volumedetect), no confusión entre tipos, propagación de warns a `qa_project` (status warn sin errores), HTML disfrazado de MP4 → error sin crash. | 30 |
| `test_production_doctor.py` | **PRODUCTION DOCTOR V1.0**: taxonomía de 8 clasificaciones, capas A-I con evidencia (JSON corrupto, unidades bloqueadas, paridad, pérdida en adapter, P1 verbatim, estados de cola), ciclo AUDIT→FIX→re-audit→VERIFY, audit trail con 10 campos, SHA-256 de lo creativo invariante, UNKNOWN honesto, CLI exit codes. | 54 |
| `test_doctor_preflight.py` | **REAL FLOW PREFLIGHT**: veredicto PASS honesto, backend caído, contrato (sin image_prompt/**criterio estricto video_prompt: unidad generadora de video sin él → bloquea, última SOLO-imagen exenta por diseño, 1 unidad = 0 clips → no aplica**/cero video_prompt/JSON corrupto/ausente/project_id incorrecto), cola sucia (dead/lease vencido/sin jobs), pipeline activo, manifest sin host_permissions, bridge desalineado, **EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME CONNECTED (sin evidencia de lease vigente → NOT_DEMONSTRATED, nunca PASS; lease vencido no es evidencia)**, nunca ejecuta Flow ni muta, **§9 guardia SSRF vs backend propio (v2.19.1): sonda real contra servidor loopback vivo — default propio → P-BACKEND-HEALTH ok (antes imposible), backend_url externa → guardia intacta; allow_private sigue bloqueando metadata/link-local/0.0.0.0/file://**. | 48 |
| `test_concurrencia.py` | **Concurrencia**: raza de 8 workers sobre BEGIN IMMEDIATE (0 dobles claims), aislamiento multi-proyecto, token de una sola era (409 tras re-claim), completes paralelos, enqueue en caliente. | 18 |
| `test_chaos.py` | **Chaos**: reinicio REAL de proceso (subprocess), rollback atómico, doble complete 409, HTML de Flow → 422 → dead, dead → re-enqueue, estados imposibles, carrera zombie. | 28 |
| `test_10_escenas.py` | **Escala (TEST 4)**: proyecto de 10 escenas → 19 jobs (última solo-imagen por P1), sentinels verbatim por job + prompt de ~11KB intacto, orden de claims imágenes→videos, heartbeat/fail-retry/zombie/doble complete a escala, 10/10 escenas mapeadas, auto-render una vez, QA a escala con forense limpia, re-enqueue idempotente. | 44 |
| `test_autopublish_generate.py` | **Pipeline `_run` completo con mocks + QA gate REAL**: pasos pesados sustituidos por dobles instantáneos, el final fabricado es un MP4 válido (naranja+tono) que cruza `_gate_qa_final` real; publicador mockeado: éxito, fallo (quota 403) con publish_state FAILED + job kind=publish, modo generate, verificación SSE. | 45 |
| `test_memorydv.py` | **MemoryDV §memoria**: 18 campos del contrato + dominio forzado, storage JSONL por tipo, query (tipo/scope/texto/limit + utility), línea corrupta tolerada, consolidación §9 (observaciones → candidato idempotente), validación (inválido / sin regresión → ValueError / con regresión real → promoción verificada), decaimiento con retiro, aislamiento del sandbox, stats. | 36 |
| `test_skills_autonomia.py` | **Skill Contract §skills**: 17 skills con los 16 campos del contrato, `validate_registry` resuelve cada target con importlib y verifica regresiones en disco, kind (TOOL/SKILL/…/SELF-IMPROVEMENT), `mark_validated` con estado rolling. **Autonomía §26**: L0-L5, mapa acción→nivel (publicar=3, doctor fix=4, self-improve=5), check/require, `assert_no_bypass` (self-improvement jamás autoriza publishing). | 34 |
| `test_security_hardening.py` | **SEGURIDAD §30**: `safe_filename` (path traversal/hidden/basename), `validar_url` (file://, loopback, privadas, link-local metadata, credenciales, no resoluble), `safe_fetch_bytes` sin IO inseguro, MASTER_API_KEY (verify constante + reload), `sanitize_external_text` anti-inyección (ignora órdenes externas, control chars, tope), wiring real (auth /mcp, publish idempotente+QA gate, chmod 0600 token, deadline upload, SSRF en plan C y `_http_probe`). | 47 |
| `test_gobernanza.py` | **GOBERNANZA v2.19**: QA gate del render con MP4 real (inválido → RuntimeError + meta.qa_final worst=error; sano pasa; subs no quemados → warn), anti zombie-loop por `lease_cycles` (vencido→queued, agotado→dead, vigente intacto), gancho MemoryDV de la cola, métricas §28 (tasas honestas + persist JSONL), MCP de gobernanza vía dispatch real, autonomía integrada, publish_state y cierre observable. | 28 |
| `test_bridge_e2e.py` | **E2E extensión**: `node --check` en los JS + `bridge.js` REAL en sandbox VM contra backend mock HTTP con estado (claim→complete con bytes validados, 422, heartbeat, backend caído, anti-duplicado) + anclajes `[bridge v1]` + migración de dominio flow.google.com (manifest, tabs.query de AMBOS dominios, origin check del popup, versión 2.2.x). | 42 |
| `test_extension_resolver.py` | **Resolver/inyector de editor (ext 2.2.2)**: la UI real de Flow (AiSandboxAngularFrontend, raíz `<aisandbox-root>`) ya no monta Slate; el resolver elige el campo de prompt por estrategias A→D (aisandbox-root / textarea con señales de prompt / contenteditable role=textbox / compat Slate legacy), con vetos duros (nav/header/search/título/feedback/oculto/no-editable), inserción por el mecanismo del control real (setter nativo + input/change; selección + beforeinput + execCommand con fallback textContent), verificación del valor tras insertar y diagnóstico estructurado (estrategias probadas + candidatos) — mini-DOM determinista, sin Flow real (la prueba REAL se hace en el PC). | 70 |
| `test_extension_tab_selector.py` | **Selector de pestaña Flow ([bridge v3], ext 2.2.3)**: fin del `tabs[0]` arbitrario (causa raíz del FAIL real con varias pestañas: la antigua perdía el contexto de scripting tras recargar la extensión → "Cannot access contents of the page"). Orden de preferencia determinista (activa de la ventana enfocada → activas de otras ventanas → vinculada viva → resto por recencia) + **VALIDACIÓN REAL**: cada candidata se sonda EJECUTANDO la función serializada contra su contexto de página falso (el manifest no basta) con re-chequeo de URL (la vinculada que navegó fuera se veta) + fallback (fallo de una candidata → siguiente) + diagnóstico estructurado `tried` — 17 escenas en mini-chrome determinista (demo exigida [antigua inválida, nueva válida] → nueva válida; caso inverso; fallback; sin coordenadas/títulos/project_id; resolver A→D e inyección intactos). | 58 |
| `test_extension_error_tile.py` | **FIX error-tile ([error-tile v2], ext 2.2.4)**: fin del falso positivo forense (proyecto 26b63daa9bdd: Flow SÍ generó 4 MP4 válidos con firma Google/C2PA pero la extensión mató la escena por un `<flow-error-tile>` de UN intento fallido). El error-tile ahora solo es FATAL sin evidencia de resultados (sin media/video visible en el snapshot, sin tiles pendientes, sin media ya atribuida a la escena); con evidencia se ignora y las redes de seguridad reales no cambian (watchdog por escena, error de políticas por tile clásico, rate limit) — 10 escenas que ejecutan el CÓDIGO REAL de `processDomSnapshot`/`resolveSemanticScene`/`markSceneError` extraído de background.js en un service worker simulado con snapshots con la forma EXACTA de `domScanFn`. | 54 |
| `test_humos_infra.py` | **Humos anti-fantasma**: todo lo que declaramos existe físicamente en el repo (tabla, endpoints, bridge.js, wiring, CORS, P1, auto-render, runner, ESTADO_REAL). | 51 |
| `test_hands.py` | **HANDS V1.0 núcleo (capa aislada, NOT CONNECTED)**: 9 estados con transiciones (UNKNOWN nunca→COMPLETED), taxonomía de 10 errores, permisos deny-by-default en 5 categorías + allowlists (comandos por prefijo, sin shell), workspace aislado con frontera fs anti-escape/symlink, sesiones auditables persistidas, locks con dueño/timeout + carrera de 8 threads + file-lock cross-proceso, evidencia hasheada con redacción de secretos, wait engine con 8 kinds y timeout obligatorio (reloj virtual), verificación PASS/FAIL/UNKNOWN + file verification con magic bytes (HTML disfrazado de mp4 rechazado), recovery acotado con backoff creciente, identificación semántico→a11y→texto→DOM→visual→coords (vetadas por política), action engine O→I→A→O→V con idempotencia y recovery, runtime con sesión+locks+cierre honesto. | 121 |
| `test_hands_operators.py` | **HANDS V1.0 operadores**: MockEnvironment completo, desktop operator (apps/input/fs/exec_allowed/captura a evidencia), caos ventana desaparece, PhysicalDesktopBackend con triple candado (consentimiento+command_map+allowlist) y MATURIDAD NOT_VERIFIED, FlowOperator ciclo completo con disciplina §15 (prompt externo, vacío rechazado), verificación de medios, idempotencia, caos HTML disfrazado/congelado/rate-limit, ExtensionBridgeDriver contra servidor HTTP simulado con el CONTRATO REAL del bridge (enqueue/status/X-API-Key/404, gate enabled=false ⇒ BLOCKED), contrato de integración futura (schemas + NotConnectedAdapter), self-audit §40 PASS completo y clean-room §42 PASS completo. | 58 |
| `test_hands_chaos.py` | **HANDS V1.0 chaos**: timeouts (wait/driver HTTP/config), UI cambia a mitad de flujo con fallback de estrategia §8 y TARGET_NOT_FOUND con diagnóstico, permisos denegados en las 5 categorías, BLOCKED honesto (lock/backend parado/bridge apagado), recovery agotado con historial, disciplina UNKNOWN (sesión UNKNOWN cierra FAILED §11), kill switch a mitad de espera con evidencia preservada, fichero que tarda con reloj virtual, descarga fallida sin inventar assets, file lock con dueño muerto, auditabilidad total tras el caos. | 33 |
| `test_live_boot.py` | **Boot vivo**: arranca uvicorn REAL en sandbox aislado (`live_boot_smoke.sh`: startup, CORS preflight, endpoints base, métricas, video QA) + **ciclo completo del Flow Bridge por HTTP** (`live_cycle_smoke.sh`: enqueue → claim → complete PNG/MP4 reales → 409/422 → fail/retry → guard de tipo → project_done → auto-render → QA). | 33 |

Total esperado: **1252 checks** en 27 baterías.

> Nota: `test_lanzar_preflight.py` verifica la barrera de preflight que vive en
> `pipeline/orchestrator.py` (`_preflight_lanzamiento`). Contra un estado sin
> ese cambio (p.ej. un clone anterior a su publicación), la sección E queda en
> rojo por diseño: la batería actúa de detector de la feature.

## Cómo ejecutarlas (clone limpio)

```bash
cd yt_automation_v2
python3 tests/run_all.py                  # las 23 baterías + total; exit != 0 si algo falla

# individual (python3 plano, estilo autoejecutable):
python3 tests/test_production_json.py
bash tests/live_boot_smoke.sh             # boot vivo aislado (opcional, sin pytest)

# opcional con pytest (cada batería = 1 test; live_boot requiere bash+ffmpeg):
python3 -m pytest tests/ -q --ignore=tests/test_live_boot.py
```

Requisitos: `python3 >= 3.10`, `bash`, `curl`, `ffmpeg/ffprobe` (para
`test_live_boot.py`, `test_qa_forensics.py` y `test_10_escenas.py`) y las
dependencias de `backend/requirements.txt`
instaladas (mínimo `fastapi`/`starlette`; las baterías NO importan `av` ni
`faster_whisper` aunque no estén instalados). La primera corrida en un clone
limpio crea el runtime mínimo (`backend/data/`, SQLite, `output/`) al importar
`config`/`database`; todo ello está en `.gitignore`.

## Qué escriben y limpian en disco

- `test_production_json.py`, `test_merge_216_pyav.py`, `test_lanzar_preflight.py`:
  escriben `backend/data/output/<pid>/production.json` (carpeta de proyecto de
  prueba) y la **eliminan al final** de la corrida.
- `test_guion_json.py`: usa la SQLite real de desarrollo
  (`backend/data/yt_automation.db`), crea proyectos de prueba y los **borra al
  final** (`delete_project`).
- `test_live_boot.py`: copia `backend/` a un sandbox temporal (fuera del repo,
  se borra al terminar), usa su PROPIA SQLite vacía y puertos locales
  (127.0.0.1:8765/8766). No toca la DB ni los outputs del desarrollador.
- Ninguna batería deja carpetas de prueba en `backend/data/output/` ni toca
  nada fuera de `backend/data/` y su sandbox temporal.

Notas de aislamiento: cada batería inyecta su propio módulo `database` fake en
`sys.modules` (excepto `test_guion_json.py`, que usa la real) y purga los
módulos de la app al empezar, por lo que también pueden correr en el
mismo proceso (caso pytest). `run_all.py` además las ejecuta en procesos
separados. `test_live_boot.py` corre subprocess `bash` y se excluye del modo
pytest por defecto.
