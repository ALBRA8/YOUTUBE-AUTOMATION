# SESSION INDEX

## SES-2026-10-18-01 — Auditoría ALBRA + Start Frame
- **Estado:** memoria de sesión registrada; ejecución real pendiente.
- **Hecho:** se retomó contexto previo, compararon referencias Git y leyeron README/INDEX/master/ESTADO_REAL; se inspeccionaron `injectScene`, `__bridgeHandleJob`, `readStartFrame` y `injector.js`.
- **Hallazgo:** el camino Flow inyecta prompt; readStartFrame es Meta AI; no se demostró body de request con binding de imagen.
- **Decisiones:** no implementar aún; no mover lógica a AGENTE-GENERAL; preservar P1 y capas existentes.
- **Pendiente:** una generación real desde ALBRA con imagen conocida y captura sanitizada.
- **Límite:** esta sesión no abrió Chrome ni generó vídeo real; conclusiones externas previas se registran como contexto histórico, no como nueva prueba.

## SES-2026-10-18-02 — Google Flow Start Frame: captura manual en vivo
- **Estado:** IN_PROGRESS / CAPTURA PARCIALMENTE COMPLETADA.
- **Hecho:** se instaló/cargó la extensión instrumentada v2.5.0; se comprobó `window.__FLOW_RPC_OBS__`; en Flow se seleccionó `Fotogramas`, se colocó una imagen conocida en `Iniciar`, se dejó `Finalizar` vacío y se generó un vídeo real.
- **Hallazgo:** Flow separa `Fotogramas` de `Ingredientes` y presenta slots `Iniciar`/`Finalizar`; la instrumentación observó tráfico `WuwhI` real.
- **Evidencia actual:** 4 observaciones `WuwhI` en `window.__FLOW_RPC_OBS__` después de la generación.
- **Límite:** la tabla de DevTools ocultó campos; aún no se ha identificado de forma concluyente el `WuwhI` de generación ni su `mediaId` de Start Frame.
- **Decisión:** no generar otra vez ni implementar binding todavía; leer los cuatro registros almacenados y clasificar.
- **Referencia:** `SES-2026-10-18-02_GOOGLE_FLOW_START_FRAME_LIVE_CAPTURE.md`.

## SES-2026-10-19-01 — LIVE FAIL, Autopsia, Ingestión Polimórfica y Cierre Integral F5
- **Estado:** CLOSED / AUDITADA CON RIESGOS DOCUMENTADOS.
- **Hecho:** Ingestión polimórfica en `extension/injector.js`, resolución de precedencia `init.body` y orden causal de telemetría.
- **Resultado:** 244/244 tests aprobados en suites herméticas.

## SES-2026-10-20-03 — GoogleFlowMCP: puente implementado y robustez de transporte
- **Estado:** Implementación consolidada en main; LIVE TEST 1 preparado.
- **Hecho:** Implementación del cliente Stdio MCP, buffer de salida en bridge.js, selectores DOM con contingencia, purga de stale locks y sanitización de prompts.

## SES-2026-11-06-01 — INT-091 Selector de carpetas, Timeout 300 s y Render 4K
- **Estado:** CLOSED / PASS.
- **Hecho:** Implementación del selector nativo de carpetas de Windows vía `window.showDirectoryPicker()`, elevación de `FLOW_MCP_TIMEOUT` a 300 s, renderizado vertical 4K de prueba y desacoplamiento de NotebookLM en Connection Manager.
- **Referencia:** `SES-2026-11-06-01_CUSTOM_FOLDER_FLOW_TIMEOUT_4K_VALIDATION.md`.

## SES-2026-11-06-02 — Auditoría Técnica Integral P0-P3, Remediación y Sincronización
- **Estado:** CLOSED / PASS.
- **Hecho:** Remediación secuencial quirúrgica de los 17 puntos de la auditoría técnica (P0 a P3), rebase con `origin/main` (memoria viva `LEEME_PRIMERO.md`, `ROADMAP.md`, reubicación de lanzadores en `launchers/` y decisiones D-010/D-011) y sincronización con el repositorio remoto.
- **Resultado:** 40/40 tests PASS en suites de auditoría y suite de lanzadores.
- **Referencia:** `SES-2026-11-06-02_AUDITORIA_TECNICA_P0_P3_REMEDIACION_INTEGRAL.md`.

## SES-2026-11-14-01 — Conectividad Google Flow y NotebookLM + Descubrimiento en Vivo (Sonda INT-093)
- **Estado:** CLOSED / PASS.
- **Hecho:** Conexión real en vivo de Chrome CDP 9333, Google Flow (5 tools operativas verificadas con `flow_list_assets` en 1.6 s) y NotebookLM (32 tools). Solución al fallo `[LIST_EMPTY]` mediante migración a `notebook.google.com` y build label activo (`boq_labs-tailwind-frontend_20261112.11_p0`). Ejecución de la sonda INT-093 (`sonda_nombres.json` con `q3`, `q4`, `q5` SOPORTADO). Recuperación y fijación de 10 cuadernos reales en el panel web. Sincronización reactiva del semáforo en `app-mcp.js` (Ecosistema 4/4 verde).
- **Resultado:** 10 cuadernos listados en vivo; suites `test_notebooklm_base_url.py` (1/1), `test_u_panel_ecosistema.py` (21/21), `test_mcp_manager.py` (38/38) y `test_u1_mcp_resumen.py` (11/11) en verde.
- **Referencia:** `SES-2026-11-14-01_CONECTIVIDAD_GOOGLE_FLOW_NOTEBOOKLM_DESCUBRIMIENTO.md`.

