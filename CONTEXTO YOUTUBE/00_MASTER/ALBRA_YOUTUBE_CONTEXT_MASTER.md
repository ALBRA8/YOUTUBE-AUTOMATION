# ALBRA — YOUTUBE-AUTOMATION — CONTEXTO MAESTRO DE AUDITORÍA

**Documento de continuidad y transferencia de contexto.**

## 0. Propósito

Este documento concentra el contexto técnico y de auditoría disponible sobre `ALBRA8/YOUTUBE-AUTOMATION`, su extensión Google Flow y la integración futura con el agente general ALBRA. Su objetivo es evitar pérdida de contexto entre sesiones, constructores y auditorías.

> Este documento contiene únicamente contexto técnico no secreto. No registrar tokens, cookies, credenciales, firmas de URL, media IDs crudos ni secretos de infraestructura.

---

## 1. Fuente de verdad actual

- Repositorio: `ALBRA8/YOUTUBE-AUTOMATION`
- Rama de la extensión validada: `harness-v1`
- Commit validado de la extensión: `8326f43ebd54f3a6fb41e4b74041422c44955eb8`
- Versión de extensión: `2.6.0`
- `main` contiene documentación/contexto histórico y, a fecha de esta auditoría, mantiene una extensión más antigua (`2.4.2`).
- **No considerar `main` como fuente de verdad de la extensión hasta una eventual fusión deliberada de `harness-v1` → `main`.**

Regla operativa: no mezclar documentación/estado de `main` con el estado funcional de la extensión en `harness-v1` sin indicar explícitamente la rama de origen.

---

## 2. Arquitectura conceptual ALBRA

Objetivo arquitectónico:

`AGENTE-GENERAL ALBRA`
→ contratos, permisos, auditoría, gobernanza y capacidades comunes

`YOUTUBE-AUTOMATION`
→ orquestación y contratos específicos del dominio YouTube

`Extensión / bridges / capacidades especializadas`
→ observabilidad y ejecución especializada en el navegador cuando corresponda

Las capacidades externas de YouTube no deben convertirse automáticamente en agentes autónomos independientes. Deben integrarse como capacidades especializadas bajo los contratos y gobernanza de ALBRA.

No alterar contratos existentes, bridge, cola, backend o AGENTE-GENERAL únicamente para acomodar una integración externa sin auditoría previa.

---

## 3. Estado del backend local

Backend reportado como desplegado:

- URL: `http://127.0.0.1:8000/`
- Versión: `2.20.0`
- Health: `200 OK`
- `gemini: true`
- `nvidia: true`
- `nvidia_model: moonshotai/kimi-k3`
- `whisper: true`

Importante: los valores `true` del health endpoint demuestran disponibilidad/configuración reportada, pero no equivalen por sí solos a una prueba funcional completa de cada proveedor.

---

## 4. Unificación de extensiones locales

Antes de la unificación existían tres copias divergentes:

| Ubicación | Versión anterior | Estado actual |
|---|---:|---|
| `p1-work/extension` | 2.6.0 | Canónica; sin cambios |
| `yt_automation_v2/extension` | 2.3.0 | Sincronizada a 2.6.0 |
| `cleanroom-github/extension` | 2.2.0 | Sincronizada a 2.6.0 |

El constructor reportó `diff -r` byte-a-byte idéntico entre las tres copias después de la sincronización: mismos 13 archivos + iconos, incluyendo el parser F2 de `injector.js`.

Los demás trabajos de esos clones (backend/submódulos) quedaron intactos.

**Regla de oro:** la única fuente de verdad de la extensión es `harness-v1` en el commit `8326f43`, extensión `2.6.0`.

En Chrome debe existir una sola copia activa de esta extensión. Si hay una copia cargada desde otra carpeta, debe retirarse de Chrome antes de validar el comportamiento para evitar dos instancias compitiendo.

---

## 5. Fase 1 / Fase 2 de instrumentación Google Flow

### F1 — batchexecute

La extensión 2.6.0 incorpora observación de tráfico `batchexecute`.

El parser extrae, cuando la estructura lo permite:

- `operation`
- `videoModelKey`
- `aspectRatio`
- `count`
- `structuredPromptPresent`
- `startFrame` como `{mediaIdPresent, fingerprint}`
- variantes de `inputFrames.firstFrame.mediaId`
- `firstFrame.mediaId`
- `startImage.mediaId`
- crop coordinates mediante whitelist

La respuesta se observa mediante `resp.clone()` y canal `FLOW_BATCH_RESPONSE`.

Las URLs observadas eliminan query strings antes de ser expuestas.

No se emiten media IDs crudos como telemetría pública.

### F2 — Start Frame

Commit validado: `8326f43...`.

Los tests de F2 simulan payloads en VM y validan el parser. El constructor reportó 67/67 checks Python para F2.

**Limitación:** esos tests son mocks/fixtures; no prueban por sí solos el payload LIVE real de Google Flow.

---

## 6. Batería de tests reportada

El constructor reportó, sin que esto deba interpretarse como auditoría independiente:

