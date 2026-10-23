# INT-022 · MCP CONNECTION MANAGER — Panel de Control ↔ servidores MCP (Google Flow + NotebookLM)

**Estado:** IMPLEMENTADO — VALIDACIÓN REAL CON SESIÓN GOOGLE PENDIENTE
**Mandato:** orden directa del usuario (Senior Full-Stack & AI Automation Architect): puente
de transporte UI↔MCP, persistencia de sesión (CDP/userDataDir), notebookId dinámico y
triggers visuales en el panel.

## 1. Objetivo

El panel (navegador) no puede hablar **stdio** con los servidores MCP externos. Este
intégration añade un **cliente MCP persistente en el backend** (`services/mcp_manager.py`)
más 5 endpoints REST, y un componente **"MCP Connection Manager"** en el dashboard con
badges de estado, toggles conectar/desconectar, selector de `notebookId` y botón
**Test Pipeline** (dry-run). No hay arquitecturas paralelas: reutiliza `tools/GoogleFlowMCP`
y el ecosistema `notebooklm-py` ya elegido en la Misión NotebookLM (candidato A).

## 2. Decisiones críticas

| Decisión | Justificación |
|---|---|
| Cliente propio en vez de reusar `flow_mcp_client` | `flow_mcp_client` es **one-shot** (spawn→call→kill por operación) y lo usa el orquestador: se queda INTACTO. El manager mantiene la conexión viva para el panel (menos latencia, estado consultable). |
| Framing JSON-RPC por líneas | El mismo de `flow_mcp_client` y del transporte stdio de MCP; un solo formato para ambos servidores. |
| Sesión Google Flow: sin código nuevo | `GoogleFlowMCP/src/chrome.js` ya usa **Chrome dedicado + `--remote-debugging-port` (CDP) + user-data-dir propio** y Chrome sobrevive al proceso Node. El backend solo propaga `FLOW_CDP_PORT` (default 9333, igual a chrome.js) y verifica el CDP en preflight. |
| AUTH_REQUIRED como estado, no como 5xx | El preflight (§2 del mandato) corre tras `tools/list`: para flow llama `flow_list_assets` y detecta el texto real `"Not signed in"`; para notebooklm llama la sonda `NOTEBOOKLM_PROBE_TOOL` (default `list_notebooks`) y detecta errores con patrón de auth (regex `not signed in|auth|cookie|...`). El badge rojo lo pinta la UI con el detalle. |
| notebookId dinámico (§3) | Precedencia: `arguments[notebook_id]` (tool) → `body.notebook_id` (panel) → `.env NOTEBOOKLM_NOTEBOOK_ID`. Validación de patrón `^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$` (rechaza inyección). Clave de inyección configurable (`NOTEBOOKLM_ID_KEY`, default `notebook_id`). Si no hay id: pasa los argumentos y devuelve `warnings` (no rompe). |
| Allowlist notebooklm | `NOTEBOOKLM_MCP_TOOLS` (coma). Vacío = todas (panel local detrás de `auth_guard`); ejemplo solo-lectura en `.env.example`. google-flow: todas sus `flow_*` (son las del propio servidor). |

## 3. Cambios por archivo

| Archivo | Cambio |
|---|---|
| `backend/services/mcp_manager.py` | **NUEVO** (~440 l): `MCPClientManager` (spawn stdio, handshake `initialize`→`initialized`→`tools/list`, ejecución `tools/call` con timeouts y limpieza de proceso, preflight de sesión, `_cdp_up` vía urllib en thread, `stderr_tail` para diagnóstico, estados canónicos). |
| `backend/config.py` | +13 líneas: `FLOW_CDP_PORT`, `NOTEBOOKLM_MCP_CMD/TIMEOUT/TOOLS`, `NOTEBOOKLM_PROBE_TOOL`, `NOTEBOOKLM_ID_KEY`, `NOTEBOOKLM_NOTEBOOK_ID`, `NOTEBOOKLM_HOME`. |
| `backend/main.py` | +5 endpoints (sección INT-022, heredan `auth_guard`/`csrf_guard`): `POST /api/mcp/connect`, `POST /api/mcp/disconnect`, `GET /api/mcp/status`, `POST /api/mcp/execute`, `POST /api/mcp/test-pipeline`. |
| `backend/static/app.js` | +~170 l: `renderMCP`, badges, acciones `mcpConnect/mcpDisconnect/mcpTest/mcpRefresh`, inyección en `updatePills` (pills `pill-flow`/`pill-nblm` en topbar), refresh silencioso al arrancar. |
| `backend/static/index.html` | Botón nav "🔌 MCP" + 2 pills topbar + cache-bust `?v=2.21.0`. |
| `backend/static/style.css` | +estilos `.mcp-svc/.mcp-badge/.mcp-log` (tokens existentes `--ok/--warn/--err/--muted`). |
| `backend/.env.example` | Sección INT-022 documentada. |
| `tools/mcp-setup/` | **NUEVO**: `login-notebooklm.{bat,sh}` y `open-flow-chrome.{bat,sh}` — primera ejecución del login Google una sola vez (los "triggers manuales" de la máquina). |
| `tests/fixtures/fake_mcp_server.py` | **NUEVO**: servidor MCP stdio falso (modos `flow`/`nblm`, fallo de auth, tool lenta). |
| `tests/test_mcp_manager.py` | **NUEVO**: batería S1-S11 (38 checks). |
| `tests/run_all.py` | Registro de la batería (48 en total). |

## 4. Batería S1-S11 (sin ejecutar aún en tu máquina)

S1 connect/handshake/tools/list · S2 execute roundtrip + tool desconocida ·
S3 preflight AUTH_REQUIRED ("Not signed in" real de Flow) · S4 timeout con limpieza ·
S5 notebook_id payload>.env>ausencia+warnings · S6 allowlist · S7 auth JSON-RPC nblm ·
S8 test_pipeline + validez de id · S9 código de error estable · S10 stderr_tail ·
S11 endpoints REST ASGI (conect/status/execute/400s/test-pipeline/disconnect).

## 5. Pendiente honesto

- **Validación real con sesión Google** (no existe en el sandbox): conectar contra
  `notebooklm-mcp` real y `GoogleFlowMCP` real desde tu máquina (scripts de `tools/mcp-setup/`).
- Los nombres reales de las tools de `notebooklm-py` se descubren en vivo vía `tools/list`
  (el panel las lista); la sonda `list_notebooks` es el default y es ajustable por `.env`.
- Flujo completo §3 "await confirmation before triggering YouTube Agent → Google Flow":
  la pieza de orquestación agente→pipeline NO se toca aquí (orden: no romper el agente);
  el panel cubre validar/inyectar/probar; el encadenamiento automático queda para la
  especialización del agente (INT futura).

## 6. Límites

- El manager no gestiona servidores SSE/HTTP remotos — solo stdio (alcance del mandato).
- `execute` está pensado para el panel y el agente local; el pipeline de producción sigue
  usando `flow_mcp_client` (INT-012 y gates intactos).
