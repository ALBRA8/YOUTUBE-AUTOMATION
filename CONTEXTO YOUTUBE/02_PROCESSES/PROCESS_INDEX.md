# PROCESS INDEX

## PROC-001 — Auditoría AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION
- **Estado:** VERIFIED para la conclusión arquitectónica.
- **Conclusión:** cuerpo central para infraestructura común; especialización para dominio audiovisual.
- **Regla:** revalidar HEADs antes de modificar código.

## PROC-002 — Auditoría estática de Start Frame
- **Estado:** completada para el código inspeccionado; E2E sigue NOT_DEMONSTRATED.
- **Método:** revisar Execution Contract, export, background.js, injector.js, jobs, estado real y HAR histórico.
- **Conclusión:** no está demostrado el binding de imagen de entrada al request de vídeo.

## PROC-003 — Captura forense real de Flow
- **Estado:** PLANNED / BLOCKED hasta ejecutar Chrome real.
- **Pasos:** imagen conocida; DevTools Network + Preserve log; iniciar un solo vídeo desde ALBRA; guardar requests relevantes; sanear secretos; correlacionar job/escena, upload/asset, mediaId, request, respuesta y vídeo.
- **Seguridad:** no compartir HAR crudo; eliminar cookies, tokens, credenciales, URLs firmadas y datos personales.

## PROC-004 — Corrección mínima basada en evidencia
- **Estado:** PLANNED; no iniciar antes de PROC-003.
- **Pasos:** hipótesis + criterio de aceptación; prueba aislada; cambio mínimo; regresión; tests pertinentes; actualizar ESTADO_REAL y memoria; prueba E2E real.

- **Runbook operativo:** [`PROC-003_GOOGLE_FLOW_START_FRAME_CAPTURE.md`](./PROC-003_GOOGLE_FLOW_START_FRAME_CAPTURE.md) — captura real, correlación de mediaId y saneamiento de evidencia.
