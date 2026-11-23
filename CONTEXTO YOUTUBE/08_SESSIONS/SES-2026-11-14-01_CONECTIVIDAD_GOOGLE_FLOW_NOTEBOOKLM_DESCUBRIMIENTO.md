# SES-2026-11-14-01 — Conectividad en Vivo de Google Flow y NotebookLM + Descubrimiento de Cuadernos y Sonda INT-093

**Fecha:** 2026-11-14T00:45:00-05:00  
**Entorno:** Windows 10/11, Python 3.14.3 / venv Python 3.12, ALBRA Server (Uvicorn puerto 8000), Chrome CDP 9333 (perfil `FlowImageChrome`).  
**Estado:** CLOSED / PASS.

---

## 1. Contexto y Objetivos

El usuario solicitó:
1. Comprobar la conexión real del Ecosistema Google en su máquina local tras el arranque de ALBRA (`launchers\start.bat`).
2. Resolver fallos de autenticación/comunicación en Google Flow y NotebookLM.
3. Ejecutar la sonda de capacidades MCP INT-093 (`tools/sonda_capacidades_nombres.py`).
4. Resolver el listado de notebooks (`[LIST_EMPTY] listado de notebooks vacío o ilegible`) y el semáforo del panel web.

---

## 2. Hallazgos y Diagnósticos en Vivo

### 2.1 Google Flow MCP (5 tools)
- **Estado:** 🟢 Conectado y autenticado.
- **Evidencia:** Prueba en vivo contra el endpoint `/api/mcp/execute` con `tool="flow_list_assets"`, respondiendo en 1.64 segundos con 26 assets existentes del proyecto activo (`scene_01_start`, `scene_02_start`, `Apple in kitchen...`, etc.).
- **Veredicto:** 100% operativo sin cambios requeridos en el transporte de Flow.

### 2.2 Sonda de Capacidades INT-093
- Se ejecutó por HTTP contra el backend activo:
  ```powershell
  backend\.venv\Scripts\python.exe tools\sonda_capacidades_nombres.py --salida sonda_nombres.json
  ```
- **Informe generado:** [`sonda_nombres.json`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/sonda_nombres.json).
- **Resultados de contrato:**
  - `q3_notebook_create_titulo`: **SOPORTADO** (`notebook_create` acepta `title`).
  - `q4_notebook_renombrar`: **SOPORTADO** (`notebook_rename`).
  - `q5_source_add_titulo`: **SOPORTADO** (`notebook_add_text` acepta `title` opcional).
  - Tools de Google Flow: 5 operativas (`flow_upload_file`, `flow_generate_image`, `flow_generate_video`, `flow_list_assets`, `flow_new_project`).

### 2.3 Diagnóstico y Resolución del Error en NotebookLM (`[LIST_EMPTY]`)
Al pulsar «Listar / refrescar notebooks» en la UI, el backend arrojaba:
`Listar notebooks: [LIST_EMPTY] listado de notebooks vacío o ilegible`

**Causas Raíz:**
1. **Migración de Dominio Google:**
   Google migró NotebookLM a `https://notebook.google.com` (rebranding "Gemini Notebook"). El servidor `notebooklm-mcp-server` v0.1.15 enviaba las peticiones RPC a `https://notebooklm.google.com`, lo cual provocaba respuestas `401 Unauthorized`.
2. **Build Label Desactualizado:**
   El parámetro `bl` estaba fijado a un build de enero de 2026 (`boq_labs-tailwind-frontend_20260108.06_p0`), mientras que la versión activa en el frontend de Google era `boq_labs-tailwind-frontend_20261112.11_p0`.
3. **Websocket Origin 403 Forbidden en auth CLI:**
   `websocket.create_connection` en `auth_cli.py` no suprimía el origen por defecto hacia Chrome DevTools en el puerto 9333.
4. **Desfase de Estado en el Frontend (Panel Web):**
   `backend/static/app-mcp.js` llamaba a `/api/mcp/resumen` sin adjuntar los query parameters `notebook_id` ni `nicho_id`. Además, `mcpPickNotebook` no disparaba la actualización visual de la tarjeta superior, manteniendo el indicador de cuaderno en rojo pese a estar seleccionado en el `<select>`.

---

## 3. Remediación Implementada

1. **Soporte de Dominio y Build Label Dinámico:**
   - En [`backend/config.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/config.py):
     `NOTEBOOKLM_BASE_URL = os.getenv("NOTEBOOKLM_BASE_URL", "https://notebook.google.com").strip()`
     `NOTEBOOKLM_BL = os.getenv("NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_20261112.11_p0").strip()`
   - En [`backend/services/mcp_manager.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/services/mcp_manager.py): inyección automática de `NOTEBOOKLM_BASE_URL` y `NOTEBOOKLM_BL` al entorno del subproceso `notebooklm-mcp`.
   - En [`backend/.env.example`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/.env.example) y `backend/.env`: documentación de ambas variables.
   - En el entorno de herramientas uv de `notebooklm_mcp`: actualización de `api_client.py` para respetar las variables de entorno.
   - **Commit:** `49cce1f` (`fix(notebooklm): soportar notebook.google.com y bl activo en mcp_manager y api_client`).

2. **Propagación de Cuaderno y Nicho en el Frontend:**
   - En [`backend/static/app-mcp.js`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/static/app-mcp.js):
     - `gsessRefresh` ahora serializa `notebook_id` y `nicho_id` en la query string a `/api/mcp/resumen`.
     - `mcpPickNotebook` y `mcpNichoChange` invocan `gsessRefresh(true)` inmediatamente tras la selección.
   - **Commit:** `0778ae4` (`fix(ui): propagar notebook_id y nicho_id en gsessRefresh y refrescar al elegir cuaderno`).

---

## 4. Verificación en Vivo

1. **Listado de Cuadernos:**
   Llamada a `POST /api/mcp/list-notebooks` devolvió con éxito 10 cuadernos reales:
   - *FRUTINOVELAS* (`5b7728cb-3e1e-480f-ae82-786f61c0179b`)
   - *Alex Hormozi* (`f70b902c-df5a-454c-8733-b70a2fd2cdb7`)
   - *VITAL ESSENCE* (`e68abdd1-10ce-4bdf-a1c3-6ffb2c4dc8fa`)
   - *AGENTE TRADING* (`c3ea95dc-c257-42d3-b417-ce7221bec206`)
   - *Automatización OpenClaw* (`09c57f0a-0021-410c-9f95-761275bb0b80`)
   - *Jürgen Klaric* (`51a35e86-fba9-4311-b330-85e2474561cb`)
   - *TLP* (`c20485ef-2d63-46f6-ab37-86b8bd56d1da`)
   - *HOJA DE GUANABANA* (`bde945dc-a40d-4213-9ab2-3b2b23f3f04a`)
   - *(y 2 cuadernos sin título).*

2. **Resumen del Ecosistema:**
   `GET /api/mcp/resumen?nicho_id=datos-curiosos` reportó:
   - `chrome.ok`: `true`
   - `flow.ok`: `true`
   - `notebooklm.ok`: `true`
   - `cuaderno.ok`: `true`
   - `todo_conectado`: `true`
   - `listo_para_pipeline`: `true` (4/4 verde).

3. **Suites de Tests Herméticas:**
   - `tests/test_notebooklm_base_url.py`: 1/1 PASSED.
   - `tests/test_u_panel_ecosistema.py`: 21/21 PASSED.
   - `tests/test_mcp_manager.py`: 38/38 PASSED.
   - `tests/test_u1_mcp_resumen.py`: 11/11 PASSED.
   - `ruff check`: 0 fallos de linter.
