# ARCHITECTURE — YOUTUBE-AUTOMATION

**Estado:** arquitectura conceptual confirmada; ejecución externa real de Flow sigue IN_PROGRESS / NOT_DEMONSTRATED.  
**Revisión:** 2026-10-18.

## Principios
- AGENTE-GENERAL es el cuerpo central de ALBRA; YOUTUBE-AUTOMATION es la especialización audiovisual.
- Infraestructura transversal en el cuerpo central; lógica de producción/Google Flow en la especialización.
- P1 Golden Contract preserva el `video_prompt` creativo verbatim. P2 es adaptación operacional separada y condicionada por evidencia; no mutar P1 silenciosamente.
- Transportar datos, configurar UI, observar respuesta y demostrar efecto real son niveles de evidencia diferentes.
- Fail-closed: control requerido no verificable no debe convertirse en autorización.
- Código y tests del repo son fuente de verdad de implementación; memoria documental conserva decisiones, contexto y trazabilidad.

## Capas
1. Creative Engine / Production JSON: intención creativa y datos por escena.
2. Exportación/adaptación: convierte la especificación para ejecución sin alterar P1.
3. Backend/orquestador: ingestión, jobs, persistencia, QA, render y publicación.
4. Flow Bridge backend: SQLite `flow_jobs`, claim atómico, token, lease, heartbeat, retries, recuperación y endpoints.
5. Chrome extension: `bridge.js` reclama jobs; `background.js` administra cola, gate, inyección UI, polling y assets; `injector.js` observa tráfico de Flow.
6. HANDS: capa de ejecución física aislada con permisos, sesiones y evidencia auditables; conexión física/Flow real se marca no conectada/off según inventario/configuración.
7. QA/gobernanza: validación de assets, ffprobe/PIL, métricas, Doctor/preflight, skills, autonomía y publicación.
8. MemoryDV: memoria operativa de episodios/observaciones/patrones candidatos con promoción controlada; no modifica código/pipeline.
9. CONTEXTO YOUTUBE: memoria documental Markdown versionada; no asumir que es un vector DB.

## Diagrama
```text
AGENTE-GENERAL (identidad, coordinación, infraestructura transversal)
        │ A2A / Handoff / MCP
        ▼
YOUTUBE-AUTOMATION (dominio audiovisual)
 Creative Engine → Production JSON → export/execution_spec
 → backend jobs/leases → extension bridge → Chrome / Google Flow
 → assets → import/QA/render/publicación
```

## Camino Flow auditado
Para vídeos bridge con spec, `injectScene(item)` vuelve a ejecutar gate/consent. Después inyecta el prompt por `slateInjectFn`, verifica resultado de UI y reporta `GENERATION_SUBMITTED`. Esto prueba el paso de envío según el código, no que la imagen prevista esté ligada al request ni que Flow haya generado el resultado esperado.

`readStartFrame(sceneNumber)` se usa en la ruta Meta AI. No atribuirlo a Google Flow.

## Contratos y límites
- `references` transportadas no equivalen a referencias ejecutadas.
- En el contrato auditado `start_frame` y `end_frame` se construyen como `None`; no están en los controles verificables enumerados.
- `mediaIdToScene` asocia IDs de respuestas/resultados con escenas, no prueba el binding de entrada.
- El interceptor revisado no demuestra captura estructurada del body de request de generación ni el mediaId de entrada.
- HAR histórico: `WuwhI / MEDIA_GENERATION`, `videoModelKey=abra_i2v_6s`, `inputFrames.firstFrame.mediaId`. Variante observada: `startImage.mediaId`. Son observaciones de versiones/capturas, no esquema universal.

## Escala de evidencia
| Evidencia | Sí demuestra | No demuestra |
|---|---|---|
| Tests unitarios/mocks | comportamiento en alcance del test | proveedor Flow real |
| E2E mock / HTTP backend vivo | transporte y contratos de esa capa | Start Frame real |
| Prompt inyectado + Generate | UI recibió prompt y se envió acción según el código | binding de imagen |
| mediaId en respuesta | ID de un medio de salida/respuesta | que fuera imagen de entrada |
| HAR de ejecución real | payload observado en esa ejecución | protocolo universal futuro |
| imagen conocida + request + vídeo correlacionados | evidencia de binding en ese ejemplo | garantía universal sin pruebas adicionales |

## Frontera
No mover Flow a AGENTE-GENERAL ni crear otro bridge/orquestador. Identificar la capa exacta con evidencia y corregir mínimamente allí.
