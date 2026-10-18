# PROC-003 RUNBOOK — CAPTURA REAL GOOGLE FLOW START FRAME

**Estado:** READY_FOR_OPERATOR — requiere una sesión real de Chrome autenticada por el usuario.  
**Objetivo:** demostrar qué imagen de entrada recibe Google Flow en una generación de vídeo iniciada desde ALBRA.  
**No objetivo:** inferir el protocolo por el DOM, hardcodear un campo a partir de un HAR antiguo o modificar código antes de reunir evidencia.

## Reglas de seguridad
- No compartas contraseñas, cookies, cabeceras `Authorization`, tokens, API keys ni archivos HAR sin sanear.
- Las URLs de medios pueden contener firmas temporales. Elimina query strings sensibles antes de compartir.
- No uses automatización contra endpoints privados ni reproduzcas manualmente requests autenticadas fuera de la sesión normal del navegador.
- Haz una única generación de prueba y evita incluir datos personales en el prompt o en el nombre del proyecto.

## Preparación
1. Abre Chrome con la sesión de Google Flow que normalmente utiliza ALBRA.
2. Abre DevTools → **Network**.
3. Activa **Preserve log** y **Disable cache**. Selecciona **All** y limpia el registro antes de empezar.
4. Mantén a la vista la pestaña de Flow y confirma que la extensión ALBRA y su bridge están en el estado operativo esperado.
5. Usa una imagen de prueba no sensible, reconocible y única. Anota localmente su nombre/hash, escena y job/proyecto de ALBRA; no publiques datos privados.

## Ejecución controlada
1. Inicia exactamente una generación de vídeo desde el camino habitual de ALBRA con esa imagen como Start Frame previsto.
2. No recargues ni navegues fuera de Flow durante la generación.
3. En Network, localiza las peticiones que coincidan temporalmente con la generación. Revisa las peticiones de generación de vídeo y, si existen, las peticiones previas de upload/registro de medios.
4. En cada request relevante, inspecciona **Headers**, **Payload** y **Response**. Anota localmente:
   - hora aproximada y método;
   - ruta/operación sin query string ni secretos;
   - estructura del body que identifica la generación;
   - campo exacto del identificador de imagen de entrada, si aparece;
   - identificador de tarea/lote/workflow y respuesta relacionada;
   - evidencia de que el ID de entrada corresponde a la imagen de prueba;
   - identificador/URL final del vídeo, con query strings eliminadas.
5. Deja que Flow termine o registre un error. Anota si el vídeo resultante corresponde a la escena esperada.

## Qué buscar (pistas, no contrato)
Un HAR histórico mostró `inputFrames.firstFrame.mediaId`; otra variante observada usaba `startImage.mediaId`. **Ninguna de esas formas se debe asumir válida para la sesión actual**. Busca la estructura real en el payload observado y conserva el nombre del campo exactamente como apareció.

## Correlación mínima exigida
La evidencia solo se considera suficiente cuando permite relacionar:
`proyecto/job ALBRA → escena → imagen elegida → mediaId de entrada → request de generación → respuesta/tarea → vídeo final`.

Si falta el request body o no se puede relacionar el mediaId con la imagen conocida, marca el resultado como **INCONCLUSIVE**, no como fallo del proveedor ni como Start Frame probado.

## Entrega segura de evidencia
Preferencia:
1. Comparte una transcripción textual del request relevante con valores secretos eliminados.
2. Incluye el fragmento del payload que contiene el campo de imagen y los IDs de correlación, reemplazando IDs sensibles por etiquetas consistentes como `MEDIA_INPUT_A`, `JOB_A`.
3. Incluye la respuesta relevante con tokens, URLs firmadas y datos personales eliminados.

Si necesitas compartir un HAR, sanitízalo primero en local. Elimina `Cookie`, `Set-Cookie`, `Authorization`, tokens, credenciales, parámetros de URL firmados y cualquier dato personal; verifica el archivo resultante manualmente antes de adjuntarlo. No compartas el HAR original.

## Criterio de decisión posterior
- **Input mediaId visible y correlacionado:** comparar su forma exacta con el contrato/código y diseñar una prueba de regresión.
- **Request de generación visible pero sin imagen de entrada:** investigar cómo se selecciona/sube/bindea la imagen; no asumir que `references` basta.
- **No aparece request identificable:** revisar filtros/endpoint actual en DevTools; no concluir que Flow no soporta Start Frame.
- **Error del proveedor:** clasificarlo con status/body saneado y correlación temporal; no atribuirlo a Start Frame sin evidencia causal.

## Salida del procedimiento
Registrar resultado como **PROVEN**, **DISPROVEN** o **INCONCLUSIVE**, con evidencia adjunta saneada, versión/commit de la extensión utilizada y los cambios exactos del entorno. Después actualizar `ESTADO_REAL.md` y la memoria `CONTEXTO YOUTUBE`. No modificar código antes de esta clasificación.