- F2 mock: 14/14
- Python F2: 67/67
- F1: 64/64
- error tile: 65/65
- tab selector: 58/58
- harness: 55/55
- flow bridge: 49/49

`tests/run_all.py` incluye `test_flow_batchexecute.py` y `test_flow_startframe_fase2.py`.

GitHub combined status del commit consultado anteriormente devolvió `statuses: []`; no se debe afirmar que hubo CI externa si GitHub no la muestra.

---

## 7. Prueba LIVE Start Frame — resultado confirmado

La prueba LIVE fue ejecutada en Chrome real con:

- Chrome `155.0.0.0` / Windows 10/11 x64 reportado por el constructor
- Backend ALBRA `2.20.0`
- Extensión Flow Script Processor ID `eejhfkoibnkfnkiomejgcggclofceobp`
- Extensión `2.6.0`
- Commit `8326f43...`
- Start Frame real en la UI de Google Flow
- Prompt de prueba: `esta tomando cafe la mujer`

Resultado funcional:

- Start Frame: **SÍ**
- Generación real: **SÍ**
- Vídeo generado: **SÍ**

El tráfico real permitió observar:

- RPC `eb1hJf` asociado a la mutación/render
- RPC `WuwhI` asociado a una acción de referencia/ingrediente
- `videoModelKey`: `abra_i2v_10s`
- `aspectRatio`: `1`
- `count`: `1`
- referencia de Start Frame mediante slot
- crop real observado
- generación completada en la UI

Crop observado en la prueba:

- top: `0.10081230055120394`
- left: `null`
- bottom: `0.8991876994487961`
- right: `1.0`

La generación quedó correlacionada funcionalmente como:

`imagen seleccionada → request real → tarea/render → vídeo resultante`

---

## 8. Hallazgo crítico del LIVE Gate

El resultado correcto del Live Gate NO es PASS completo. Es:

**PASS PARCIAL**

Motivo:

La extensión 2.6.0 observó el tráfico `batchexecute`, pero durante esta ejecución real el parser no extrajo automáticamente todos los campos porque la mutación de render se transportó en `eb1hJf` como una **matriz posicional/protobuf**, no mediante la estructura textual esperada por el parser para ciertas llamadas `WuwhI`.

El parser esperaba una estructura del tipo conceptual:

`WuwhI → MEDIA_GENERATION_SETTINGS → JSON`

La ejecución LIVE mostró una estructura diferente:

`eb1hJf → matriz posicional/protobuf`

Por esta razón, valores como `videoModelKey`, crop y referencia de Start Frame tuvieron que ser identificados mediante inspección directa del payload real de red.

**Conclusión:** Google Flow Start Frame funciona en vivo; la observabilidad automática de la extensión todavía necesita soportar de forma segura esta variante real de `eb1hJf`.

---

## 9. Distinción crítica de identificadores

No asumir equivalencia entre:

- slot ID
- asset ID
- media ID
- fingerprint

En la prueba LIVE se observó un slot de Start Frame con UUID y una huella sanitizada reportada por el constructor. Eso demuestra una referencia y una relación observada, pero no debe etiquetarse automáticamente como `mediaIdPresent: true` si el parser no obtuvo realmente un media ID.

Un fingerprint de una referencia/slot no debe presentarse como fingerprint de media ID sin evidencia suficiente.

Esta distinción debe resolverse en la siguiente auditoría de `eb1hJf`.

---

## 10. Siguiente gate obligatorio

Antes de modificar `injector.js`, realizar una **autopsia técnica del RPC LIVE `eb1hJf`**.

Objetivos:

1. Determinar estructura real del payload.
2. Identificar exactamente dónde aparecen operación, modelo, ratio, count, Start Frame, asset/media references, crop, prompt y task identifiers.
3. Clasificar cada identificador como slot ID, asset ID, media ID, fingerprint u otro.
4. Explicar exactamente por qué el parser 2.6.0 devuelve `null`.
5. Comparar con las estructuras F1/F2 ya soportadas.
6. Determinar si `eb1hJf` es una variante estable que debe incorporarse al parser.
7. Diseñar el cambio mínimo antes de implementarlo.
8. Evaluar regresión sobre F1/F2.
9. Definir una nueva prueba LIVE posterior al cambio.

Durante esta autopsia:

- NO modificar código.
- NO hacer commits.
- NO cambiar ramas.
- NO fabricar payloads.
- NO llamar endpoints internos de Google directamente.
- NO usar mocks como evidencia LIVE.
- Sanitizar secretos.

---

## 11. Principios de seguridad y límites

No implementar ni intentar:

- transporte backend de Start Frame fuera de la UI autorizada;
- fabricación de `batchexecute`;
- replicación de tokens/cookies/reCAPTCHA;
- reproducción del backend interno de Google Flow;
- extracción o publicación de credenciales;
- emisión de media IDs crudos.

La extensión debe actuar como observador pasivo de operaciones que la UI real ya ejecuta.

---

## 12. Repo externo de skills YouTube

Repositorio autor identificado:

`Jakeschincariol/youtube-agent-skill`

Existe también un repo distinto:

`pacb9148/Jakeschincariol-youtube-agent-skill`

