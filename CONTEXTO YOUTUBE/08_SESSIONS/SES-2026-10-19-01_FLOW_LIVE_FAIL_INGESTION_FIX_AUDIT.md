# SES-2026-10-19-01 — Google Flow Start Frame: LIVE FAIL, Autopsia e Ingestión Polimórfica

**Fecha:** 2026-10-19  
**Estado:** PENDING AUDIT / IMPLEMENTATION READY FOR REVIEW  
**Propósito:** Registrar documentalmente la ejecución del LIVE Gate (commit 85ab666), el fallo de observación resultante, la autopsia forense de red, la implementación local del fix de ingestión polimórfica en injector.js y las puertas de control vigentes.

---

## 1. Contexto Git y Referencias Técnicas

- **Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`
- **Rama de trabajo reportada:** `harness-v1`
- **HEAD base reportado:** `85ab666bc283509c1617feabefc98aee3bac5ed4`
- **Commit padre reportado:** `8326f43ebd54f3a6fb41e4b74041422c44955eb8`
- **Extensión:** Flow Script Processor 2.6.0 (`extension/manifest.json`)
- **Estado del árbol de trabajo (reportado y verificado):** Modificaciones locales sin staging ni commit (`Changes not staged for commit`).

### Archivos modificados en el árbol de trabajo (reportados):
1. `extension/injector.js` (implementación de ingestión polimórfica no destructiva)
2. `tests/flow_batchexecute_eb1hjf_mock.js` (arnés VM con pruebas de Request, URLSearchParams, Duck-typing y Streams)
3. `tests/test_flow_startframe_eb1hjf.py` (batería de validación y límites de repositorio)

---

## 2. Historial de la Incidencia: Del Parser Dual al LIVE FAIL

1. **Implementación del Parser Dual (Commit 85ab666):**
   - Se diseñó el soporte pasivo para el RPC `eb1hJf` (Protobuf posicional real de Google Flow) y compatibilidad con `WuwhI` (F1/F2).
   - Las pruebas de laboratorio pasaron con 224/224 OK reportados.
   - La auditoría PRE-LIVE autorizó el avance al LIVE Gate.

2. **Ejecución del LIVE Gate en Google Flow:**
   - **Resultado en UI:** El video se renderizó y completó exitosamente con Start Frame enlazado en la interfaz real de Google Flow.
   - **Resultado en Observabilidad (`window.__FLOW_RPC_OBS__`):** **LIVE FAIL**. El observador emitió `videoModelKey: null`, `startFrame: null`, `ids: {}`, `operation: null`.
   - **Tráfico Real de Red Interceptado:**
     - `WuwhI` (vinculación de ingredientes / telemetría): ts `1792464488597`
     - `eb1hJf` (mutación de render y grafo de tareas): ts `1792464493895`
     - Polling de estado `jwpduf` / `as29s`: completado en estado `DONE`.

3. **Autopsia Forense de Red y Causa Raíz:**
   - La inspección del tráfico demostró que Google Flow (frontend compilado con Angular y Closure) invoca `window.fetch` pasando una instancia de `Request` como primer argumento: `fetch(new Request(url, { ... }))`, sin proveer el segundo argumento `init`.
   - El interceptor anterior evaluaba: `const rawBody = init ? init.body : null;`, recibiendo `null`.
   - La cadena de fallo confirmada fue:
     `Google Flow → window.fetch(Request) → init.body (null) → rpcBodyText(null) → parseFreqEntries([]) → payload null → parser posicional NUNCA ejecutado`.

4. **Implementación Local del Fix de Ingestión Polimórfica:**
   - Se implementó en `extension/injector.js` una estrategia de lectura no destructiva:
     - Detección de objetos `Request` vía `isRequest(input)`.
     - Si no hay `init.body`, se clona preventivamente el Request con `input.clone()` y se lee asíncronamente con `.text()`.
     - El objeto `input` original se pasa intacto (`bodyUsed === false`) a `originalFetch.apply(this, arguments)`.
     - Detección duck-typed cross-realm para `URLSearchParams`, `FormData` y contenedores Closure/Angular (`QueryData` / `HttpParams`).
     - Aislamiento defensivo de `ReadableStream` (`typeof body.getReader === 'function'`): nunca se consumen, retornando `null` de forma segura.
     - Extracción de payloads en `parseFreqEntries` con soporte para percent-encoding (`%5B`).

5. **Pruebas de Laboratorio Reportadas (235/235 OK):**
   - F1 (`tests/test_flow_batchexecute.py`): 64/64 PASS.
   - F2 (`tests/test_flow_startframe_fase2.py`): 67/67 PASS.
   - Dual/Post-Autopsia (`tests/test_flow_startframe_eb1hjf.py`): 49/49 PASS (incluyendo 11 checks para Request, URLSearchParams, Duck-typing y Streams).
   - YouTube Harness (`tests/test_harness.py`): 55/55 PASS.

---

## 3. Estado de la Implementación y Jerarquía de Evidencia

- **Declaración del implementador:** `IMPLEMENTATION READY FOR REVIEW`.
  *(Nota de rigor: Esta declaración indica que el implementador considera el fix listo para revisión; no constituye certificación independiente ni validación LIVE).*
- **Fase en curso:** `AUDITORÍA TÉCNICA DEL DIFF COMPLETO`.
- **Estado de validación LIVE:** `LIVE NOT RUN — WAITING FOR REVIEW`. La implementación **NO** ha sido probada aún en un nuevo LIVE real de Google Flow.

---

## 4. Puertas de Control Absolutas (GATES)

Quedan expresamente vigentes las siguientes restricciones:

- **NO COMMIT:** Prohibido crear commits hasta completar la auditoría técnica y recibir autorización explícita.
- **NO LIVE:** Prohibido ejecutar LIVE gates en Google Flow hasta aprobar formalmente el diff.
- **NO MERGE:** La rama `harness-v1` permanece estrictamente separada de `main`.
- **NO CONSTRUCTOR:** Prohibido transferir código, prompts de implementación o tareas de integración al constructor.
- **NO BACKEND CHANGES:** Prohibido modificar backend, contratos, bridge, colas, orquestador, HANDS o AGENTE-GENERAL.
- **NO REVERT / PRESERVE WORKTREE:** Prohibido descartar o revertir las modificaciones locales existentes en el working tree.

---

## 5. Siguiente Acción Autorizada

La única acción autorizada es la finalización de la auditoría técnica del diff completo con foco en:
- Semántica de `fetch(url, init)` vs `fetch(Request)` y prioridad de `init.body`.
- No-destructividad de `Request.clone().text()`.
- Protección contra consumo de `ReadableStream`.
- Cero fugas de Media IDs crudos y credenciales.
- Dictamen formal de auditoría.


---

## 6. Intervención Complementaria F5: Precedencia Estricta y Orden Causal

1. **Defectos Detectados en Auditoría Dirigida:**
   - Precedencia de `init.body`: El uso previo de `if (rawBody)` hacía que valores explícitos como `{ body: "" }` o `{ body: null }` evaluaran a falsy y cayeran en `else if (isRequest(input))`, leyendo erróneamente el cuerpo del `Request` superseded.
   - Orden de telemetría: La lectura asíncrona de `clone.text()` y el despacho de `originalFetch` no estaban coordinados, permitiendo que respuestas ultra-rápidas (mocks, caché) emitieran `rpc_response` antes que `rpc_request`.

2. **Resolución Quirúrgica Implementada:**
   - Precedencia: Se incorporó `hasExplicitBody = !!(init && typeof init === 'object' && 'body' in init && init.body !== undefined)`. Si es `""` o `null`, se emite observación nula segura sin inspeccionar el `Request`.
   - Orden Causal: Se encadenó `captureResponse` detrás de `reqObsPromise.then(fn).catch(fn)` mediante `onSettled(fn)`. El despacho nativo de `originalFetch` se mantuvo inmediato, y la captura de respuesta ahora espera deterministamente a que la observación del request haya finalizado.
   - Resiliencia: Errores en la lectura del clon no bloquean la llamada nativa y preservan el orden causal emitiendo el fallback seguro.

3. **Pruebas F5 Agregadas en el Arnés VM:**
   - `test_f5_case1_empty_string_override`: PASS.
   - `test_f5_case2_null_body_override`: PASS.
   - `test_f5_case3_empty_init_preserves_request`: PASS.
   - `test_f5_case4_undefined_body_preserves_request`: PASS.
   - `test_f5_case5_url_empty_body`: PASS.
   - `test_f5_causal_telemetry_ordering`: PASS (orden causal garantizado frente a `Promise.resolve`).
   - `test_f5_clone_error_resilience`: PASS (error de lectura no altera el resultado nativo).

4. **Resultados Finales Consolidados (244/244 OK):**
   - F1 (`test_flow_batchexecute.py`): 64/64 PASS.
   - F2 (`test_flow_startframe_fase2.py`): 67/67 PASS.
   - Dual/Post-Autopsia + F5 (`test_flow_startframe_eb1hjf.py`): 58/58 PASS.
   - YouTube Harness (`test_harness.py`): 55/55 PASS.
   - Total: 244/244 pruebas aprobadas (100% OK).

5. **Dictamen de la Intervención F5:** `APROBADO CON RIESGOS DOCUMENTADOS`.

---

## 7. Ejecución LIVE Gate F5 y Ajuste Quirúrgico de Punteros Posicionales (F5.1)

1. **Evidencia Capturada en Vivo:**
   - La prueba manual con Start Frame en Google Flow confirmó la detección de `eb1hJf` con orden causal estricto ($\Delta \approx 4605\text{ ms}$).
   - La captura directa de la pestaña Network decodificó el payload nativo exacto:
     ```text
     innerData = JSON.parse(req[0][0][1])
     block = innerData[0][0]
     Prompt: block[0][2][0][0] -> "la mujer esta tomando cafe "
     videoModelKey: block[1] -> "abra_i2v_10s"
     Operación/Aspect: block[2] -> 1 (MEDIA_GENERATION / 1:1)
     Start Frame mediaId: block[4][1] -> "433d7c19-a8e5-402e-bdf0-1f53970a35c4"
     cropCoordinates: block[4][5] -> [0.10081230055120394, null, 0.8991876994487961, 1]
     ```

2. **Causa Raíz de Ingestión Nula en Producción:**
   - En Google Flow en producción, Google Closure minifica los nombres de constructores de parámetros (`QueryData` pasa a ser una clase ofuscada como `a` o `b`), haciendo que el regex de constructor fallara y `rpcBodyText` retornara `null`.
   - Adicionalmente, peticiones enviadas con `ArrayBuffer` o `Uint8Array` no contaban con decodificación sincrónica mediante `TextDecoder`.
   - Si existía percent-encoding parcial, `decodeURIComponent` podía arrojar `URIError` y abortar el parseo de `f.req`.

3. **Corrección Implementada en injector.js:**
   - `safeDecodeUriComponent`: Decodificador tolerante a fallos de escape `%XX`.
   - `rpcBodyText`: Soporte para `ArrayBuffer` / `Uint8Array` (`TextDecoder`) e inspección no destructiva de cualquier objeto con `.toString()` que contenga `f.req=`, `[` o `%5B`.
   - `parseFreqEntries`: Extracción robusta de `f.req` y parseo recursivo multicapa.
   - `resolvePositionalSpec`: Puntero posicional directo a `innerData[0][0]` (`block[1]`, `block[2]`, `block[4][1]`, `block[4][5]`, `block[0][2][0][0]`), manteniendo DFS como respaldo defensivo.

4. **Resultados de Validación Consolidada (254/254 OK):**
   - F1 (`test_flow_batchexecute.py`): 64/64 PASS.
   - F2 (`test_flow_startframe_fase2.py`): 67/67 PASS.
   - eb1hJf + Live Payload (`test_flow_startframe_eb1hjf.py`): 68/68 PASS (incluyendo 10 comprobaciones H4 con el payload real de Flow).
   - YouTube Harness (`test_harness.py`): 55/55 PASS.
   - Total: 254/254 pruebas aprobadas (100% OK).
