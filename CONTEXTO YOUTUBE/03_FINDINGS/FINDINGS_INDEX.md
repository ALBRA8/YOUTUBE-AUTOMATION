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

## F-010 — BM1/BM4 Verificados en Pipeline; Playwright connectOverCDP vulnerable a targets browser_ui
- **Estado:** VERIFIED EN PRUEBA REAL (2026-11-24).
- **Evidencia:** Corrida `run_20261124_171918_061b13` procesó el blueprint externo `claude` omitiendo Stage 2 LLM (`Blueprint EXTERNO claude: no generado por Gemini`), persistió `video_prompt` y `subtitle_text` en `blueprint.json` y los expuso fielmente en `/api/pipeline/status` (BM1/BM4 OK).
- **Límite/Hallazgo Técnico:** En Windows, cuando Chrome mantiene popups de omnibox (`chrome://omnibox-popup.top-chrome/`), `chromium.connectOverCDP` en Playwright intenta resolver todos los targets y sufre un cuelgue hasta agotar los 120 s configurados en `FLOW_CDP_CONNECT_TIMEOUT_MS`.
- **Referencia:** `08_SESSIONS/SES-2026-11-24-01_PRUEBA_ACEPTACION_REAL_BL_BM_Y_DIAGNOSTICO_CDP.md`.

## F-011 — Resolución de Bloqueo CDP y Generación Real de Vídeo en Google Flow Demostrada
- **Estado:** VERIFIED EN PRUEBA REAL E2E (2026-11-25).
- **Evidencia:** Purga selectiva de 11 procesos zombi de `FlowImageChrome` (PID raíz 11896) liberando el puerto 9333 sin tocar los 17 procesos del usuario. Re-arranque limpio vía `connect-all-google` conectando Playwright en 924 ms. Ejecución real de `flow_generate_video` con el ancla `personaje` (`id:02b5fa3d-179c-488a-b99b-64cc219a573e`), generada en Google Flow en 84 s y descargada a disco.
- **Validación Audiovisual:** MP4 generado (`2026-11-25T06-18-29-slow-zoom-in-on-the-red-apple-character-.mp4`), tamaño 1.28 MB (1,342,954 bytes), duración 8.01 s, resolución 720x1280 (9:16 vertical), códec de vídeo h264 a 24 fps, audio aac verificado con ffprobe.
- **Referencia:** `08_SESSIONS/SES-2026-11-25-01_RECUPERACION_FLOW_CDP_LIMPIEZA_Y_GENERACION_REAL.md`.


