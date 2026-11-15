# SES-2026-11-14-02 — Cierre BB1-BB4 y Sincronización Dual de Credenciales en NotebookLM MCP

**Fecha:** 2026-11-14T19:30:00-05:00  
**Entorno:** Windows 10/11, Python 3.12 / 3.14.3, Uvicorn en puerto 8000 (PID 12816), Chrome CDP 9333 (`FlowImageChrome`), FastMCP / uv tool `notebooklm-mcp-server`.  
**Estado:** CLOSED / PASS.

---

## 1. Objetivos de la Sesión

1. **Ejecutar y validar los mandatos BB1 a BB4:**
   - **BB1:** Cambiar default de `NOTEBOOKLM_CONTEXT_TOOL` a `notebook_query` en `backend/config.py` y `pipeline_orchestrator.py` con fallback resiliente ante herramientas no expuestas o `TOOL_UNKNOWN`.
   - **BB2:** Interpretar la respuesta de `notebook_query`: extraer exclusivamente el campo `answer` si es JSON; validar `status == "success"` y presencia de texto o fallar con `CONTEXT_EMPTY`.
   - **BB3:** Resolver el trinquete de excepciones (`test_p2_2_except_ratchet.py`) manteniendo el baseline estricto de 286 ocurrencias mediante el helper unificado `_exposed_tools` y tuplas de excepciones específicas. Actualizar [ESTADO_REAL.md](../../ESTADO_REAL.md) a 60 baterías e incluir detalles literales de error en `CONTEXT_EMPTY`.
   - **BB4:** Revertir el fallback Pillow/NumPy de `remove_product_background` en [ecommerce_overlays.py](../../backend/services/ecommerce_overlays.py) para que sin `cv2` lance explícitamente `ImportError("instala opencv-python-headless para el modo e-commerce")`. Declarar `opencv-python-headless` en [requirements.txt](../../backend/requirements.txt) y proteger los tests con `pytest.importorskip("cv2")`.
2. **Resolver la reaparición del error `[LIST_EMPTY]` en el selector de cuadernos de NotebookLM.**
3. **Verificar el Ecosistema Google en vivo (4/4 verde) y dejar el servidor preparado para el Piloto P2.**

---

## 2. Diagnóstico Técnico: Causa de la Desincronización en NotebookLM

### 2.1 El problema de doble almacenamiento (`storage_state.json` vs `auth.json`)
Al pulsar «Listar / refrescar notebooks» en la interfaz web, el sistema reportaba intermitentemente:
```text
Listar notebooks: [LIST_EMPTY] listado de notebooks vacío o ilegible
RPC Error 16: Authentication expired
```

Se identificó la discrepancia arquitectónica entre dos componentes:
- **`backend/services/mcp_manager.py` (código heredado):** la función `capture_google_session()` extraía cookies de Chrome por CDP y las escribía en la estructura de `notebooklm-py`:  
  `~/.notebooklm/profiles/default/storage_state.json` (formato lista de objetos `[{name, value, domain, ...}]`).
- **`notebooklm-mcp-server` (paquete activo de FastMCP ejecutado como `notebooklm-mcp`):** este servidor **NO** lee de `~/.notebooklm/`, sino de:  
  `~/.notebooklm-mcp/auth.json` (formato diccionario plano `{cookies: {NAME: VALUE}, csrf_token, session_id, extracted_at}`).

Dado que `auth.json` nunca se actualizaba automáticamente al hacer login o pulsar «Conectar todo», contenía cookies obsoletas que expiraban con el tiempo, causando el rechazo de Google (`Authentication expired`).

---

## 3. Remediación Implementada

### 3.1 Sincronización Dual Automática (`_sync_auth_json`)
En [backend/services/mcp_manager.py](../../backend/services/mcp_manager.py):
- Se añadió el método privado `_sync_auth_json(self, cookies: list[dict]) -> None`.
- Cada vez que `capture_google_session()` obtiene cookies frescas de Chrome CDP, actualiza de inmediato `~/.notebooklm-mcp/auth.json` preservando los tokens CSRF y Session IDs existentes y actualizando las cookies activas.
- El manejo de excepciones captura exclusivamente `OSError` y `(json.JSONDecodeError, OSError)`, evitando cualquier incremento en el trinquete de excepciones de `test_p2_2_except_ratchet.py`.

