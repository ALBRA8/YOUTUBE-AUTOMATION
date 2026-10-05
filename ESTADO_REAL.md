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
Además, el fixture `GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json`
nunca se subió al repositorio.

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
| Suite canónica | ✅ 7 baterías en `tests/run_all.py` | runner |

## 3. Lo que AÚN NO está demostrado (límites honestos)

- **E2E con Google Flow REAL**: no se ha demostrado una ejecución de punta a
  punta generando assets en labs.google con la extensión. El backend y el
  contrato están probados en hermético; el lado navegador (inyección en el
  Slate de Labs, descarga de blobs, subida del binario) requiere una corrida
  manual con Chrome + sesión de Google. **No se declara éxito E2E.**
- **Auto-render real**: probado con mock de `start_flow_render`; el render
  real requiere ffmpeg + voz y se prueba con las baterías de merge.
- **Calidad de MP4 final** y **multi-proyecto en paralelo**: sin evaluar.
- El fixture oficial `GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json`
  sigue sin existir en el repo; el contrato P1 se prueba con un payload
  canónico equivalente (`test_flow_contract_p1.py`). Si aparece el fixture
  oficial, se añade como caso de test sin cambiar el contrato.

## 4. Mantenimiento de este documento

1. Cada hito nuevo actualiza la tabla de la sección 2 con su batería.
2. Prohibido marcar ✅ sin test que lo respalde en este repo.
3. Los límites de la sección 3 solo se mueven a la sección 2 con evidencia.