## SES-2026-11-14-02 — Cierre BB1-BB4 y Sincronización Dual de Credenciales en NotebookLM MCP
- **Estado:** CLOSED / PASS.
- **Hecho:** Ejecución y cierre de mandatos BB1-BB4 (default `NOTEBOOKLM_CONTEXT_TOOL=notebook_query`, parsing seguro de `answer`, helper `_exposed_tools` preservando trinquete 286, 60 baterías en `ESTADO_REAL.md`, fallback e-commerce con `ImportError` explícito y `opencv-python-headless` en requirements). Identificación y remediación de la desincronización de credenciales entre `storage_state.json` y `~/.notebooklm-mcp/auth.json` mediante `_sync_auth_json()`. Verificación en vivo de los 7 cuadernos (con *FRUTINOVELAS* como `first_id`) y semáforo 4/4 verde (`todo_conectado: true`, `listo_para_pipeline: true`).
- **Resultado:** 811 passed, 1 skipped, 0 failed en pytest completo; 67 OK · 0 fallos en StartFrame F2; trinquete 286 intacto; ruff 0 hallazgos; compileall exit 0.
- **Referencia:** `SES-2026-11-14-02_SINCRONIZACION_DUAL_AUTH_JSON_Y_CIERRE_BB1_BB4.md`.

## SES-2026-11-14-03 — Diagnóstico Chrome/Flow/Gemini + Implementación BB5 (Pipeline Guards & Auth Sync)
- **Estado:** CLOSED / PASS.
- **Hecho:** Diagnóstico en profundidad de conectividad CDP, procesos Chrome 9333, Flow MCP y validez de `GEMINI_API_KEY` (A.a a A.e). Implementación de BB5: aborto de pipeline con código `BLUEPRINT_DEMO` si el motor es `local-demo` sin `PIPELINE_ALLOW_DEMO=1`, recorte de escenas opcional `max_scenes` (1-12) en `POST /api/pipeline/run` preservando la última escena de cierre, y validación y escritura atómica con `chmod 600` en `_sync_auth_json`. Creación de batería hermética `tests/test_bb5_pipeline_guards.py` (5 tests) e integración en `tests/run_all.py` (61 baterías canónicas). Actualización de `ESTADO_REAL.md` y `ROADMAP.md`.
- **Resultado:** 5/5 tests BB5 passed; trinquete 286 intacto; integridad documental 3/3 passed; verificación completa C en verde. Piloto Parte D saltado por no cumplirse precondición A(b) y A(e).
- **Referencia:** `SES-2026-11-14-03_BB5_PIPELINE_GUARDS_Y_DIAGNOSTICO_FLOW_GEMINI.md`.

## SES-2026-11-18-01 — Endurecimiento Definitivo de NotebookLM y Conectividad CDP Resiliente
- **Estado:** CLOSED / PASS.
- **Hecho:** Diagnóstico y remediación de la causa raíz de `[LIST_EMPTY]` (expiración de tokens CSRF `SNlM0e` / `FdrFJe` y build label desactualizado de Google). Implementación de parsing nativo `batchexecute`, extracción en vivo de tokens vía CDP 9333, inyección dinámica de `NOTEBOOKLM_BL`, sincronización atómica en `_sync_auth_json(..., tokens=...)` y fallback transparente con `_cdp_list_notebooks_direct`.
- **Resultado:** 7/7 tests en `test_bb5_pipeline_guards.py`; trinquete 286 intacto; 7 cuadernos reales listados en vivo con `FRUTINOVELAS` identificado.
- **Referencia:** `SES-2026-11-18-01_ENDURECIMIENTO_DEFINITIVO_NOTEBOOKLM_CDP.md`.

## SES-2026-11-19-01 — Contexto Local de Respaldo por Nicho y Experimento de Cookies
- **Estado:** CLOSED / PASS.
- **Hecho:** Experimento de cookies CDP sobre `notebook.google.com` (E-A..E-E: 24 cookies de host específico, GET httpx HTTP 200 sin redirección a accounts, conclusión sobre RPCs batchexecute). Implementación de contexto local de respaldo por nicho en `pipeline_orchestrator.py` con validación regex, rechazo de path traversal/symlinks, límite 64 KB, fallback automático ante auth error y modo `PIPELINE_CONTEXT_SOURCE=local`.
- **Resultado:** 5/5 tests PASS en `test_bc_contexto_local.py`; 62 baterías canónicas registradas en `run_all.py` y `ESTADO_REAL.md`; integridad documental y trinquete de excepciones verificados.
- **Referencia:** `SES-2026-11-19-01_CONTEXTO_LOCAL_RESPALDO_Y_EXPERIMENTO_COOKIES.md`.

