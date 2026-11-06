# Especificación operativa — Generador automático de miniseries dramáticas con NotebookLM + Google Flow

**Tipo:** documentación funcional y de aceptación; no declara integración real por sí sola.  
**Fuentes revisadas:** video aportado «Gemini Notebook: He creado un generador automático de mininovelas gratis» (duración aproximada 18:56; revisión visual de su flujo de pantalla), `Compt-ytube-MASTERPROMPT-MINIDRAMA.docx`, `herramientas-ia-v5-julio-2026.pdf`, y documentación existente del repositorio `PLAN_PILOTO_SERIE_NOTEBOOKLM.md`, `ANTIGRAVITY_VALIDACION_PRODUCCION.md` y `ESTADO_REAL.md`.  
**Propósito:** convertir el método editorial mostrado en el video y las reglas del Master Prompt en un flujo persistente, verificable y automatizable dentro de YOUTUBE-AUTOMATION.

> **Regla de evidencia:** esta especificación describe qué debe hacer el sistema. No demuestra que NotebookLM, Google Flow, Nano Banana, Omni/Veo, la extensión Chrome ni la generación real estén conectados. Esos puntos solo pasan con evidencia de una ejecución real.

---

## 1. Qué aporta cada fuente y qué autoridad tiene

### 1.1 Video tutorial aportado

En las pantallas del video se observa este recorrido general:

1. Preparación de un notebook de Gemini Notebook/NotebookLM identificado como **MINIDRAMAS**, con fuentes y directivas de trabajo.
2. Uso de instrucciones específicas para que el notebook produzca la estructura y los prompts de la mininovela.
3. Obtención de una propuesta narrativa y de prompts estructurados por episodio/clip.
4. Paso a Google Flow para crear referencias de personajes mediante la función **Characters** y generar material visual.
5. Generación de escenas/clips y revisión de los resultados.
6. Montaje de los materiales en un editor de video para obtener una pieza vertical final.

El video es una demostración visual del procedimiento humano. No debe interpretarse como evidencia de que exista una API pública, un contrato de automatización o una conexión de extremo a extremo entre NotebookLM y Flow. La automatización del navegador debe tratarse como una integración de interfaz sujeta a cambios.

### 1.2 Master Prompt adjunto — reglas funcionales obligatorias

El archivo `Compt-ytube-MASTERPROMPT-MINIDRAMA.docx` define:

- Formato objetivo: **5 episodios × 60 segundos = 300 segundos**.
- Cada episodio: **6 clips exactos × 10 segundos**.
- Cada episodio debe tener un gancho visual/narrativo en los primeros 3 segundos.
- El arco de temporada: incidente inducido; escalada/complicación; punto de quiebre o clímax intermedio; caída/reagrupación; resolución y cliffhanger final.
- Antes de desarrollar la serie, el sistema presenta **5 títulos con tagline** y se detiene hasta que el usuario elija uno.
- Después de la aprobación se construyen la biblia de personajes y sus referencias para Flow Characters/Nano Banana.
- Los prompts de personaje se centran en rostro, rasgos faciales e indumentaria.
- Los prompts de clip van en un solo párrafo continuo; nombres en MAYÚSCULAS; diálogo hablado siempre en español; máximo **12 palabras habladas por clip**; estado final descrito a los 9.9 s.
- El control de calidad verifica las fuentes Omni, la consistencia de personajes, el formato de párrafo, el idioma, el límite de diálogo, el estado final y el cómputo temporal.

Estas reglas se consideran requisitos de producto, no sugerencias de estilo.

### 1.3 Catálogo de herramientas adjunto

El PDF `herramientas-ia-v5-julio-2026.pdf` identifica, entre otras, estas herramientas:

- **Google Flow:** generación y edición de imágenes, personajes/referencias y generación de video; menciona Nano Banana y Veo/Omni.
- **Google AI Studio:** generación de voz/speech de Google.
- **ElevenLabs:** alternativa de generación de voz.
- También enumera Gemini, ChatGPT, Qwen, Suno y otras herramientas para tareas auxiliares.

El catálogo es una fotografía de julio de 2026. Sus precios, créditos, disponibilidad, nombres de modelos y límites no deben codificarse como constantes: deben ser configurables y volver a verificarse al ejecutar cada piloto. No se exige integrar todas las herramientas listadas. El flujo base de esta especificación usa NotebookLM como fuente editorial, Flow para imagen/video y un proveedor TTS configurable.

---

## 2. Resultado que debe producir el sistema

Una ejecución válida debe dejar un **paquete de serie reproducible**, no solo texto en una conversación:

