# INT-023 — Pipeline Orchestrator: NotebookLM → Agente → Google Flow

**Estado:** IMPLEMENTADO — batería hermética 55/55 · regresión verde (INT-022 38, INT-012 16, INT-021 59) · validación real con sesiones Google pendiente (lado del usuario).
**Mandato:** wiring de producción de las 3 etapas usando `mcp_manager` (INT-022) **sin romper** la generación de prompts/blueprints existente.

## 1. Regla de oro respetada

`services/agent.py` y `pipeline/script_gen.py` quedan **intactos** (cero diff). La generación del guion sigue siendo el motor de siempre (`script_gen.from_idea` → `build_result` con su sanitización anti Safety-Policy). El orquestador NO reescribe plantillas: **alimenta** el motor con la idea enriquecida y despacha lo que el motor produce.

## 2. Arquitectura

```
UI (vista 🔌 MCP · tarjeta 🚀 Pipeline)
  │ POST /api/pipeline/run {idea, format, notebook_id?}
  ▼
services/pipeline_orchestrator.py  (single-flight, estado atómico en disco)
  ├─ [0/3] PRE-FLIGHT (gatekeeper §2)  → mcp_manager.test_pipeline × 2
  │        ❌ AUTH_REQUIRED / Disconnected → aborta ANTES de gastar tokens
  ├─ [1/3] STAGE 1 · contexto          → mcp_manager.execute("notebooklm",
  │        NOTEBOOKLM_CONTEXT_TOOL, {query}, notebook_id dinámico §3)
  │        → data/pipeline_runs/<run_id>/context.md
  ├─ [2/3] STAGE 2 · blueprint         → script_gen.from_idea(idea + contexto)
  │        (motor existente) → blueprint.json + escenas s1..sN
  └─ [3/3] STAGE 3 · despacho Flow     → por escena:
           flow_generate_image (start-frame con @{personaje})
           → asset = stem del archivo generado
           → flow_generate_video(prompt=movimiento+narración, startFrame, aspect)
```

**Consistencia de personaje (§1.3):** el asset de referencia se sube **UNA vez** por corrida (`flow_upload_file`, nombre `FLOW_REF_ASSET_NAME` default `personaje`) desde `FLOW_REF_IMAGE_PATH` o generado como ancla con el contexto del notebook; todas las escenas citan `@{personaje}` en su start-frame.

**Recuperación (§2):** una escena que falla NO tumba la corrida → `status="failed"` + `detail` con código estable (`TOOL_ERROR`, `TIMEOUT`…), los assets previos quedan intactos, y `POST /api/pipeline/retry-scenes` re-despacha **solo** las fallidas usando el blueprint persistido (Stage 1/2 jamás se repiten; la referencia de personaje no se re-subi: está cacheada en `run.reference_asset`).

## 3. Contratos

### Estados de corrida (`state.json` atómico en `data/pipeline_runs/<run_id>/`)
`queued → preflight → stage1_context → stage2_blueprint → stage3_dispatch → done`
· `error` (códigos: `PRE_FLIGHT_AUTH`, `PRE_FLIGHT_NOTEBOOKLM`, `PRE_FLIGHT_FLOW`, `CONTEXT_EXTRACTION_FAILED`, `CONTEXT_EMPTY`, `BLUEPRINT_FAILED`, `BLUEPRINT_EMPTY`, `FLOW_NOT_CONNECTED`, `PIPELINE_CRASH`) · `done` con `error_code=PARTIAL_FAILURES` cuando hay escenas fallidas.

### Endpoints (heredan `auth_guard`/`csrf_guard`)
| Endpoint | Descripción |
|---|---|
| `POST /api/pipeline/run` | `{idea, format?, style?, notebook_id?}` → `run_id`; single-flight (409 `PIPELINE_BUSY` si ya hay corrida: Flow serializa en el Chrome dedicado) |
| `GET /api/pipeline/status?run_id=` | snapshot (última corrida si no se indica): etapas, `[3/3] (X/Y)`, chips por escena, `failed_scene_ids`, archivos generados |
| `POST /api/pipeline/retry-scenes` | `{run_id, scene_ids?}` → re-despacho quirúrgico de fallidas; errores 400: `RETRY_NO_BLUEPRINT`, `NO_FAILED_SCENES`, `RUN_NOT_FOUND` |

### Config nueva (`.env`, ver `.env.example §INT-023`)
`NOTEBOOKLM_CONTEXT_TOOL` (default `query_notebook` — si el servidor no la expone, la UI lista las tools reales), `NOTEBOOKLM_CONTEXT_QUERY`, `PIPELINE_CONTEXT_MAX_CHARS` (6000), `FLOW_REF_ASSET_NAME` (`personaje`), `FLOW_REF_IMAGE_PATH`.

## 4. UI (vista 🔌 MCP → tarjeta «🚀 Pipeline completo»)

- Botón **🚀 Run Full Pipeline (NotebookLM → Agent → Flow)**: usa la idea + formato del formulario y el notebookId activo del MCP Manager (`#nblm-nid` → localStorage → `.env`).
- Progreso en vivo por polling ligero (2 s, se auto-detiene al terminar; reanuda si recargas con una corrida activa): `[1/3] Reading NotebookLM…` → `[2/3] Generating Blueprint…` → `[3/3] Dispatching Scenes to Flow (X/Y)…` + chips por escena (✓ done · ✗ failed con tooltip del error · … despachando).
- Botón **🔁 Reintentar escenas fallidas** visible solo cuando `failed_scene_ids` no está vacío.
- Badges de etapa reutilizan las clases de los badges MCP (amarillo en marcha / verde completado / rojo error).

## 5. Batería (tests/test_pipeline_orchestrator.py — 55 checks, S1-S10b)

Mocks herméticos (cero red/Chrome/LLM): `FakeManager` imita el contrato real de `mcp_manager` (incluida la inyección §3 del notebookId); `script_gen.from_idea` se parchea como módulo para verificar el handoff SIN tocar su plantilla. Cubre: pre-flight aborta sin gastar tokens (S2/S3/S3b), happy path 3 escenas con `@{personaje}` y aspect por formato (S4), escena fallida → `PARTIAL_FAILURES` con assets intactos (S5), retry SOLO de la fallida sin delta de Stage 1/2 (S6), errores limpios (S7), Flow caído en Stage 3 → escenas reintegrables (S8), tool de contexto ausente surfaced (S9), endpoints ASGI in-process (S10).

## 6. Límites honestos

- Validación REAL con sesiones Google (NotebookLM `query_notebook` + Flow CDP) pendiente en la máquina del usuario; el nombre exacto de la tool de contexto depende del servidor `notebooklm-mcp` instalado (configurable).
- El retry requiere el mismo directorio `data/pipeline_runs/` (persistente en disco, sobrevive reinicios del backend).
- Flow genera el video de cada escena por separado (start-frame + motion); el montaje final sigue siendo trabajo del pipeline de fábrica existente (fuera del alcance del mandato INT-023).
