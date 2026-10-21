# FINDINGS INDEX

## F-001 — Execution Contract no define Start Frame verificable
- **Estado:** VERIFIED por inspección estática.
- **Evidencia:** `start_frame` y `end_frame` se construyen como `None`; no figuran entre los controles verificables enumerados.
- **Impacto:** no se garantiza contractualmente la imagen de entrada prevista.

## F-002 — readStartFrame pertenece a Meta AI
- **Estado:** VERIFIED por inspección de `extension/background.js`.
- **Impacto:** no contar esta función como implementación de Google Flow.

## F-003 — Camino Flow inyecta prompt y envía Generate
- **Estado:** VERIFIED por código de `injectScene(item)`: llama `slateInjectFn`, verifica `res.ok` y reporta `GENERATION_SUBMITTED`.
- **Límite:** esto no demuestra selección/binding de imagen.

## F-004 — mediaIdToScene es tracking de resultados
- **Estado:** VERIFIED según auditoría del response handler.
- **Límite:** no prueba dirección escena → imagen de entrada → petición de vídeo.

## F-005 — Interceptor no demuestra el body del request de generación
- **Estado:** VERIFIED para el código revisado; no se encontró captura estructurada del body que identifique mediaId de input.

## F-006 — HAR histórico de Camino muestra Start Frame estructural
- **Estado:** OBSERVED, no universal.
- **Observación:** `WuwhI / MEDIA_GENERATION`, `generation_type=video`, `videoModelKey=abra_i2v_6s`, `inputFrames.firstFrame.mediaId`; cadena posterior descrita `jwpduf → as29s → flow-content.google/video/<UUID>`.
- **Precaución:** otra variante observada usa `startImage.mediaId`. Capturar la versión actual.

## F-007 — E2E real Google Flow no demostrado
- **Estado:** NOT_DEMONSTRATED en `ESTADO_REAL.md`.
- **Próximo paso:** generación controlada desde ALBRA y captura real.

## F-008 — CONTEXTO YOUTUBE estaba vacío/incompleto
- **Estado:** VERIFIED al revisar plantillas y 404 de índices anunciados.
- **Acción:** poblar memoria documental con trazabilidad y estados honestos.

## F-009 — Google Flow UI real separa Fotogramas de Ingredientes y expone slot Iniciar
- **Estado:** VERIFIED EN UI REAL; payload pendiente.
- **Evidencia:** sesión manual real del 2026-10-18 con extensión v2.5.0. Al seleccionar `Fotogramas`, Flow mostró `Iniciar` y `Finalizar`; la imagen conocida se colocó en `Iniciar` y la generación produjo un vídeo.
- **Límite:** todavía no se ha leído de forma concluyente el `WuwhI` de esta generación para demostrar el `mediaId` de Start Frame.
- **Referencia:** `08_SESSIONS/SES-2026-10-18-02_GOOGLE_FLOW_START_FRAME_LIVE_CAPTURE.md`.