```text
data/output/<production_id>/
  series/
    SERIES_BIBLE.md
    SERIES_BIBLE.json
    source_register.json
    approvals.json
    continuity/
      episode_01_state.json
      episode_02_state.json
  episodes/
    EP01/
      episode_script.json
      episode_script.md
      characters/
        <CHARACTER_ID>_reference_prompt.txt
        <CHARACTER_ID>_reference_image.png
      clips/
        C01/
          clip_spec.json
          flow_prompt.txt
          image/
          video/
          audio/
        ...
        C06/
      voice/
      subtitles/
      render/
      qa/
    EP02/
      ...
  production_manifest.json
  run_log.jsonl
```

La estructura es una **propuesta de organización**. Antes de implementarla, mapearla a las rutas reales y convenciones de YOUTUBE-AUTOMATION; no crear una segunda estructura incompatible con `data/output/<pid>`, Flow Bridge ni el orquestador existente.

### 2.1 Entregables mínimos

1. Biblia editorial y registro de fuentes.
2. Cinco títulos y taglines, con selección humana registrada.
3. Biblia de personajes y prompts de referencia.
4. Arco de los cinco episodios.
5. Guion y seis especificaciones de clip por episodio.
6. Prompts listos para Flow y referencias visuales generadas.
7. Clips/imágenes descargados y vinculados a su escena.
8. Voz, música si aplica, subtítulos y render final.
9. Reportes QA técnicos y revisión creativa humana.
10. Estado de continuidad al final de cada episodio y evidencia de aprobación.

---

## 3. Flujo funcional con puertas de aprobación

### Fase A — Ingesta de fuentes y preparación de NotebookLM

**Entradas:** identificador del notebook, fuentes autorizadas, fecha de revisión y objetivo de la serie.

**Acciones:**
1. Comprobar que el notebook existe y la sesión está autenticada.
2. Enumerar fuentes disponibles y conservar título, tipo, fecha/versión y referencia de origen cuando sea posible.
3. Separar hechos documentados, interpretación, ideas creativas y datos pendientes de verificar.
4. Aplicar el prompt maestro y las guías de minidramas/Google Omni disponibles en el notebook.
5. Generar un resumen estructurado y una biblia preliminar.

**Salida:** `source_register.json` y `SERIES_BIBLE.md/json`.

**Gate A:** no avanzar si faltan fuentes obligatorias, si el notebook no está autenticado o si el resumen mezcla hechos e inferencias sin etiquetarlos. La biblia debe quedar guardada en el proyecto; no depender de la memoria del chat.

**Nota:** NotebookLM es la fuente de investigación/criterios editoriales. El video no demuestra que se deba automatizar la creación de notebooks ni que NotebookLM exponga una API estable para todas las operaciones. Si se usa automatización de interfaz, debe ser un adaptador independiente y verificable.

### Fase B — Concepto y selección del título

1. Proponer exactamente cinco conceptos/títulos, cada uno con tagline.
2. Registrar para cada opción premisa, conflicto, promesa dramática y gancho.
3. Presentar las cinco opciones al usuario.
4. **Detener el flujo** y esperar selección explícita.
5. Guardar opción seleccionada, fecha, usuario/actor aprobador y versión de la biblia.

**Gate B:** sin selección explícita no se crean personajes, guiones ni jobs de generación. Un timeout no equivale a aprobación.

### Fase C — Biblia de personajes y continuidad visual

Por cada personaje:
- ID estable e inmutable (no usar solo el nombre como clave).
- Nombre en MAYÚSCULAS para presentación.
- Edad exacta definida por el guion.
- Rasgos faciales: forma del rostro, piel, ojos, cejas, nariz, labios, cabello y rasgos distintivos.
- Vestuario completo y paleta: prendas, colores, calzado y accesorios.
- Rol narrativo, relaciones, objetivo, conflicto y evolución.
- Voz/idioma y características vocales si habrá locución o diálogo generado.
- Restricciones de continuidad: elementos que no deben cambiar entre clips, salvo cambio explícito de vestuario/tiempo.

Crear un prompt de referencia por personaje, siguiendo el formato del Master Prompt, y generar la imagen en Flow Characters/Nano Banana.

**Gate C:** revisar la referencia generada y aprobarla antes de usarla como referencia de clips. Guardar el asset y su identificador real de Flow; no asumir que escribir el nombre del personaje en el prompt equivale a adjuntar una referencia.

### Fase D — Arco de temporada y guiones

Generar cinco episodios con estos objetivos narrativos:

