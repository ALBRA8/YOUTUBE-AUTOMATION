# ESTADO REAL del sistema — inventario honesto

> **Regla de oro (lección del incidente de 2026-10):** nada se declara
> "terminado" sin una batería de tests que lo respalde en este repo.
> Si no está aquí, no existe. Este documento se actualiza con cada hito.

---

## 1. Incidente registrado

Se llegó a reportar como **terminado** un "FLOW BRIDGE REAL" con: cola SQLite
`flow_jobs` (claim atómico, leases, heartbeat, reintentos), 6 endpoints
`/api/extension/flow/jobs*` (v2.16.2), `extension/bridge.js` y auto-render.
**Nada de eso existía en el repo** (sin commit, sin rama, sin stash).

Consecuencia: batería de humos `tests/test_humos_infra.py` — verifica que
todo lo que declaramos **existe físicamente en el código**, y este documento
mantiene el inventario público.

## 2. Lo que EXISTE hoy (verificado con código + tests)

| Componente | Estado | Verificación |
|---|---|---|
| Adapter Production JSON (parse → validate → ingest) | ✅ real | `test_production_json.py` (76 checks) |
| **P1 Golden Contract**: `video_prompt` del Creative Engine llega **verbatim** al payload de Flow (transformacion/generic + artesano); gana sobre `ai_stages` y sobre plantillas; `duration_target` llega al export | ✅ real | `test_flow_contract_p1.py` (44 checks) |
| Campos del contrato preservados: `image_prompt`, `duration_target`, `initial_state`, `action`, `change`, `final_state`, `audio`, `references`, `casting`, `story_function`, `niche_extra` | ✅ real | `test_flow_contract_p1.py` |
| **Flow Bridge backend**: tabla `flow_jobs` (SCHEMA en `database.py`), claim atómico `BEGIN IMMEDIATE` + `job_token` nonce, lease imagen 8 min / video 15 min, heartbeat, reintentos imagen 3 / video 2 → `dead`, recuperación perezosa de leases expirados, re-enqueue idempotente | ✅ real | `services/flow_jobs.py` + `test_flow_bridge.py` (48 checks) |
| **6 endpoints** `/api/extension/flow/jobs*` (enqueue · next · heartbeat · complete · fail · status) + CORS para la extensión | ✅ real | `main.py` + `test_flow_bridge.py` vía httpx ASGI |
| Validación de assets: PNG/JPEG/WEBP con PIL · MP4 con ffprobe (>0.3s) | ✅ real | `test_flow_bridge.py` |
| Convención de assets: `data/output/<pid>/flow/Escena_NN_flow.png` + `Escena_NN_video_<part>.mp4` | ✅ real | igual que `flow_import.py` |
| Mapeo final escenas (`image_path`) + **auto-render** `orchestrator.start_flow_render` al completar el proyecto | ✅ real | `test_flow_bridge.py` (mock del render) |
| **Extensión**: `extension/bridge.js` (poll → claim → heartbeat → complete/fail), wiring `[bridge v1]` en `background.js`, botón "Puente Backend" en popup, README | ✅ existe · sintaxis verificada (`node --check`) | `test_humos_infra.py` |
| **FIXTURE GOLDEN OFICIAL** `tests/fixtures/GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json` (datos sintéticos con sentinels, NO prompts creativos reales): ejecutable de punta a punta — fixture → ingest REAL con DB → roundtrip meta JSON → script.json (P1 verbatim) → cola → claim → complete → QA | ✅ real | `test_golden_fixture.py` (30 checks) |
| **Video QA** (`services/video_qa.py` + `GET /api/video_qa/{pid}` + tool MCP): QA con ffprobe/PIL por escena (imagen mapeada o cruda en `flow/`, clips con duración/resolución/fps/códec/audio) + render final con reglas duras; **forense de medios**: muestrea frames (25/50/75%) para detectar pantalla negra/azul y mide `max_volume` para detectar audio completamente silencioso (warns, no bloquean); reporta flags error/warn/ok sin reventar | ✅ real | `test_golden_fixture.py` §7 + `test_qa_forensics.py` (30 checks con assets enfermos fabricados) |
| **Métricas/observabilidad** (`services/metrics.py` + `GET /api/metrics` + tool MCP `metricas`): proyectos/jobs/cola Flow por estado, dead por tipo, escenas sin imagen, disco de `data/output` | ✅ real | imports + registro verificado; snapshot puro de agregados |
| **Tools MCP de operación**: `flow_encolar` · `flow_estado` · `video_qa` · `metricas` (server 20 tools) | ✅ real | dispatch verificado por import + suite MCP |
| **Concurrencia**: 8 workers en raza sobre BEGIN IMMEDIATE (cero dobles claims, tokens únicos), aislamiento multi-proyecto con filtro pid, token de una sola era (409 tras re-claim), completes paralelos, enqueue en caliente | ✅ real | `test_concurrencia.py` (18 checks) |
| **Chaos**: reinicio REAL de proceso (subprocess reabre la SQLite y reclama), rollback atómico a mitad de escritura, doble complete → 409 sin sobreescribir asset, HTML de Flow → 422 → dead por intentos, dead → re-enqueue limpio, heartbeat/complete sobre estados imposibles, carrera zombie | ✅ real | `test_chaos.py` (28 checks) |
| **Escala (TEST 4 de la misión)**: proyecto de 10 escenas → 19 jobs (última escena solo-imagen por P1), contrato P1 verbatim por job + prompt de ~11KB intacto, orden de claims imágenes→videos, heartbeat/fail-retry/zombie/doble complete a escala, 10/10 escenas mapeadas, auto-render una vez, QA a escala, re-enqueue idempotente | ✅ real | `test_10_escenas.py` (44 checks) |
| **E2E extensión**: `bridge.js` REAL en sandbox VM (stubs Chrome MV3) contra backend mock HTTP con estado — claim→complete con bytes PNG validados, fail, 422→fail con detail, heartbeat true/409 false, cola vacía, backend caído no tumba el bucle, canal popup, anti-duplicado | ✅ real (capa contrato, sin Google Flow real) | `tests/e2e_bridge_mock.js` + `test_bridge_e2e.py` (24 checks Python + 26 en el harness) |
| **Boot vivo + ciclo completo por HTTP real**: uvicorn arrancado de verdad en sandbox aislado — startup, CORS preflight de la extensión, endpoints base, métricas, video QA; y ciclo Flow Bridge de punta a punta por HTTP: enqueue (build_script_json) → claim ordenado → complete con PNG/MP4 reales (PIL/ffprobe) → 409 doble complete → 422 HTML → fail/retry (attempts) → guard de tipo → project_done → **auto-render disparado** → status final → QA "ok" | ✅ real (capa HTTP; render de fondo sin claves TTS en sandbox) | `tests/live_boot_smoke.sh` + `tests/live_cycle_smoke.sh` vía `test_live_boot.py` (33 checks) |
| Suite canónica | ✅ 14 baterías en `tests/run_all.py` (548 checks) | runner |

