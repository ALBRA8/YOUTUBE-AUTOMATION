# SES-2026-11-14-03 — Diagnóstico Chrome/Flow/Gemini + Implementación BB5 (Pipeline Guards & Auth Sync)

**Fecha/Hora:** 2026-11-14T20:55:00-05:00  
**Estado:** CLOSED / PASS  
**Rama:** `main`  
**Entorno:** Windows, Python 3.14 (venv `backend/.venv`)  

---

## 1. Objetivos de la Sesión
1. **Parte A (Diagnóstico de Chrome/Flow y Clave Gemini):**
   - Evaluar endpoint `/json/version` en puerto 9333 y conectividad WebSocket CDP.
   - Evaluar ejecución de `flow_list_assets` vía `POST /api/mcp/execute`.
   - Inspeccionar procesos del sistema de Chrome asociados al puerto 9333 y perfil Flow.
   - Ejecutar flujo de conexión completa (`POST /api/mcp/connect-all-google`) ante fallos.
   - Comprobar validez de `GEMINI_API_KEY` vía GET a Google GenAI models sin exponer secretos.
2. **Parte B (Implementación de Cambios BB5):**
   - **BB5.1:** Abortar la corrida en Etapa 2 con código `BLUEPRINT_DEMO` y detalle explícito si el motor de guion es `local-demo` y `PIPELINE_ALLOW_DEMO != "1"`.
   - **BB5.2:** Parámetro opcional `max_scenes` (1-12) en `POST /api/pipeline/run` para recortar el blueprint antes de la Etapa 3 conservando la última escena como cierre.
   - **BB5.3:** Validación y escritura atómica en `_sync_auth_json` (mcp_manager): no escribir si la lista de cookies está vacía o carece de `SID` o `__Secure-1PSID`; atomic write vía archivo temporal + `os.replace`; `os.chmod 600` donde aplique; logging con `warning` en lugar de silenciamiento.
   - Batería nueva de tests herméticos: `tests/test_bb5_pipeline_guards.py` integrada en `tests/run_all.py` (61 baterías canónicas).
   - Actualización de `ESTADO_REAL.md` y `ROADMAP.md`.
3. **Parte C (Verificación Completa):**
   - `compileall`, `ruff`, `pytest` completo y `tests/run_all.py`.
4. **Parte D (Condición de Piloto):**
   - Sujeto a que A(b) dé OK y A(e) dé HTTP 200. En caso de HTTP 400 en Gemini (`API_KEY_INVALID`), saltar la parte D informando las causas.

---

## 2. Hallazgos y Mediciones de la Parte A
- **A(a) WebSocket CDP:** OK en 0.14 s. Chrome responde versión `Chrome/157.0.8103.40` y WebSocket `ws://127.0.0.1:9333/devtools/browser/3bf4bade-9583-4370-9ecd-18ae2e3b95a3`.
- **A(b) Flow List Assets:** Falla con HTTP 502 en 30.51 s (`browserType.connectOverCDP: Timeout 30000ms exceeded`).
- **A(c) Procesos Chrome 9333:** 5 procesos detectados (1 proceso principal PID 7556 + 4 helpers/renderers). Perfil principal único: `google_profile_global`. La ventana visual requiere mirada humana.
- **A(d) Conectar Todo y Reintento:** `POST /api/mcp/connect-all-google` completado con HTTP 200 en 3.30 s. Reintento A(a) OK en 0.15 s. Reintento A(b) vuelve a fallar con HTTP 502 en 30.34 s por timeout de CDP en GoogleFlowMCP.
- **A(e) Validación Clave Gemini:** Clave presente (longitud 39). Petición GET devolvió HTTP 400 con motivo `API_KEY_INVALID`.

---

## 3. Implementación de Cambios BB5
1. **`backend/services/pipeline_orchestrator.py`:**
   - En `create_run`: aceptación y validación del entero `max_scenes` (1-12) lanzando `PipelineError` con código `INVALID_MAX_SCENES`.
   - En `_run` (Stage 2): comprobación de `res2.get("engine") == "local-demo"` abortando con `BLUEPRINT_DEMO` si `PIPELINE_ALLOW_DEMO != "1"`.
   - Recorte de escenas con `(scenes[:ms - 1] + [scenes[-1]]) if ms > 1 else [scenes[-1]]` y reindexación determinista de `scene_id`.
2. **`backend/main.py`:**
   - En `pipeline_run`: extracción y validación de `max_scenes` (1-12) lanzando HTTP 400 ante tipos inválidos o fuera de rango.
3. **`backend/services/mcp_manager.py`:**
   - `_sync_auth_json`: validación estricta de presencia de cookies de sesión Google (`SID` o `__Secure-1PSID`), escritura con `tempfile.mkstemp` + `os.replace` atómico y `os.chmod(..., 0o600)`, con captura de `OSError` y advertencias de log.
4. **`tests/test_bb5_pipeline_guards.py`:**
   - 5 tests unitarios herméticos sin red cubriendo todas las ramas de BB5 (100% passed).
5. **Preservación de Trinquetes:**
   - Trinquete `test_p2_2_except_ratchet.py` conservado exactamente en baseline 286.

---

## 4. Resultado de Verificación
- `compileall`: 0 errores.
- `ruff`: 0 infracciones en selectores obligatorios.
- `pytest`: suite completa hermética en verde.
- `tests/run_all.py`: 61 baterías canónicas registradas.