| Episodio | Función |
|---|---|
| EP01 | Incidente inducido; conflicto inmediato y hook en 0–3 s |
| EP02 | Escalada, complicación e intento fallido |
| EP03 | Punto de quiebre, confrontación o giro |
| EP04 | Caída, tensión máxima y reagrupación |
| EP05 | Resolución del conflicto y cliffhanger para otra temporada |

Cada episodio debe incluir logline, objetivo dramático, conflicto, giro, clímax, cliffhanger, cambios de personajes y hechos revelados.

**Gate D:** comprobar continuidad causal entre episodios y que el EP05 resuelva el arco principal aunque abra uno nuevo. No inventar hechos presentados como verificados si la serie tiene base documental.

### Fase E — Desglose de clips y contrato de prompt

Cada episodio contiene exactamente seis clips de 10 segundos:

| Clip | Rango | Función |
|---|---:|---|
| C01 | 00–10 s | Hook visual |
| C02 | 10–20 s | Desarrollo y tensión |
| C03 | 20–30 s | Giro menor |
| C04 | 30–40 s | Reacción/escalada |
| C05 | 40–50 s | Clímax |
| C06 | 50–60 s | Micro-cliffhanger |

Cada clip debe tener una ficha estructurada, como mínimo:

- `episode_id`, `clip_id`, `start_ms`, `end_ms`, `duration_target`.
- `story_function`, `location`, `time_of_day`, `visual_style`, `camera`, `lighting`.
- `casting` con IDs de personajes y referencias adjuntas.
- `initial_state`, `action`, `change`, `final_state`.
- `image_prompt`, `video_prompt`, `references`, `audio`.
- Diálogo exacto en español, personaje que habla y contador de palabras.
- Estado final visual a 9.9 s que permita enlazar con el siguiente clip.
- Criterios de aceptación y restricciones negativas relevantes.

**Reglas de prompt:**
1. El prompt que se envía a Flow debe conservarse íntegro y trazable.
2. Un párrafo continuo por clip, según el Master Prompt.
3. Nombres en MAYÚSCULAS.
4. Diálogo en español, máximo 12 palabras por clip. El validador debe contar palabras de forma determinista y mostrar el texto que excede el límite.
5. El estado final a 9.9 s debe estar dentro del párrafo.
6. Duración objetivo exacta de 10 s; si la interfaz/proveedor no puede garantizarla, registrar duración solicitada y observada por separado. No declarar cumplimiento solo porque el prompt diga “10 seconds”.
7. Incluir referencia real de personaje/imagen cuando la interfaz lo permita; si no se puede adjuntar, detener o marcar como excepción aprobada, nunca fingir consistencia.
8. No incluir instrucciones incompatibles, múltiples acciones simultáneas imposibles o diálogos que excedan el tiempo de habla.

**Gate E:** validación automática de 30 clips por temporada (5×6), 10 s objetivo, diálogo, campos requeridos, referencias y continuidad. Los clips no válidos no se encolan.

### Fase F — Generación en Google Flow

Orden obligatorio y trazable:
1. Verificar sesión Google y pestaña Flow correctas.
2. Capturar capacidades reales de la sesión/modelo y configuración visible; no asumir que una opción existe.
3. Verificar controles requeridos antes de enviar (modelo, duración, relación de aspecto, referencias, audio u otros que realmente se exijan).
4. Crear/seleccionar referencias de personajes.
5. Enviar el prompt del clip y adjuntar referencias.
6. Esperar resultado con timeout y observación de estado.
7. Descargar el asset real, validar bytes/formato y asociarlo al clip.
8. Registrar job, intento, estado, modelo/configuración observados, tiempos, errores y ruta del asset.
9. Reintentar solo según política limitada; cada intento debe tener ID propio. No confundir un tile/error temporal de la UI con el resultado final del job.
10. Si hay rechazo, cambio de UI, falta de capacidad o estado no verificable, detener ese job y conservar evidencia. No inventar un PASS.

**Gate F:** no pasar al render hasta que todos los clips requeridos tengan assets válidos o una excepción aprobada. La extensión/bridge y el backend deben confirmar el job; un mock, DOM simulado, fixture o test hermético no cuenta como generación real.

### Fase G — Voz, sonido, montaje y render

- Proveedor TTS configurable (Google AI Studio o ElevenLabs, según disponibilidad/decisión); no codificar precios ni cuotas del PDF como valores permanentes.
- Voz consistente por personaje, pronunciación y español definido para la audiencia.
- Música y efectos solo con derechos/licencia compatibles con el uso previsto.
- Alinear voz, diálogo, duración y subtítulos.
- Ensamblar clips en orden, respetando continuidad y tiempos.
- Formato vertical 9:16 como objetivo del Master Prompt.
- Exportar MP4 y subtítulos; registrar códec, resolución, FPS, duración y presencia de audio.
- Mantener la cadena de assets original para poder reconstruir el render.

