# SES-2026-10-18-02 — Google Flow Start Frame: captura manual en vivo

**Fecha:** 2026-10-18  
**Estado:** IN_PROGRESS / CAPTURA PARCIALMENTE COMPLETADA  
**Propósito:** documentar la prueba manual realizada en Google Flow después de instrumentar la extensión para observar `batchexecute`.

## Contexto técnico

La extensión de `YOUTUBE-AUTOMATION` fue instrumentada en el commit `2d0a99b85fa8c7f224b5c8660708411b1617e32a` (branch local reportada `harness-v1`) para observabilidad pasiva de `batchexecute`.

Cambios reportados en esa fase:
- `extension/injector.js`: observación de requests/responses de `batchexecute`, incluyendo `WuwhI`, `eb1hJf`, `jwpduf` y `as29s`.
- `extension/content.js`: forwarding de `FLOW_RPC_EVIDENCE`.
- `extension/background.js`: ring de observaciones `rpcObservations`, snapshot y reset.
- `extension/manifest.json`: versión 2.5.0.
- Tests de harness: 15/15; F1: 64/64; regresión reportada: 44 baterías / 2062 OK.
- El cambio fue deliberadamente pasivo: no modifica el flujo de generación ni el contrato P1/P2.

## Prueba manual en Google Flow

Se utilizó una sesión real de Google Flow en Chrome con DevTools abierto y la extensión v2.5.0 activa.

### Preparación

1. Se abrió un proyecto real de Flow.
2. Se comprobó en consola que `window.__FLOW_RPC_OBS__` existe y devuelve observaciones.
3. Se realizó previamente una generación sin Start Frame. Esa generación solo sirve como control de observabilidad y **no es evidencia de Start Frame**.
4. En el selector de configuración se observó la interfaz en español con las opciones `Imagen`, `Video`, `Fotogramas` e `Ingredientes`.
5. Al seleccionar `Fotogramas`, la interfaz mostró dos posiciones: `Iniciar` y `Finalizar`.
6. La imagen de prueba de una mujer fue colocada en `Iniciar` y `Finalizar` quedó vacío.
7. El prompt utilizado fue, en esencia, una instrucción para que la mujer de la imagen estuviera sentada en una cafetería, mirando a cámara y levantando lentamente una taza, manteniendo apariencia y rostro de referencia.

### Evidencia visual observada

La interfaz posterior a cerrar el panel mostró claramente:

`[imagen]  ↔  [Finalizar]`

con la imagen ocupando la posición de inicio. Esto es evidencia de que el usuario seleccionó el modo de **Fotogramas** y colocó la imagen en el slot de inicio de la UI. No prueba por sí sola qué payload interno envió Flow.

### Resultado

La generación produjo un vídeo correctamente en Flow.

Después de la generación, la consola mostró múltiples observaciones `WuwhI`, `jwpduf` y `as29s`. Se confirmó que `window.__FLOW_RPC_OBS__` contiene 4 observaciones `WuwhI` en el momento de la inspección:

```js
window.__FLOW_RPC_OBS__.filter(x => x.rpcid === "WuwhI")
```

resultado observado: `Array(4)`.

También se ejecutó:

```js
console.table(window.__FLOW_RPC_OBS__.filter(x => x.rpcid === "WuwhI"))
```

La tabla confirmó cuatro registros, pero la visualización compacta de DevTools ocultó parte de los campos. Por ello **todavía no se ha clasificado el payload de la generación como Start Frame PROVEN mediante esta captura**.

## Estado de evidencia

### PROBADO EN ESTA SESIÓN
- La UI real de Flow tiene un modo `Fotogramas` separado de `Ingredientes`.
- El modo `Fotogramas` expone un slot `Iniciar` y otro `Finalizar`.
- La imagen conocida fue colocada en `Iniciar`.
- La generación produjo un vídeo.
- La instrumentación de ALBRA observa tráfico real `batchexecute` en la sesión.
- `window.__FLOW_RPC_OBS__` contiene observaciones reales `WuwhI`.

### TODAVÍA NO PROBADO
- Que el `WuwhI` correspondiente a esta generación contenga `operation: MEDIA_GENERATION`.
- Que el request real contenga `videoModelKey: abra_i2v_6s`.
- Que el request real contenga `inputFrames.firstFrame.mediaId` y/o `firstFrame.mediaId` correspondiente a la imagen seleccionada.
- Que el `mediaId` observado se pueda correlacionar inequívocamente con la imagen conocida y con el vídeo resultante.
- Que el comportamiento sea idéntico para todas las variantes/modelos/versiones de Flow.

## Siguiente inspección exacta

No generar otro vídeo. Inspeccionar únicamente las observaciones ya almacenadas:

```js
window.__FLOW_RPC_OBS__
  .filter(x => x.rpcid === "WuwhI")
  .map((x,i) => ({
    n: i,
    operation: x.operation,
    videoModelKey: x.videoModelKey,
    aspectRatio: x.aspectRatio,
    count: x.count,
    startFrame: x.startFrame,
    ids: x.ids
  }))
```

Ese resultado debe utilizarse para clasificar la captura. No se debe asumir que el registro con `WuwhI` es automáticamente la generación: hay llamadas de estado/carga con `operation`, `videoModelKey`, `aspectRatio`, `count` y `startFrame` nulos.

## Reglas de seguridad

No almacenar cookies, tokens, `SAPISIDHASH`, `f.sid`, CSRF, reCAPTCHA, URLs firmadas ni credenciales. Cualquier HAR o extracto compartido debe estar sanitizado.

## Decisión arquitectónica provisional

La evidencia de esta sesión refuerza la estrategia **Híbrida Asimétrica**:

- la UI/sesión real de Flow realiza la selección de `Fotogramas → Iniciar`;
- Flow maneja internamente autenticación, reCAPTCHA, registro de proyecto y generación;
- la extensión observa pasivamente el protocolo real;
- el backend solo debe persistir/transportar evidencia y `flow_media_id` cuando el protocolo esté demostrado.

No se autoriza todavía una reimplementación backend de `batchexecute` ni cambios de ejecución Start Frame.