## 3. Lo que AÚN NO está demostrado (límites honestos)

- **E2E con Google Flow REAL**: no se ha demostrado una ejecución de punta a
  punta generando assets en labs.google con la extensión instalada en Chrome.
  El contrato backend↔extensión SÍ está probado en la capa navegador
  (`e2e_bridge_mock.js`), pero la inyección en el Slate de Labs, la descarga
  de blobs reales y la subida a un backend vivo requieren corrida manual con
  Chrome + sesión de Google. **No se declara éxito E2E real.**
- **Auto-render real disparado desde el bridge**: probado con mock de
  `start_flow_render`; el render completo (TTS + Ken Burns + mezcla +
  subtítulos) se prueba en las baterías de merge, pero el disparo automático
  con assets reales de Flow aún no se ha corrido de punta a punta.
- **Calidad visual del video final**: el QA mide propiedades técnicas
  (duración, resolución, fps, audio); la calidad creativa sigue siendo
  revisión humana.
- El fixture Golden usa prompts sintéticos (sentinels CE_SENTINEL_*) por
  diseño de prueba; cuando exista un Production JSON REAL del Creative
  Engine se añade como fixture adicional sin cambiar el contrato.

## 4. Mantenimiento de este documento

1. Cada hito nuevo actualiza la tabla de la sección 2 con su batería.
2. Prohibido marcar ✅ sin test que lo respalde en este repo.
3. Los límites de la sección 3 solo se mueven a la sección 2 con evidencia.
