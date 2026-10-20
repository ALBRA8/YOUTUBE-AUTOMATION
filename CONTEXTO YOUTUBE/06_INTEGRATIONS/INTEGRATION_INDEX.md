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

## INT-006 — YOUTUBE-AUTOMATION ↔ GoogleFlowMCP
- **Estado:** PUENTE LOCAL IMPLEMENTADO / PRUEBAS AISLADAS REPORTADAS PASS / LIVE PENDIENTE.
- **Componentes reportados:** `backend/services/flow_mcp_client.py`, configuración en `backend/config.py`, integración condicional en `backend/pipeline/images.py`.
- **Seguridad operacional:** `FLOW_MCP_ENABLED=0` por defecto; si está desactivado o falla, el pipeline continúa por los proveedores de fallback existentes.
- **Preflight:** el perfil dedicado `FlowImageChrome` no existía; puede requerir login manual en una ventana aislada.
- **Validación pendiente:** generación real de una imagen a través del pipeline y MCP, verificación binaria y comprobación del fallback.
- **Límite de evidencia:** el informe local no demuestra que el código esté committeado/pusheado ni que la generación LIVE haya ocurrido.
