# INTEGRATION INDEX

## INT-001 — AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION
- **Estado:** frontera arquitectónica vigente.
- **Cuerpo central:** identidad, coordinación e infraestructura transversal.
- **Especialización:** producción audiovisual, Flow Bridge, QA, publicación.
- **Regla:** no duplicar infraestructura ni mover Google Flow al cuerpo central.

## INT-002 — Backend Flow Bridge ↔ Chrome extension
- **Estado:** código/tests reportados como reales dentro de sus alcances.
- **Componentes:** jobs SQLite, claim/lease/heartbeat/retry, endpoints `/api/extension/flow/jobs*`, `extension/bridge.js` y wiring en `background.js`.
- **Límite:** mocks/HTTP no prueban binding visual de Flow.

## INT-003 — Chrome extension ↔ Google Flow
- **Estado:** PARTIAL / REAL EXECUTION NOT DEMONSTRATED.
- **Observado:** inyección UI de prompt, reporte de envío, polling/descarga y observabilidad de respuestas/notificaciones.
- **No demostrado:** carga/selección de imagen correcta y binding de su mediaId en request de vídeo.
- **Próximo:** captura de red real desde ALBRA.

## INT-004 — Start Frame Meta AI
- **Estado:** existe `readStartFrame` y `injectMetaScene`.
- **Límite:** proveedor/camino separado; no extrapolar a Google Flow.

## INT-005 — HANDS / Flow Operator
- **Estado:** HANDS estructuralmente implementado según inventario; conexión física/Flow real marcada OFF/NOT CONNECTED según configuración.

## INT-006 — GoogleFlowMCP (Browser Automation vía Playwright/CDP)
- **Estado:** FASE DE PREPARACIÓN CERRADA Y VERIFICADA (No conectado a producción).
- **Ubicación:** `tools/GoogleFlowMCP`
- **Mecanismo:** MCP Server stdio + Playwright-core conectándose a Chrome dedicado vía CDP (puerto 9333).
- **Herramientas expuestas:** `flow_generate_image`, `flow_upload_file`, `flow_list_assets`, `flow_new_project` (introspección JSON-RPC 2.0 verificada).
- **Pruebas de suite:** `npm test` (`node --test`) 3/3 PASS (concurrencia, recuperación y liberación de lock).
- **Frontera de seguridad:** Perfil aislado en `%LOCALAPPDATA%\FlowImageChrome`, `.gitignore` local blindando `config.json`, `state.json`, `.flow.lock` y medios locales. Servidor inactivo hasta autorización de activación.

