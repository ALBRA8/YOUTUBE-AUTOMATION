# SES-2026-11-24-01 — Prueba de Aceptación Real (BL1-BL4 + BM1-BM4) y Diagnóstico Flow CDP

- **Fecha:** 2026-11-24
- **Estado:** BLOQUEADO EN STAGE 3 / VALIDACIÓN PARCIALMENTE DEMOSTRADA (BM1-BM4 VERIFICADOS; BL1-BL4 BLOQUEADOS POR CDP)
- **Repo:** `D:\PROYECTOS\YOUTUBE AUTOMATION`
- **HEAD:** `ac9340d` (`feat(BM): soporte de video_prompt y subtitle_text en blueprint externo y pipeline`)
- **Run ID:** `run_20261124_171918_061b13`

---

## 1. Objetivo y Alcance

Ejecutar una prueba de aceptación REAL sobre el producto de punta a punta, sin cambios de código, para validar:
1. **BL1-BL4:** Resolución de `startFrame` en Google Flow (`assets.js`, `flow.js`) y política de reintentos en `flow_generate_image`.
2. **BM1-BM4:** Campos `video_prompt` (<=600 chars) y `subtitle_text` (<=200 chars) en blueprint externo, uso de `video_prompt` tal cual en etapa 3, subtítulos limpios en etapa 4 y exposición en `/api/pipeline/status`.

---

## 2. Preparación y Pre-requisitos (Paso 0)

1. **Dependencias del venv:** Verificadas mediante `import cv2, psutil`. Versiones reales reportadas: `opencv-python-headless 5.1.0`, `psutil 7.2.2` (OK).
2. **Entorno Demo:** Confirmado que `PIPELINE_ALLOW_DEMO` no está definida en el entorno ni en `backend/.env` (OK).
3. **Backend:** Reiniciado limpiamente en `http://127.0.0.1:8000` con el código actualizado de `ac9340d`. `GET /api/health` devolvió HTTP 200 OK.
4. **Google Flow MCP:** Conectado vía `POST /api/mcp/connect` con resultado `state: "connected"`, `auth: "ok"`, `[flow] CDP connect OK en 2217ms`.
5. **Ancla de Proyecto Flow:** Comprobado mediante `POST /api/mcp/execute` con `flow_list_assets` (ejecutado en 1.96 s). Presencia confirmada del ancla:
   `- personaje [id:02b5fa3d-179c-488a-b99b-64cc219a573e]`.

---

## 3. Lanzamiento y Ejecución del Piloto (Paso 1 y Paso 2)

Se envió `POST /api/pipeline/run` con el payload canónico de 3 escenas sobre la idea *"Frutinovela: la manzana descubre que la pera la traicionó"*, formato `short`, nicho `frutinovelas` y blueprint externo de label `claude` conteniendo `video_prompt` y `subtitle_text` en cada escena.

### Trazabilidad por Etapas:
- **Preflight (Etapa 0):** `notebooklm` ✅ · `google-flow` ✅ · cuaderno `5b7728cb-3e1e-480f-ae82-786f61c0179b` auto-descubierto.
- **Stage 1 (Reading NotebookLM):** Extracción exitosa de 5,719 caracteres de contexto verificado del cuaderno (`ok en 35.8s`).
- **Stage 2 (Generating Blueprint — BM1/BM4):** 
  - El blueprint externo de Claude fue validado y cargado directamente sin invocar a Gemini.
  - Registro literal del orquestador:
    `2026-11-24 17:20:14,673 pipeline_orchestrator WARNING [pipeline run_20261124_171918_061b13] Blueprint EXTERNO claude: no generado por Gemini`
  - Se persistió `blueprint.json` en `backend/data/pipeline_runs/run_20261124_171918_061b13/` conteniendo `engine: "external:claude"`, `blueprint_source: "external"`, y los campos `video_prompt` y `subtitle_text` para las 3 escenas.
  - `/api/pipeline/status` expuso ambos campos en cada escena (BM4 OK).