**Gate G:** QA técnico sin errores bloqueantes; reproducción real del MP4; revisión humana de continuidad, legibilidad, actuación, calidad visual y coherencia narrativa. El QA técnico no sustituye la revisión creativa.

### Fase H — Continuidad y siguiente episodio

Al cerrar cada episodio, generar y guardar:
- Resumen canónico de lo ocurrido.
- Estado exacto de cada personaje (ubicación, vestuario, lesiones/objetos, relaciones y conocimiento).
- Hechos revelados y preguntas aún abiertas.
- Estado final de cada clip y del episodio.
- Referencias visuales aprobadas y cambios justificados.
- Decisiones editoriales y excepciones.

El episodio siguiente debe cargar esos artefactos persistentes como contexto obligatorio. No depender de la conversación previa ni regenerar personajes desde cero.

**Gate H:** validar contradicciones de cronología, vestuario, localización, relaciones, conocimiento y objetos. Para declarar repetibilidad, producir y revisar al menos una escena real del episodio siguiente.

### Fase I — Publicación

La publicación no forma parte del piloto automático por defecto. Requiere:
- QA final sin errores bloqueantes.
- Aprobación humana explícita y persistida.
- Metadatos revisados (título, descripción, miniatura, audiencia, idioma).
- Estado de publicación idempotente y evidencia del resultado.

Autopublicación desactivada durante las pruebas. Nunca convertir el éxito de render en consentimiento para publicar.

---

## 4. Contrato de datos recomendado

El sistema ya documenta campos de producción como `image_prompt`, `video_prompt`, `duration_target`, `initial_state`, `action`, `change`, `final_state`, `audio`, `references`, `casting` y `story_function`. Se deben reutilizar y extender, no duplicar bajo nombres alternativos.

Campos de control adicionales recomendados:
- Identidad: `series_id`, `season_id`, `episode_id`, `clip_id`, `character_id`, `production_id`.
- Versionado: `master_prompt_version`, `series_bible_version`, `source_snapshot_id`, `prompt_hash`.
- Aprobaciones: `approval_required`, `approval_state`, `approved_by`, `approved_at`.
- Evidencia: `source_refs`, `flow_job_id`, `attempt_id`, `asset_sha256`, `asset_path`, `observed_settings`.
- Estado: `editorial_state`, `generation_state`, `qa_state`, `creative_review_state`, `publish_state`.

Estados sugeridos por etapa:
`DRAFT → NEEDS_APPROVAL → APPROVED → READY → QUEUED → GENERATING → ASSET_VALIDATED → RENDERED → QA_PASSED → CREATIVE_REVIEW → APPROVED_FOR_PUBLISH → PUBLISHED`.

Los estados de error/indeterminación deben ser terminales o requerir una transición explícita de recuperación; nunca mapear `UNKNOWN`, `UNVERIFIABLE` o timeout a éxito.

---

## 5. Validaciones automáticas mínimas

### Editorial
- Cinco opciones de título antes de cualquier desarrollo.
- No hay avance sin título aprobado.
- Cinco episodios y seis clips por episodio.
- 30 clips exactos por temporada base.
- Hook identificable en los primeros 3 segundos de cada episodio.
- Arcos y cliffhangers cumplen la función definida.
- Diálogos en español y máximo 12 palabras por clip.
- Nombres en mayúsculas y personajes definidos en la biblia.
- Cada clip tiene estado inicial, acción/cambio y estado final.
- No hay contradicciones con la continuidad guardada.

### Visual/técnico
- Referencia de personaje existe y está adjunta cuando es requerida.
- Aspect ratio vertical 9:16 solicitado y observado por separado.
- Duración solicitada y observada guardadas.
- Archivo descargado con magic bytes/formato válido.
- No aceptar HTML/error pages como imágenes o videos.
- Video validado con ffprobe; imagen con decodificador real.
- Render final reproducible, audio audible, subtítulos sincronizados y legibles.
- QA final y revisión creativa son estados distintos.

### Operación/seguridad
- Proyecto de prueba aislado y autopublish apagado.
- Secretos nunca se guardan en prompts, documentos, HAR ni logs.
- Timeouts y reintentos limitados; no bucles infinitos.
- Evidencia saneada por job y por intento.
- Kill switch y cancelación disponibles.
- Cualquier acción física/navegador requiere permisos explícitos y allowlist.
- Coste/créditos y latencia por proveedor se registran cuando estén disponibles.

