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

## INT-006 — GoogleFlowMCP (Browser Automation vía Playwright/CDP y Puente Local)
- **Estado:** PUENTE LOCAL IMPLEMENTADO / PRUEBAS AISLADAS PASS / LIVE TEST 1 PASS.
- **Ubicación:** 	ools/GoogleFlowMCP
- **Componentes:** ackend/services/flow_mcp_client.py, ackend/config.py, ackend/pipeline/images.py.
- **Mecanismo:** MCP Server stdio JSON-RPC 2.0 + Playwright-core conectándose a Chrome dedicado vía CDP (puerto 9333).
- **Herramientas expuestas:** low_generate_image, low_upload_file, low_list_assets, low_new_project.
- **Seguridad operacional:** FLOW_MCP_ENABLED=0 por defecto; degradación limpia a fallback ante cualquier error.

## INT-007 — Reference / Asset Lineage & Scene Asset Resolver (Gate B / B.2 / B.2R)
- **Estado:** IMPLEMENTADO / PRUEBAS UNITARIAS Y REGRESIÓN PASS / LIVE TEST 2R PASS.
- **Componentes:** ackend/pipeline/asset_resolver.py, ackend/pipeline/images.py, 	ools/GoogleFlowMCP/src/flow.js.
- **Mecanismo:** Resolución determinista de referencias de escena (scene.references / meta.production_unit.references) → subida vía upload_file() → desambiguación y fix de rename en Google Flow → inyección de @mention → consumo interactivo (mention-chip) en ProseMirror → generación real en Flow.
- **Dictamen:** REFERENCE CONSUMPTION PASS.