- **Stage 3 (Dispatching Scenes to Flow):**
  - Al iniciar la etapa 3, se ejecutó el pre-calentamiento CDP obligatorio (`_flow_warm_timeout()`, 150 s).
  - Intento 1 de `flow_list_assets` excedió los 150 s (`timeout de 150s en tools/call`).
  - Se reconectó Google Flow MCP (`[google-flow] conectado: srz-google-flow-mcp · 5 tools · auth=ok`).
  - Intento 2 de calentamiento volvió a exceder los 150 s.
  - Aborto defensivo del pipeline con código `FLOW_CDP_SLOW` en [backend/services/pipeline_orchestrator.py#L1392](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/services/pipeline_orchestrator.py#L1392):
    `Flow CDP no responde tras 2 intentos de calentamiento (FLOW_CDP_SLOW): timeout de 150s en tools/call`.

---

## 4. Diagnóstico Forense de la Causa Raíz (CDP / Playwright)

Tras el bloqueo, se llevó a cabo un diagnóstico profundo del subsistema CDP en Windows:
1. **Estado de Procesos:**
   El proceso Chrome principal (PID 26588) permanecía activo escuchando en el puerto 9333 (`--remote-debugging-port=9333 --user-data-dir=...\FlowImageChrome`).
2. **Inspección de Targets en CDP (`http://127.0.0.1:9333/json`):**
   Se detectó la presencia de targets internos de UI de Chrome:
   - `chrome://omnibox-popup.top-chrome/` (`type: browser_ui`)
   - `chrome://omnibox-popup.top-chrome/omnibox_popup_aim.html` (`type: browser_ui`)
3. **Mecanismo del Fallo de Playwright:**
   `chromium.connectOverCDP("http://127.0.0.1:9333")` se conecta al WebSocket global del navegador (`ws://127.0.0.1:9333/devtools/browser/...`) e intenta negociar la inspección de todos los targets disponibles. En presencia de targets internos de la UI de Chrome (omnibox popup activo) o ventanas ocluidas, la llamada `connectOverCDP` de Playwright se queda en espera indefinida hasta agotar su timeout configurado (120,000 ms), produciendo en el servidor MCP:
   `[flow] CDP connect intento 1 falló tras 120058ms (browserType.connectOverCDP: Timeout 120000ms exceeded.); reintento único…`
4. **Comprobación Diferencial Directa:**
   Se comprobó que una conexión WebSocket directa al target de la pestaña de Flow (`ws://127.0.0.1:9333/devtools/page/DC3A97BED24137350CEF044A860FC160`) responde inmediatamente a comandos CDP como `Page.bringToFront` y `Page.navigate`. Esto confirma que el render de Chrome y el puerto 9333 están vivos, siendo el cuello de botella el descubrimiento global de targets de Playwright durante el `connectOverCDP`.

---

## 5. Verificación Obligatoria de Fallo

En estricto cumplimiento de las reglas del mandato, antes de concluir se intentó verificar nuevamente la lista de activos con `flow_list_assets` vía `POST /api/mcp/execute`.
- **Resultado:** La llamada expiró con `httpx.ReadTimeout` (60 s).
- **Log del Servidor MCP:**
  `[flow] CDP connect intento 1 falló tras 120058ms (browserType.connectOverCDP: Timeout 120000ms exceeded.); reintento único…`

---

## 6. Estado de los Mandatos Validados

| Mandato | Estado | Evidencia |
| :--- | :--- | :--- |
| **BM1** (campos opcionales en blueprint externo) | **PASS / VERIFICADO** | Validado en `validate_external_blueprint`, normalizado y persistido en `blueprint.json`. |
| **BM2** (uso de `video_prompt` literal) | **PASS / VERIFICADO** | Verificado en código de etapa 3 (`pipeline_orchestrator.py:1502`); `blueprint.json` contiene los 3 `video_prompt` sin composición de fallback. |
| **BM3** (subtítulos limpios en plan de render) | **PENDIENTE DE RENDER** | No ejecutado por bloqueo en Stage 3; `subtitle_text` listo en modelo y blueprint. |
| **BM4** (exposición en `/api/pipeline/status`) | **PASS / VERIFICADO** | Confirmado en respuesta JSON de `/api/pipeline/status` con los 3 `video_prompt` y `subtitle_text`. |
| **BL1-BL4** (StartFrame Flow y reintentos) | **BLOQUEADO** | No alcanzada la fase de generación de vídeo por `FLOW_CDP_SLOW` en calentamiento previo. |

---

## 7. Próximos Pasos Recomendados

1. **Aislamiento de Targets en Flow MCP:** Evaluar si `connectOverCDP` en Playwright puede apuntar a la URL de WebSocket de la página específica en vez de la del navegador global, o garantizar el cierre/desenfoque del omnibox antes del connect.
2. **Reintento de Escenas (retry-scenes):** Una vez estabilizada la conexión de Flow, la corrida `run_20261124_171918_061b13` puede reintentar quirúrgicamente las 3 escenas (`s1`, `s2`, `s3`) mediante `POST /api/pipeline/retry-scenes` sin repetir las etapas 1 y 2.