### 3.2 Correcciones de BB1 a BB4
- **BB1:** `NOTEBOOKLM_CONTEXT_TOOL = "notebook_query"` configurado como default canónico en [config.py](../../backend/config.py) y en [pipeline_orchestrator.py](../../backend/services/pipeline_orchestrator.py). Si el servidor no la expone pero sí expone `notebook_query`, degrada con log informativo.
- **BB2:** En Stage 1 de [pipeline_orchestrator.py](../../backend/services/pipeline_orchestrator.py), parsing tolerante de `parsed_json` extrayendo el campo `"answer"`. Si `status != "success"` o `"answer"` está vacío, emite `CONTEXT_EMPTY`.
- **BB3:** Helper unificado `_exposed_tools` en `PipelineOrchestrator` reemplazando los dos bloques try/except duplicados. Trinquete verificado en 286 ocurrencias. [ESTADO_REAL.md](../../ESTADO_REAL.md) actualizado a 60 baterías con la fila oficial de `test_bb_stage1_notebook_query.py`.
- **BB4:** `remove_product_background` en [ecommerce_overlays.py](../../backend/services/ecommerce_overlays.py) lanza `ImportError` explícito ante la ausencia de OpenCV. `opencv-python-headless>=4.8` declarado en [requirements.txt](../../backend/requirements.txt). Tests en [test_int055_ecommerce_overlays.py](../../tests/test_int055_ecommerce_overlays.py) protegidos con `pytest.importorskip("cv2")`.

---

## 4. Evidencia de Verificación en Vivo

### 4.1 Descubrimiento de Cuadernos (`POST /api/mcp/list-notebooks`)
Respuesta real y directa del servidor local en `http://127.0.0.1:8000/api/mcp/list-notebooks`:
```json
{
  "ok": true,
  "tool": "notebook_list",
  "notebooks": [
    { "id": "5b7728cb-3e1e-480f-ae82-786f61c0179b", "title": "FRUTINOVELAS" },
    { "id": "bde945dc-a40d-4213-9ab2-3b2b23f3f04a", "title": "HOJA DE GUANABANA" },
    { "id": "c20485ef-2d63-46f6-ab37-86b8bd56d1da", "title": "TLP" },
    { "id": "51a35e86-fba9-4311-b330-85e2474561cb", "title": "Jürgen Klaric" },
    { "id": "09c57f0a-0021-410c-9f95-761275bb0b80", "title": "Automatización OpenClaw" },
    { "id": "c3ea95dc-c257-42d3-b417-ce7221bec206", "title": "AGENTE TRADING" },
    { "id": "f70b902c-df5a-454c-8733-b70a2fd2cdb7", "title": "Alex Hormozi" }
  ],
  "first_id": "5b7728cb-3e1e-480f-ae82-786f61c0179b"
}
```

### 4.2 Estado de Conexión del Ecosistema (`GET /api/mcp/resumen`)
```json
{
  "piezas": {
    "chrome":     { "ok": true, "detalle": "Chrome CDP 9333 arriba" },
    "flow":       { "ok": true, "detalle": "Google Flow conectado y autenticado · 5 tools" },
    "notebooklm": { "ok": true, "detalle": "NotebookLM conectado y autenticado · 32 tools" },
    "cuaderno":   { "ok": true, "detalle": "cuaderno «5b7728cb-3e1e-480f-ae82-786f61c0179b» seleccionado" }
  },
  "listo_para_pipeline": true,
  "todo_conectado": true,
  "siguiente_paso": "Todo listo: escribe la idea y lanza «Run Full Pipeline»."
}
```

### 4.3 Resultados de Calidad y Regresión
- **Pytest Suite Completo:** 811 passed, 1 skipped (cv2), 0 failed.
- **Trinquete de Excepciones:** `tests/test_p2_2_except_ratchet.py` -> 2 passed (sin subir baseline 286).
- **Linter de CI:** `ruff check --select F821,E9,F63,F7,F82 backend tools tests` -> 0 findings.
- **Compilación de Sintaxis:** `python -m compileall` sobre `backend`, `tests` y `tools` -> Exit code 0.
- **Guardias StartFrame F2:** `tests/test_flow_startframe_fase2.py` -> 67 OK · 0 fallos.

---

## 5. Estado Actual del Sistema

- **Servidor ALBRA:** Proceso Uvicorn activo en `127.0.0.1:8000` ejecutando el commit vigente.
- **Google Flow MCP:** Conectado y autenticado (5 herramientas disponibles).
- **NotebookLM MCP:** Conectado y autenticado (32 herramientas disponibles).
- **Cuaderno Activo:** `5b7728cb-3e1e-480f-ae82-786f61c0179b` (*FRUTINOVELAS*).
- **Listo para Piloto P2:** Listo para recibir orden de ejecución de prueba en vivo.