## SES-2026-11-19-02 — Cadena de Fallback Gemini, Build Label en Vivo y Filtrado Específico de Cookies
- **Estado:** CLOSED / PASS.
- **Hecho:** Sondas S1-S5 identificando deprecación de `gemini-2.5-flash` por Google y compatibilidad con `gemini-3.8-flash`. Implementación de cadena dinámica de fallback `GEMINI_TEXT_MODEL_FALLBACKS` en `gemini_client` ante 404, derivación de build label en vivo desde el DOM/HTML de NotebookLM (`_live_bl`), y filtrado de cookies por especificidad de host descartando dominios ajenos.
- **Resultado:** 6/6 tests PASS en `test_bd_gemini_models_and_bl.py`; 63 baterías canónicas registradas en `run_all.py` y `ESTADO_REAL.md`; trinquete 286 intacto; integridad documental 3/3 en verde.
- **Referencia:** `SES-2026-11-19-02_GEMINI_MODEL_FALLBACK_Y_BUILD_LABEL_VIVO.md`.

## SES-2026-11-19-03 — Estabilidad Flow/CDP, Flags de Fondo, Calentamiento y Reintento Acotado (BE)
- **Estado:** CLOSED / PASS.
- **Hecho:** Diagnóstico de fallos por `connectOverCDP: Timeout 30000ms exceeded` debido al estrangulamiento de fondo en Chrome (CDP port 9333). Implementación de D1 (flags `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows`), D2 (calentamiento previo a Stage 3 con `flow_list_assets` hasta 2 intentos, abortando con `FLOW_CDP_SLOW`) y D3 (excepción acotada a regla AA1 permitiendo UN único reintento precedido de calentamiento ante `connectOverCDP: Timeout`).
- **Resultado:** 5/5 tests PASS en `test_be_flow_cdp_stability.py`; 64 baterías canónicas en `run_all.py` y `ESTADO_REAL.md`; trinquete 286 intacto.
- **Referencia:** `SES-2026-11-19-03_FLOW_CDP_ESTABILIDAD_Y_REINTENTO_ACOTADO.md`.

## SES-2026-11-20-01 — Estabilidad Flow CDP, Latencia Gemini (ThinkingConfig), Tests Windows y Suite Canónica
- **Estado:** CLOSED / PASS.
- **Hecho:** Reparación hermética de tests en Windows NTFS (bloqueos SQLite, filtros ffmpeg con letras de unidad, saltos CRLF vs LF, aislamiento de clientes LLM reales en tests herméticos). Implementación de D1 (`--disable-features` consolidado), D2 (keepalive en segundo plano durante etapas 0 a 2 cancelado en etapa 3), D3 (`ThinkingConfig(thinking_budget=0)` con 77.5% de mejora en latencia + logging con tiempo y tipo de error) y pruebas herméticas.
- **Resultado:** 2812 OK · 0 fallos en 66 baterías (`tests/run_all.py`), 865 passed en `pytest`, `compileall` y `ruff` 100% verde; trinquete 286 intacto.
- **Referencia:** `SES-2026-11-20-01_ESTABILIDAD_FLOW_CDP_LATENCIA_GEMINI_Y_SUITE_COMPLETA.md`.

## SES-2026-11-21-01 — Keepalive D2 cancelado en CUALQUIER salida + batería sobre `_run` real
- **Estado:** CLOSED / PASS (verificación completa). Piloto real NO ejecutado (Corresponde a Antigravity; regla D-007).
- **Hecho:** Corregida fuga de keepalive D2 en `pipeline_orchestrator.py::_run`: la tarea sobrevivía como huérfana si la corrida fallaba en etapa 1/2 o lanzaba excepción (solo se cancelaba en la transición a Stage 3). Cancelación ahora en el `finally` de `_run` (junto al single-flight `_busy`), loop extraído a `PipelineOrchestrator._flow_keepalive(run, interval, timeout)`. Batería `test_be_flow_cdp_stability.py` reescrita: los tests D2 keepalive ejecutan el `_run` REAL (create_run→start_run) con manager doble e intervalo 0.05 s y verifican con `asyncio.all_tasks()` que no sobrevive ninguna tarea tras (a) pings en etapas 0-2 con fallo en etapa 2 y (c) una corrida que llega a etapa 3 (sin pings dentro de ella). Anti-test vacuo verificado: sin el fix, (a+b) falla en `assert _surviving_keepalive_tasks() == []`.
- **Resultado:** compileall rc=0; ruff F821,E9,F63,F7,F82 verde; pytest COMPLETO 875 passed · 0 failed; run_all.py 66 baterías · 2847 OK · 0 fallos; trinquete 286 intacto (no subido).
- **Referencia:** `SES-2026-11-21-01_KEEPALIVE_ANY_EXIT_Y_BATERIA_RUN_REAL.md`.

