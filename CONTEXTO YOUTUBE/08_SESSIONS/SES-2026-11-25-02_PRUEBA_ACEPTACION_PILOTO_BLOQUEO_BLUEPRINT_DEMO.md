# SES-2026-11-25-02 — Prueba de Aceptación Piloto 3 Escenas y Diagnóstico de Clave en Contrato de API

- **Fecha:** 2026-11-25
- **Estado:** BLOQUEADO EN STAGE 2 / DIAGNOSTICADO CON EVIDENCIA LITERAL (FLOW CDP ESTABLE; BLOQUEO POR BLUEPRINT_DEMO)
- **Repo:** `D:\PROYECTOS\YOUTUBE AUTOMATION`
- **HEAD:** `ac9340d` (`main`)
- **Run ID:** `run_20261125_030514_9c6874`

---

## 1. Objetivo y Alcance

Ejecutar una prueba de aceptación REAL sobre el producto, de punta a punta, sin cambios de código, para validar:
1. **BL1-BL4:** Resolución de `startFrame` por nombre/prefijo en Google Flow (`assets.js`, `flow.js`) y política de reintentos en `flow_generate_image`.
2. **BM1-BM4:** Incorporación de `video_prompt` literal y subtítulos limpios (`subtitle_text`).
3. **Flujo E2E:** 3 escenas ejecutadas en Google Flow y render final ensamblado vía FFmpeg.

---

## 2. Prechequeo y Línea Base (Paso 0)

1. **CDP 9333 (`/json/version`):**
   - Versión de navegador: `Chrome/158.0.8127.36`.
   - `webSocketDebuggerUrl`: `ws://127.0.0.1:9333/devtools/browser/b0df391b-5886-43ca-9c80-75dbff16dfaa`.
2. **Health y Auth:**
   - `GET /api/health` -> HTTP 200 OK (`version: 2.47.0`, `gemini: true`, `nvidia: true`).
   - `GET /api/auth/status` -> HTTP 200 OK (`auth_required: false`).
3. **Línea Base de Assets (`flow_list_assets`):**
   - `POST /api/mcp/execute` -> HTTP 200 OK (`ok: true`, 26 assets listados, ancla `personaje` presente).

---

## 3. Lanzamiento del Piloto (Paso 1)

Se envió `POST /api/pipeline/run` con el payload de 3 escenas (*"La traición de la pera"*), nicho `frutinovelas`, formato `short`, `max_scenes: 3` y la estructura de escenas conteniendo `video_prompt` y `subtitle_text`.
- **Run ID generado:** `run_20261125_030514_9c6874`.

---

## 4. Evolución de la Corrida y Diagnóstico Forense (Paso 2)

### Trazabilidad por Etapas:
- **Preflight (Etapa 0):** `notebooklm` ✅ · `google-flow` ✅ · cuaderno `5b7728cb-3e1e-480f-ae82-786f61c0179b` auto-descubierto.
- **Stage 1 (Reading NotebookLM):** Fallo HTTP 400 en RPC batchexecute de NotebookLM; activación inmediata del fallback transparente a contexto local de `frutinovelas` (2,875 caracteres cargados con éxito).
- **Keepalive Flow CDP:** Durante toda la etapa 1 y 2, el monitor en segundo plano mantuvo pings activos a Google Flow (`flow_list_assets`), respondiendo en 2.3s, 1.7s, 4.6s y 0.9s sin ningún cuelgue ni síntoma de `FLOW_CDP_SLOW`.
- **Stage 2 (Generating Blueprint — Bloqueo):**
  - El orquestador intentó invocar a Gemini en lugar de consumir directamente el blueprint externo de Claude.
  - El cliente de Gemini falló reiteradamente:
    - `gemini-3.8-flash`: HTTP 503 Service Unavailable tras timeouts de 90s.
    - `gemini-flash-latest`: HTTP 404 Not Found.
    - `gemini-2.5-flash`: HTTP 404 Not Found (`model is no longer available to new users`).
  - El generador cayó al generador local demo.
  - El guard de seguridad BB5 en [backend/services/pipeline_orchestrator.py#L1183](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/services/pipeline_orchestrator.py#L1183) abortó la corrida para evitar despachar contenido no canónico a Flow:
    ```text
    BLUEPRINT_DEMO: Gemini falló: 404 modelo no disponible — el guion salió del generador demo y no se despacha a Flow
    ```

### Causa Raíz Identificada:
En [backend/main.py#L276](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/main.py#L276), el handler de FastAPI define:
```python
run = _pipe.orchestrator.create_run(
    ...,
    blueprint=body.get("blueprint"))
```
El payload suministrado utilizó la clave `"external_blueprint"` en lugar de `"blueprint"`. Como consecuencia, `body.get("blueprint")` devolvió `None`, el pipeline asumió que no se había provisto un blueprint externo y delegó la generación a Gemini, disparando el aborto por falta de disponibilidad de los modelos externos.

---

## 5. Estado de Mandatos y Pruebas

| Mandato | Estado | Evidencia |
| :--- | :--- | :--- |
| **Estabilidad Flow CDP** | **PASS / VERIFICADO** | Keepalive de Flow respondió en 0.9s-4.6s continuamente; sin `FLOW_CDP_SLOW`. |
| **Fallback Contexto Local** | **PASS / VERIFICADO** | Ingesta de 2,875 caracteres del nicho `frutinovelas` ante incidencia en NotebookLM. |
| **Guard BB5 de Seguridad** | **PASS / VERIFICADO** | Aborto fail-closed ante generación demo con `PIPELINE_ALLOW_DEMO=0`. |
| **BL1-BL4 (Cascada startFrame)** | **BLOQUEADO** | No despachado a Flow por aborto previo en Stage 2. |
| **BM1-BM4 (Prompt/Subtítulos)** | **BLOQUEADO** | Blueprint externo no procesado debido a discrepancia de clave en payload. |

---

## 6. Próxima Acción Recomendada

Para completar la validación de BL1-BL4 y BM1-BM4 sin depender de cuotas ni disponibilidad de Gemini:
1. Enviar el POST a `/api/pipeline/run` asegurando que la clave raíz sea `"blueprint": { ... }` (contrato exacto de `main.py`).
2. Con `"blueprint"`, Stage 2 omite por completo las llamadas a Gemini y despacha inmediatamente las 3 escenas a Google Flow en Stage 3.
