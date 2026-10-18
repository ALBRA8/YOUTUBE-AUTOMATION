# PROJECT STATE — YOUTUBE-AUTOMATION

**Estado:** IN_PROGRESS — auditoría forense de ejecución real Google Flow / Start Frame.  
**Última actualización:** 2026-10-18.  
**Fuente:** archivos del repo `main` y contexto de auditoría disponible en esta sesión. Este snapshot no reemplaza tests ni convierte simulaciones en E2E real.

## Propósito y arquitectura
YOUTUBE-AUTOMATION es la especialización audiovisual de ALBRA. `ALBRA8/AGENTE-GENERAL` es el cuerpo central y mantiene infraestructura transversal; la lógica de producción audiovisual y Google Flow permanece en YOUTUBE-AUTOMATION. No se justifica rediseñar ni duplicar el bridge/orquestador.

## Referencias Git revisadas
- YOUTUBE-AUTOMATION `main` comparado con `f23ce558b1dffe5570199db48a9bda7909e4d956`: 4 commits por delante; la comparación devolvió solo cuatro archivos de documentación dentro de `CONTEXTO YOUTUBE/`, sin cambios de código en esa comparación.
- AGENTE-GENERAL `main` comparado con `9b28990df26d25f4137d9e8810637c0ac0df49ed`: idéntico en esa comparación.
- Revalidar HEADs antes de futuras modificaciones.

## Hito de auditoría completado en esta sesión
1. Leídos `CONTEXTO YOUTUBE/README.md`, `INDEX.md`, master docs y `ESTADO_REAL.md`.
2. Inspeccionados `injectScene(item)`, `__bridgeHandleJob(job, sendResult)`, `readStartFrame(sceneNumber)` en `extension/background.js` y la observabilidad de `extension/injector.js`.
3. El camino Flow de `injectScene` pasa el gate/consent cuando aplica, inyecta el prompt mediante `slateInjectFn`, verifica el resultado de UI y reporta `GENERATION_SUBMITTED`. No se encontró ahí selección o binding de imagen de entrada como Start Frame.
4. `readStartFrame` corresponde al proveedor Meta AI, no demuestra Start Frame en Google Flow.
5. El interceptor observa red/respuestas, pero el código revisado no demuestra captura estructurada del body de la request de generación ni cuál mediaId de entrada se envió.
6. No se ejecutó generación real en Chrome durante esta sesión. E2E con Flow sigue NOT_DEMONSTRATED.

## Estado del sistema
La base tiene infraestructura de Production JSON/P1, cola Flow Bridge con jobs/leases/heartbeat/retries, validación de assets, QA, métricas, Doctor/preflight, seguridad, MemoryDV, skills/autonomía y HANDS aislado según `ESTADO_REAL.md`. Los tests declarados allí prueban sus respectivos alcances; no equivalen a proveedor real.

## Gap crítico
- Execution Contract construye `start_frame: None` y `end_frame: None` en la implementación auditada.
- Start/End Frame no figuran entre los controles verificables enumerados.
- `references` transportadas no implican que Flow las use.
- `mediaIdToScene` registra resultados; no demuestra el binding de una imagen de entrada.
- El HAR histórico de Camino mostró `WuwhI / MEDIA_GENERATION`, `videoModelKey=abra_i2v_6s` y `inputFrames.firstFrame.mediaId`; se observaron variantes como `startImage.mediaId`. No universalizar ese campo.

## Plan inmediato
1. En Chrome con sesión habitual de Flow, DevTools → Network → Preserve log.
2. Ejecutar desde ALBRA una única generación con una imagen conocida.
3. Capturar request, payload relevante, respuesta y resultado; correlacionar job/scene, asset y mediaId.
4. Sanear cookies, tokens, credenciales, URLs firmadas y datos personales antes de compartir HAR o extractos.
5. Clasificar: A) imagen no cargada/seleccionada; B) cargada pero no vinculada; C) campo/protocolo incorrecto; D) binding correcto; E) rechazo/capability del proveedor.
6. Solo después diseñar prueba aislada, solución mínima, regresión y verificación real.
7. Actualizar `ESTADO_REAL.md` y esta memoria con evidencia y commit.

## Límites y reglas
- No implementar Start Frame antes de captura real.
- No mover lógica de Flow a AGENTE-GENERAL.
- No tocar P1, Creative Engine, Production JSON, leases/heartbeat ni HANDS núcleo sin evidencia causal.
- Prompt textual “Use the uploaded image…” no demuestra binding.
- No declarar E2E PASS por mocks, VM, DOM simulado, fixtures o HTTP backend.
- No decir “falló en ejecución real” sin captura: estado actual es NOT_DEMONSTRATED.

## Próximo hito
**FLOW START-FRAME EVIDENCE CAPTURED:** petición real correlacionada con imagen conocida y vídeo resultante, con secretos eliminados. Hasta entonces: BLOCKED / NOT_DEMONSTRATED.