Los README consultados tuvieron el mismo blob SHA `7889414543d8654abff5eb39f2b8365df52d4ae7`, lo que demuestra README idéntico en la comparación realizada, pero no autoriza a afirmar que todos los archivos sean idénticos sin comparar árboles/contenidos completos.

También existe un repo diferente llamado `Jakeschincariol/chatgpt-youtube-agent-skill`; no confundirlo con el repo original `youtube-agent-skill`.

El repo autor `youtube-agent-skill` fue descrito como un conjunto de 11 skills y 6 scripts Python bajo MIT. No publica automáticamente vídeos; entrega materiales para revisión humana.

Skills identificadas:

- `yt-script`
- `yt-package`
- `yt-retention`
- `yt-edit`
- `yt-shorts`
- `yt-chapters`
- `yt-viral`
- `yt-plan`
- `yt-comment`
- `yt-seo`
- `yt-audit`

### Auditoría técnica inicial de esas skills

Hallazgos:

1. `skills/yt-edit/deadair.py`: el manejo de una raíz JSON tipo lista presenta un defecto porque accede a `.get()` antes de resolver correctamente el tipo.
2. El mismo script suma duraciones de cortes sin unir intervalos solapados, pudiendo sobrecontar.
3. `hookscore.py` es heurístico y no debe tratarse como predictor fiable de views.
4. `yt-retention/retention.py` usa los dos primeros valores numéricos del CSV; debe validarse con exportaciones reales y columnas/unidades reales.

### Estrategia recomendada de integración

Primera tanda:

- `yt-script`
- `yt-package`
- `yt-retention`
- `yt-shorts`
- `yt-chapters`
- `yt-audit`

Segunda tanda:

- `yt-plan`
- `yt-comment`
- `yt-seo`

Tercera tanda, después de corregir/validar:

- `yt-edit`

`yt-viral` debe integrarse con límites claros sobre procedencia y calidad de datos.

No copiar el repositorio entero como 11 agentes autónomos ni conservar rutas/estructuras específicas de Claude sin adaptación.

---

## 13. Estado de integración de skills

A la fecha de este documento, la recomendación es **integración selectiva y auditada**, no copia masiva.

No modificar contratos existentes del núcleo ALBRA para acomodar las skills externas sin una auditoría previa.

---

## 14. Estado de certificación

### Certificado / demostrado

- Extensión 2.6.0 desplegada y cargada.
- Commit `8326f43` como fuente de verdad de `harness-v1`.
- Copias locales unificadas byte-a-byte según reporte del constructor.
- Start Frame funciona realmente en Google Flow.
- Generación real de vídeo con Start Frame completada.
- `abra_i2v_10s` observado en tráfico real.
- Crop observado en tráfico real.
- Correlación funcional imagen → request → tarea → vídeo demostrada.

### No certificado todavía

- Parser automático de la extensión para la variante LIVE `eb1hJf`.
- Extracción automática inequívoca de media ID desde esta variante.
- Certificación completa del Live Gate de observabilidad.
- Fusión de `harness-v1` → `main`.
- Integración definitiva de las skills externas.

---

## 15. Regla de continuidad

Cualquier nueva auditoría debe comenzar leyendo este documento y verificando el commit/branch actual antes de sacar conclusiones.

Nunca asumir que `main` y `harness-v1` representan el mismo estado.

Nunca elevar `PASS PARCIAL` a `PASS` sin una nueva prueba LIVE que demuestre la extracción automática requerida.

Nunca tratar un mock como sustituto de una prueba LIVE.

---

## 16. Próximo paso operativo

**Primero:** autopsia técnica del payload LIVE `eb1hJf`.

**Después:** propuesta de cambio mínimo del parser.

**Después:** implementación autorizada.

**Después:** tests regresivos F1/F2.

**Después:** nueva prueba LIVE Start Frame.

**Solo después:** decisión sobre certificación y eventual merge a `main`.


---

## 17. Production Framework y familia de Blueprints — 2026-10-23

Se consolidó el diseño conceptual de una arquitectura de múltiples líneas de producción, documentada en `00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md`.

Decisión central: usar un **Production Framework común** y un Blueprint especializado por línea; no crear un Blueprint universal ni un motor independiente por línea.

Registro inicial:
- `microdrama` → `microdrama_vertical_series_5x60`
- `short` → `short_vertical_v1`
- `short_form` → `short_form_production_v1`
- `ugc` → `ugc_creator_content_v1`

Fronteras: Creative Engine decide qué crear y genera Creative Specification + Production JSON; YOUTUBE-AUTOMATION ejecuta; Reverse Engineering Engine permanece independiente y transversal; NotebookLM/fuentes son conocimiento/canon/documentación, no un director creativo ni el motor de producción.

**Estado honesto:** la arquitectura y los cuatro Blueprints están definidos a nivel documental/conceptual. No afirmar que schemas, selector, validadores o integración de runtime estén implementados o probados hasta verificarlos en el repositorio. El siguiente paso es formalizar los schemas, el registro/selector y las pruebas de contrato, reutilizando los motores existentes.

Fuente canónica: `00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md`.