---

## 6. Mapeo a la documentación y arquitectura existente

La intención es complementar la arquitectura actual:

- `CONTEXTO YOUTUBE/05_TESTS/PLAN_PILOTO_SERIE_NOTEBOOKLM.md`: plan de ejecución del piloto; debe usar esta especificación como contrato editorial/funcional.
- `CONTEXTO YOUTUBE/05_TESTS/ANTIGRAVITY_VALIDACION_PRODUCCION.md`: procedimiento de validación real en la máquina, Chrome, sesión Google y Flow.
- `ESTADO_REAL.md`: inventario de lo implementado y de lo no demostrado; solo se actualiza con evidencia.
- `docs/PRODUCTION_DOCTOR.md`: preflight y diagnóstico de bloqueos.
- `docs/HANDS.md` y Flow Bridge/Execution Contract: ejecución de navegador y jobs; la especificación editorial no debe saltarse sus gates.
- Production JSON y contrato P1: preservar `video_prompt` verbatim y los campos creativos existentes.
- Video QA/orquestador: validar assets y render; separar validación técnica de revisión creativa.

**No duplicar** un segundo motor de generación de guiones ni un segundo puente de Flow. El objetivo es que el paquete editorial se transforme en el Production JSON ya aceptado por el backend y siga el mismo Flow Bridge/orquestador.

---

## 7. Brechas que esta documentación deja explícitas

1. **No existe evidencia aportada de lectura automática del notebook y conversión fiable a biblia estructurada.** Definir el adaptador real y su contrato; si la extracción requiere intervención humana, registrarlo como paso manual.
2. **La aprobación de título y biblia debe persistir como estado del sistema.** No basta con que el asistente se detenga en una conversación.
3. **La creación/selección de Characters y el adjuntado de referencias deben verificarse en Flow real.** Una imagen de referencia generada no prueba que se haya vinculado a los clips.
4. **El Master Prompt define tiempos objetivo, pero no especifica tolerancia de duración observada ni política cuando Flow entrega clips con otra duración.** La política debe quedar explícita en configuración y QA.
5. **Falta un contrato formal de continuidad por personaje/episodio** en los documentos de origen. Esta especificación propone los campos mínimos.
6. **La selección de TTS y la sincronización de diálogo/subtítulos** no están desarrolladas en el Master Prompt; se proponen como fase configurable del pipeline.
7. **El video muestra montaje final en editor**, pero no fija un editor ni un contrato de proyecto editable. El pipeline debe definir si el entregable será MP4 final, proyecto editable o ambos.
8. **Licencias/derechos** de música, imágenes, voces y fuentes deben registrarse según el destino comercial; el catálogo de herramientas no resuelve esos derechos.
9. **Cuotas, modelos y precios del PDF son temporales.** Revalidar en cada corrida y nunca garantizar “gratis” o “ilimitado”.
10. **No hay en el video evidencia suficiente para especificar una API de NotebookLM o Flow.** No diseñar automatización contra endpoints no documentados basándose solo en el video.

---

## 8. Criterios de aceptación de la primera prueba

La primera prueba se considera:

- **EDITORIAL_PASS:** biblia con fuentes trazables, título elegido, 5 episodios/30 clips válidos y aprobaciones persistidas.
- **FLOW_IMAGE_LIVE_PASS:** al menos una referencia/personaje o imagen generada en Flow real, descargada y validada, con evidencia del job.
- **FLOW_VIDEO_LIVE_PASS:** al menos un clip de video real generado, descargado y validado con configuración observada.
- **PILOT_RENDER_PASS:** episodio piloto montado, reproducible, con voz/subtítulos y QA técnico + revisión humana.
- **CONTINUITY_PASS:** una escena del episodio siguiente mantiene continuidad a partir de archivos persistidos.
- **SERIES_AUTOMATION_PASS:** repetición del flujo completo sin intervención manual en cada clip, excepto las aprobaciones editoriales/creativas que se hayan definido como obligatorias.

No declarar `SERIES_AUTOMATION_PASS` por tener tests verdes, mocks, un único video de muestra o por completar manualmente cada escena. El informe debe indicar qué pasos fueron automáticos, cuáles manuales y qué evidencia existe.

---

## 9. Regla final

El objetivo no es que el sistema “sepa escribir un prompt”. El objetivo es que convierta fuentes aprobadas en un paquete de producción versionado, solicite las aprobaciones correctas, ejecute jobs verificables en Flow, descargue y valide assets, monte el episodio, preserve continuidad y pueda repetirlo. Toda transición debe tener entrada, salida, estado, evidencia y criterio de fallo.
