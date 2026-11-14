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
