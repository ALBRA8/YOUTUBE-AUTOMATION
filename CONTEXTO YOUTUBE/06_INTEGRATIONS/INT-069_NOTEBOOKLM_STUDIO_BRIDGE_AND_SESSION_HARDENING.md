# INT-069 · NotebookLM Studio Bridge + Session Hardening + Pin de versión

**Fecha:** 2026-10-27
**Estado:** IMPLEMENTADO (PoC) · tests 16/16 · suite pytest 190/190
**Origen:** evaluación del upstream `teng-lin/notebooklm-py` (v0.8.5, MIT) —
el mismo paquete que ALBRA ya usa como servidor `notebooklm-mcp`
(`uv tool install "notebooklm-py[browser]"`, INT-022). La evaluación concluyó
que el valor no explotado estaba en: Studio generation (Audio Overviews),
session hardening (auth refresh) y el riesgo de versiones sin pinear.

## 1. Pin de versión (robustez)

- `tools/mcp-setup/login-notebooklm.bat`: el install recomendado ahora es
  `uv tool install "notebooklm-py[browser]==0.8.5"`.
- `backend/config.py`: comentario canónico junto a `NOTEBOOKLM_MCP_CMD`.
- **Por qué:** el upstream renombró tools (`list_notebooks` → `notebook_list`)
  y parámetros (`notebook_id` → `notebook`) entre versiones; una
  actualización silenciosa rompería el preflight del pipeline. El HOTFIX
  INT-023.4 (`mcp_manager._LIST_NOTEBOOK_TOOLS`) ya acepta ambos nombres de
  listado; el pin evita la próxima sorpresa.

## 2. Session hardening — `auth refresh` automático

- **`mcp_manager.auth_refresh_notebooklm(timeout=90.0) -> (bool, str)`**:
  ejecuta `notebooklm auth refresh --quiet` (subprocess con timeout, captura
  de salida, NUNCA lanza).
- **Integración:** cuando la sonda del servicio `notebooklm` del preflight
  falla con patrón de autenticación, se intenta UN refresh + UN reintento de
  la sonda.
- **Gate:** env `NLM_AUTH_REFRESH` (default `"1"`; `"0"` desactiva).
  **Fail-open:** si el refresh falla, el comportamiento es exactamente el de
  siempre (badge AUTH_REQUIRED, sin cambios de flujo).

## 3. Studio Bridge — PoC Audio Overview (producto)

**`backend/services/nlm_studio.py`** — flujo completo vía `mcp_manager`
(sin browser, sin CDP):

1. `ensure_notebook` — usa `notebook_id` dado o crea "ALBRA Studio <fecha>"
   (`notebook_create`).
2. `add_text_source` — el guion/texto como fuente (`source_add`,
   `source_type="text"`, wait=True).
3. `generate_audio_overview` — `studio_generate(notebook, artifact_type="audio")`
   → devuelve `task_id` (no bloquea).
4. `poll_status` — `studio_status` cada 10 s hasta `media_ready` o deadline
   (`NLM_STUDIO_POLL_TIMEOUT`, default 900 s) → `GENERATION_FAILED` /
   `GENERATION_TIMEOUT` fail-closed.
5. `download_audio` — `studio_download` a
   `DATA_DIR/exports/nlm_studio/<notebook_id>/albra_studio_<ts>_<rand>.m4a`.

**Endpoints (`backend/main.py`):**

| Endpoint | Comportamiento |
|---|---|
| `POST /api/nlm/studio/audio-overview` | body `text` requerido, `notebook_id`/`title` opcionales → 202 con job `generating` (poll+download en tarea de fondo). 400 sin text · 404 disabled · 409 `GENERATION_IN_PROGRESS` · 502 `[CODE] MCP…` |
| `GET /api/nlm/studio/status/{notebook_id}` | `idle \| generating \| ready \| error` |
| `GET /api/nlm/studio/download/{notebook_id}` | `FileResponse` del último audio (`.m4a` → `audio/mp4`; `.mp3` → `audio/mpeg`); 404 `INVALID_NOTEBOOK_ID` / `NO_AUDIO` |

**Env vars (`backend/config.py`, documentadas en `.env.example`):**
`NLM_STUDIO_ENABLED` (default `"1"`, `"0"` = endpoints 404),
`NLM_STUDIO_EXPORT_DIR` (default vacío = `DATA_DIR/exports/nlm_studio`),
`NLM_STUDIO_POLL_TIMEOUT` (default `900`).

## 4. Hallazgos del upstream que moldearon el diseño (v0.8.5)

- El parámetro se llama **`notebook`** (no `notebook_id`) y FastMCP rechaza
  kwargs desconocidos → `mcp_manager._mirror_notebook_arg()` renombra la
  clave legacy SOLO si el inputSchema real de la tool lo pide (servidores
  legacy intactos) + `_NO_NOTEBOOK_TOOLS = {notebook_create}`.
- El Audio Overview de v0.8.5 es **AAC/MP4 (.m4a), NO MP3** (upstream #2034)
  → el bridge exporta `.m4a`.
- `NOTEBOOKLM_CONTEXT_TOOL=query_notebook` ya no existe en v0.8.5 (pendiente
  de revisión fuera de alcance de este INT).

## 5. Herramientas MCP usadas (evidencia en el clon upstream v0.8.5)

| Tool | Uso | Evidencia upstream |
|---|---|---|
| `notebook_create(notebook→title)` | crear notebook | `src/notebooklm/mcp/tools/notebooks.py:62` |
| `source_add(notebook, source_type="text", …)` | fuente del guion | `src/notebooklm/mcp/tools/sources.py:617` |
| `studio_generate(notebook, artifact_type="audio")` | disparar generación | `src/notebooklm/mcp/tools/studio.py:223` |
| `studio_status(notebook, task_id)` | poll | `src/notebooklm/mcp/tools/studio.py:407` |
| `studio_download(notebook, artifact_type="audio", path=…)` | bajar audio | `src/notebooklm/mcp/tools/studio.py:422` |
| CLI `notebooklm auth refresh --quiet` | session hardening | `docs/cli-reference.md:76-77, 937-950` |

## 6. Verificación

- `py_compile` de `main.py`, `config.py`, `mcp_manager.py`, `nlm_studio.py` OK.
- `pytest tests/test_int069_nlm_studio.py -q` → **16 passed** (mocks de
  `mcp_manager.execute`, cero red real, cero subprocess real, tmp_path para
  exports).
- Regresión de vecinos: `test_mcp_manager.py` 38 OK · `test_int023b_notebook_id.py`
  46 OK · `pytest tests/` completa 190/190.
- `.bat`: diff de 1 línea (pin añadido), ASCII+CRLF del fichero preservados.

## 7. Límites y siguiente paso

- Los jobs de Studio viven en memoria (`_JOBS`/`_TASKS`): un reinicio del
  backend pierde el poll de fondo (el audio quedaría generado en NotebookLM;
  re-lanzar el download con el `notebook_id` lo recupera).
- Autenticación real end-to-end (cookies frescas del usuario) pendiente de
  validación en Antigravity (máquina del usuario), como el resto de la ola
  INT-044..068.
- Siguientes candidatos: Video Overview / slide decks (mismo patrón con
  `artifact_type` distinto), ingesta bulk de fuentes de research
  (`add_urls_batch`), y `studio_list` para explorar artifacts existentes.
