# PROJECT STATE — YOUTUBE-AUTOMATION

**Estado:** IN_PROGRESS — Auditoría técnica del fix de ingestión polimórfica (Flow Script Processor 2.6.0).  
**Última actualización:** 2026-10-19.  
**Fuente:** Archivos del repo `harness-v1` y auditorías técnicas. Este snapshot no reemplaza tests ni convierte simulaciones en E2E real.

## Propósito y arquitectura
YOUTUBE-AUTOMATION es la especialización audiovisual de ALBRA. `ALBRA8/AGENTE-GENERAL` es el cuerpo central y mantiene infraestructura transversal; la lógica de producción audiovisual y Google Flow permanece en YOUTUBE-AUTOMATION. No se justifica rediseñar ni duplicar el bridge/orquestador.

## Referencias Git y Estado de Trabajo (2026-10-19)
- **Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`
- **Rama de trabajo reportada:** `harness-v1`
- **HEAD base reportado:** `85ab666bc283509c1617feabefc98aee3bac5ed4`
- **Parent reportado:** `8326f43ebd54f3a6fb41e4b74041422c44955eb8`
- **Extensión:** Flow Script Processor 2.6.0 (`extension/manifest.json`)
- **Estado del árbol de trabajo (verificado):** Modificaciones locales sin commit en:
  - `extension/injector.js`
  - `tests/flow_batchexecute_eb1hjf_mock.js`
  - `tests/test_flow_startframe_eb1hjf.py`
- AGENTE-GENERAL `main`: frontera arquitectónica preservada intacta; no se introduce lógica de Flow en AGENTE-GENERAL.

## Hito de auditoría completado en esta sesión
1. Leídos `CONTEXTO YOUTUBE/README.md`, `INDEX.md`, master docs y `ESTADO_REAL.md`.
2. Inspeccionados `injectScene(item)`, `__bridgeHandleJob(job, sendResult)`, `readStartFrame(sceneNumber)` en `extension/background.js` y la observabilidad de `extension/injector.js`.
3. El camino Flow de `injectScene` pasa el gate/consent cuando aplica, inyecta el prompt mediante `slateInjectFn`, verifica el resultado de UI y reporta `GENERATION_SUBMITTED`. No se encontró ahí selección o binding de imagen de entrada como Start Frame.
4. `readStartFrame` corresponde al proveedor Meta AI, no demuestra Start Frame en Google Flow.
5. El interceptor observa red/respuestas, pero el código revisado no demuestra captura estructurada del body de la solicitud real de generación ni cuál mediaId de entrada se envió.
6. No se ejecutó generación real en Chrome durante esta sesión. E2E con Flow sigue NOT_DEMONSTRATED.
7. Se inicializó la memoria documental CONTEXTO YOUTUBE con estado, arquitectura, glosario, decisiones, procesos, hallazgos, auditorías, pruebas reportadas, integraciones, fallos/riesgos, sesión y conocimiento.

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

## Evolución reciente: Parser Dual, LIVE FAIL y Fix de Ingestión Polimórfica (2026-10-19)
1. **Parser Dual eb1hJf/WuwhI (Commit 85ab666):** Se implementó el soporte posicional Protobuf real para `eb1hJf` y backward compatibility F1/F2. Superó auditoría pre-live con 224/224 tests reportados.
2. **LIVE Gate y LIVE FAIL:** Se generó un video real con Start Frame en Google Flow; sin embargo, `window.__FLOW_RPC_OBS__` emitió valores `null` en todos sus campos de telemetría.
3. **Autopsia de Red:** La causa raíz se identificó en el interceptor `window.fetch`: Google Flow invoca `fetch(Request)` sin segundo argumento `init`, dejando `rawBody` en `null` e impidiendo que el parser se ejecutara.
4. **Fix Local de Ingestión Polimórfica:** Se modificó `extension/injector.js` para leer instancias `Request` mediante clonación preventiva (`input.clone().text()`) sin alterar el objeto entregado a `originalFetch`, soportando duck-typing de `URLSearchParams`/`FormData` y protegiendo `ReadableStream` para jamás consumirlos destructivamente.
5. **Pruebas de Laboratorio:** 235/235 tests OK reportados (F1: 64, F2: 67, eb1hJf Dual: 49, Harness: 55).
6. **Estado de la Implementación:** `IMPLEMENTATION READY FOR REVIEW`. La validación LIVE permanece `LIVE NOT RUN — WAITING FOR REVIEW`.

## Puertas de Control Absolutas (GATES)
- **NO COMMIT:** Pendiente de auditoría y autorización explícita.
- **NO LIVE:** Prohibido ejecutar un nuevo LIVE Gate hasta aprobar formalmente el diff.
- **NO MERGE:** `main` permanece estrictamente separado.
- **NO CONSTRUCTOR:** Prohibido transferir código, prompts de implementación o tareas de integración al constructor.
- **NO BACKEND CHANGES:** Backend, contratos, bridge, colas, orquestador, HANDS y AGENTE-GENERAL quedan fuera del alcance.
- **PRESERVE WORKTREE:** Prohibido revertir o descartar las modificaciones locales existentes en el working tree.

## Cierre de Intervención F5 y Estado Final Consolidado (2026-10-20)
1. **Auditoría Dirigida F5:** Se identificaron dos casos de borde: precedencia defectuosa de `init.body` explícito cuando es `""` o `null`, y falta de garantía causal en el orden de microtareas entre `rpc_request` y `rpc_response`.
2. **Corrección Quirúrgica F5:**
   - Precedencia estricta implementada vía `hasExplicitBody = !!(init && typeof init === 'object' && 'body' in init && init.body !== undefined)`.
   - Orden causal garantizado mediante `onSettled(fn)` encadenado a `reqObsPromise`, manteniendo el despacho nativo inmediato.
   - Resiliencia ante fallos de lectura del stream del clon comprobada.
3. **Validación Consolidada:** 244/244 pruebas aprobadas al 100% (F1: 64, F2: 67, eb1hJf Dual+F5: 58, Harness: 55).
4. **Dictamen de Cierre F5:** `APROBADO CON RIESGOS DOCUMENTADOS` (confinado a VM/harness, listo para solicitud de autorización de LIVE Gate).

## Cierre de Fase de Preparación — GoogleFlowMCP (tools/GoogleFlowMCP) (2026-10-20)
1. **Instalación y Aislamiento:** Extraído e instalado en `tools/GoogleFlowMCP`. Dependencias deterministas (`npm ci`, 95 paquetes, 0 vulnerabilidades).
2. **Suite de Pruebas:** Script de test corregido a `node --test` para compatibilidad nativa Windows. Pruebas de concurrencia `npm test` aprobadas al 100% (3/3 pass).
3. **Validación de Protocolo:** Handshake MCP Stdio JSON-RPC 2.0 validado e introspección de 4 herramientas (`flow_upload_file`, `flow_list_assets`, `flow_generate_image`, `flow_new_project`).
4. **Seguridad y Rutas:** Perfil de navegación aislado en `%LOCALAPPDATA%\FlowImageChrome` (puerto CDP 9333 sin conflicto con backend ALBRA 8000), tolerancia a espacios en ruta verificada, y `.gitignore` comprobado.
5. **Estado:** Fase de preparación CERRADA y VERIFICADA. Servidor inactivo y desacoplado, pendiente de autorización para fase de activación.

## Implementación del Puente GoogleFlowMCP × YOUTUBE-AUTOMATION (2026-10-20)
1. **Cliente Stdio MCP:** Implementado `backend/services/flow_mcp_client.py` con handshake JSON-RPC 2.0 (`initialize` $\rightarrow$ `notifications/initialized` $\rightarrow$ `tools/call`), gestión de procesos y drenaje de buffers.
2. **Feature Flag Seguro:** Añadido `FLOW_MCP_ENABLED=0` por defecto en `backend/config.py`.
3. **Integración en Imágenes:** Añadido Plan 0 en `backend/pipeline/images.py` con validación rigurosa de binarios (cabeceras mágicas y tamaño mínimo) y preservación estricta de la cadena de fallbacks (Gemini -> z-ai -> extension -> placeholder).
4. **Batería de Pruebas:** Creada suite hermética `tests/test_flow_mcp_bridge.py` con **21/21 tests PASS** cubriendo timeouts, fallos de auth, archivos corruptos y preservación de F5.1.
5. **Estado:** PUENTE IMPLEMENTADO Y PROBADO. Desactivado por defecto (`FLOW_MCP_ENABLED=0`), listo para la fase de activación controlada.

## Puertas de Control Absolutas (GATES)
- **NO COMMIT / PUSH:** Pendiente de revisión formal del diff y autorización expresa.
- **NO PRODUCCIÓN:** `FLOW_MCP_ENABLED=0` por defecto; el pipeline regular permanece inalterado.
- **NO LIVE / NO LOGIN:** No abrir Chrome ni iniciar sesión en Google Flow sin autorización.
- **NO CONFIG CHANGE:** `mcp_config.json` de Antigravity conservado intacto.
- **NO MERGE:** `harness-v1` permanece estrictamente separada de `main`.

## Próximo hito
**ACTIVACIÓN CONTROLADA Y VALIDACIÓN CON NAVEGADOR DEL PUENTE GoogleFlowMCP.**
