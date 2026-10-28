# INT-069.1 — Alineación de defaults de tools NotebookLM a v0.8.5 + mirror `query`→`question`

- **Fecha:** 2026-10-28.
- **Estado:** IMPLEMENTADO / suite 192/192 / baterías vecinas verdes / validación real con sesión NotebookLM pendiente (Antigravity).
- **Origen:** cierre de la auditoría INT-069 — el pin de versión quedó hecho (`notebooklm-py[browser]==0.8.5`), pero los defaults de código seguían apuntando a nombres de tools que v0.8.5 ya no expone.

## 1. Problema

Verificado contra el tag exacto `v0.8.5` (commit `50493dd`, clone en `/home/z/my-project/external/notebooklm-py`):

| Uso en ALBRA | Nombre legacy (default anterior) | Nombre real en v0.8.5 |
|---|---|---|
| Preflight de sesión (`NOTEBOOKLM_PROBE_TOOL`) | `list_notebooks` | `notebook_list` (`mcp/tools/notebooks.py:46`) |
| Contexto Stage 1 del orquestador (`NOTEBOOKLM_CONTEXT_TOOL`) | `query_notebook` | `chat_ask` (`mcp/tools/chat.py:141`) |

El caso del probe era benigno: `_LIST_NOTEBOOK_TOOLS` ya contiene ambos nombres y el código elige el que exista. El caso del contexto **NO** era solo un renombre de tool: **`chat_ask` además renombró el parámetro** — acepta `question`, no `query` (que es lo que el orquestador INT-023 envía, heredado del contrato de la tool legacy). Con FastMCP 2.14.x estricto (rechaza kwargs desconocidos con `ValidationError`, verificado en INT-069), apuntar el default a `chat_ask` sin adaptar el argumento habría roto el Stage 1 en la primera corrida real.

## 2. Cambios (quirúrgicos)

1. `backend/config.py`: defaults `NOTEBOOKLM_PROBE_TOOL` → `notebook_list`, `NOTEBOOKLM_CONTEXT_TOOL` → `chat_ask`.
2. `backend/services/mcp_manager.py`: los 3 call sites del probe alineados; **nuevo `_mirror_query_arg()`** — mismo patrón schema-driven de INT-069 (`_mirror_notebook_arg`): si el `inputSchema` real de la tool declara `question` y NO `query`, renombra la clave. Invocado desde `execute()` junto al mirror de notebook. Servidores legacy que declaran `query` quedan intactos.
3. `backend/services/pipeline_orchestrator.py`: fallback del Stage 1 → `chat_ask` (los `args` siguen enviando `query`; el mirror lo adapta según schema).
4. `backend/.env.example`: comentarios/defaults actualizados (probe, ejemplo de allowlist con nombres v0.8.5, context tool).

La cadena de compat queda: orquestador envía contrato legacy (`query` + `notebook_id`) → `mcp_manager.execute()` espeja ambas claves según el `inputSchema` real → v0.8.5 recibe `question` + `notebook`. Si en el futuro se despinnea la versión, el mismo mecanismo absorbe el cambio sin tocar el orquestador.

## 3. Tests

- `tests/test_int069_nlm_studio.py` (18 checks): nuevo `test_mirror_query_arg_v085` (schema v0.8.5 renombra `query`→`question`; servidor legacy con `query` queda intacto) y `test_defaults_aligned_v085` (contrato de defaults en `config.py` + call sites de `mcp_manager.py` y `pipeline_orchestrator.py`, con `_LIST_NOTEBOOK_TOOLS` aún aceptando el nombre legacy).
- Suite completa: **192 passed** (`pytest tests/`, antes 190). Sin regresión: `test_mcp_manager.py` 38 OK, `test_int023b_notebook_id.py` 46 OK, `test_pipeline_orchestrator.py` 56 OK (standalone).

## 4. Límite honesto

El mirror y los defaults están verificados contra el código fuente del tag v0.8.5 y con stubs; la confirmación de punta a punta (preflight en verde + Stage 1 extrayendo la biblia de investigación con `chat_ask`) requiere sesión NotebookLM viva → **Antigravity** (checklist: `05_TESTS/ANTIGRAVITY_VALIDACION_PRODUCCION.md`).
