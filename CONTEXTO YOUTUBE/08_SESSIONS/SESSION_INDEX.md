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

## SES-2026-10-20-03 — GoogleFlowMCP: puente implementado, LIVE pendiente
- **Estado:** implementación local reportada; LIVE TEST 1 bloqueado por preparación/autenticación del perfil dedicado.
- **Hecho:** Antigravity reportó 21/21 pruebas del puente, 55 OK del harness, 3/3 del paquete MCP y regresión F5.1 mock PASS.
- **Protecciones:** `FLOW_MCP_ENABLED=0` por defecto; no activar permanentemente, no alterar F5.1 ni la configuración MCP activa de Antigravity.
- **Pendiente:** preparar `FlowImageChrome`; si requiere login, el usuario lo realiza manualmente; después autorizar una única generación real.
- **Límite:** no se ha demostrado E2E LIVE ni Start Frame. Ver también `SES-2026-10-20-03_GOOGLEFLOWMCP_BRIDGE_IMPLEMENTATION.md`.
