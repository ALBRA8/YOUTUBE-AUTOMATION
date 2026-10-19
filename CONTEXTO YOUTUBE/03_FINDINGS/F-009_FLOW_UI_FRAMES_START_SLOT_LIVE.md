# F-009 — Google Flow UI real separa Fotogramas de Ingredientes y expone slot Iniciar

**Fecha:** 2026-10-18  
**Estado:** VERIFIED EN UI REAL / PAYLOAD AÚN PENDIENTE  
**Fuente:** captura manual en sesión real de Google Flow con extensión de observabilidad v2.5.0.

## Hallazgo

En la interfaz real de Flow, el selector de generación de vídeo muestra `Fotogramas` como modo separado de `Ingredientes`. Al activar `Fotogramas`, la UI presenta dos slots explícitos:

- `Iniciar`
- `Finalizar`

La imagen de prueba fue colocada en `Iniciar`, `Finalizar` permaneció vacío y la generación produjo un vídeo.

## Importancia

Esto elimina una ambigüedad importante de la investigación anterior: la UI real dispone de una ruta explícita de Start Frame que no debe confundirse con la ruta de `Ingredientes`/referencias.

## Límite de la evidencia

La UI no prueba por sí misma el contrato HTTP interno. La clasificación del protocolo requiere inspeccionar la observación `WuwhI` correspondiente a esta generación y demostrar la correlación con el `mediaId` de la imagen.

## Próximo criterio de PASS

PASS de evidencia para esta captura requiere encontrar en el registro real de generación, como mínimo:

- `operation: MEDIA_GENERATION`;
- modelo de vídeo correspondiente;
- un campo de Start Frame (`inputFrames.firstFrame.mediaId` y/o `firstFrame.mediaId` según el payload real);
- correlación del `mediaId` con la imagen seleccionada.

No universalizar nombres de campos: la captura histórica de Camino mostró `inputFrames.firstFrame.mediaId` y también se observaron variantes históricas con `startImage.mediaId`.
