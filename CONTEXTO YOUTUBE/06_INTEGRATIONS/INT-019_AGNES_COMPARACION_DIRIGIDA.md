# INT-019 — Comparación dirigida basada en código: lcy362/agnes-video-generator ↔ YOUTUBE-AUTOMATION

- **Fecha:** 2026-10-23
- **Origen del encargo:** orden de trabajo "Cierre técnico de YOUTUBE-AUTOMATION + evaluación de Agnes Video Generator" (Fase 2/3), ejecutando la acción recomendada en `INT-018` §6.
- **Método:** auditoría de código real de ambos lados con referencias `archivo:línea`. Agnes clonado localmente en `research/` (NUCA dentro del repo de producción), commit `05d1b2e` (master, incluye v7.0-dev). YOUTUBE-AUTOMATION auditado en `main` `30535f2` + corrección local INT-020 (ver §4). **No se ejecutó Agnes, no se corrieron sus tests, no se copió ninguna línea de su código.**
- **Licencia verificada en el clon:** `LICENSE` = MIT, "Copyright (c) 2026 lcy362". Permite reutilización conservando el aviso. Hoy no hay código copiado; si en el futuro se copiara, debe preservarse el aviso y revisarse la licencia del commit concreto.
- **Dimensiones de Agnes (verificadas en el clon):** 479 archivos; core/ 62 módulos ≈ 20.7K líneas; tests/ 87 archivos ≈ 21.5K líneas (67 archivos `test_*.py`, ~1.452 funciones); docs/ ≈ 19.7K líneas; frontend Vue ≈ 30.5K líneas. Dependencias: FastAPI, uvicorn, moviepy≥2.0, edge_tts, srt, arabic-reshaper/python-bidi/mishkal, json-repair, Pillow, imageio-ffmpeg, tenacity, pydantic v2.

## 1. Dictamen ejecutivo

Comparación dirigida sobre las 4 áreas recomendadas por `INT-018` §6 (checkpoints/recuperación, registro de artefactos, regresión de producto final, sincronización de subtítulos) más 2 áreas extra de la orden de trabajo (gestión de errores/reintentos y composición multimedia). **Veredicto global: no importar código de Agnes.** Todas las capacidades valiosas ya existen en YOUTUBE-AUTOMATION con mecánica propia y probada, o son ideas adaptables documentadas aquí como candidatas con condiciones. El proyecto Agnes es una aplicación E2E con su propio task manager, UI, contratos y proveedores; su adopción directa duplicaría infraestructura prohibida por la frontera arquitectónica (INT-001, INT-018 §4).

Se registran **3 ideas adoptadas como referencia de diseño** (una de ellas ya materializada en la corrección INT-020 de esta misma misión) y **7 descartes con motivo** (§3).

## 2. Tabla maestra de comparación

Leyenda de veredicto: **YA EXISTE** (capacidad cubierta por nuestro código), **GAP REAL** (falta en nuestro sistema), **IDEA ADAPTABLE** (patrón adoptable como diseño, no como código), **NO APLICA** (ligado al proveedor/arquitectura de Agnes).

### 2.1 Checkpoints y recuperación de tareas

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Persistencia de estado | `task_state.json` por tarea con escritura atómica (`core/task_manager.py:129-153`, tempfile + `os.replace`) | `meta.json` por proyecto + cola SQLite `flow_jobs` (claim atómico `BEGIN IMMEDIATE` + job_token, `services/flow_jobs.py:265-287`) | YA EXISTE (soporte más fuerte: SQLite concurrente vs JSON de un proceso) |
| Reanudación sin repetir trabajo | Skip grueso por paso (`core/pipelines/multi_scene.py:210-238`) + skip fino validando existencia real de archivos (`steps_video.py:97-113`, `steps_frames.py:183-196`) | Reuso idempotente de clips por existencia (`orchestrator.py:693`), regeneración solo de imágenes faltantes (`orchestrator.py:336`), TTS skip-if-exists por hash de texto (`tts_step.py:10-11`), re-enqueue idempotente de jobs (`flow_jobs.py:638+`) | YA EXISTE |
| Anticiclo de reintentos | No aplica (una tarea, un proceso) | `MAX_LEASE_CYCLES=3` → dead; lease imagen 8 min / video 15 min; heartbeat condicional anti-zombi (`flow_jobs.py:46-49, 209-222, 265-340`) | YA EXISTE (nuestro caso multi-worker es más duro) |
| video_id del proveedor conservado al reanudar | `scene_i/task.json` + borrado selectivo solo si el proveedor confirmó `status=failed` (`core/api/agnes_video.py:184-194`) | Los clips Flow ya descargados se reutilizan por existencia (INT-011 C.2 idempotencia demostrada en vivo) | IDEA ADAPTABLE (matiz: persistir el ID de envío de Flow antes de la descarga; hoy no lo guardamos — gap fino de observabilidad, no de recuperación) |

**Coste-riesgo de importar su task manager:** ALTO — duplicaría `flow_jobs` + `meta.json` (segunda cola prohibida), acoplaría todo a `models/task.py` de Agnes. **Tests necesarios si se adoptara:** todos los de concurrencia/chaos existentes (18+28 checks) contra el nuevo motor — inviable sin rediseño.

### 2.2 Registro de artefactos y productos de pipeline

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Productos intermedios convencionales | story/script/prompts/end_frames/clips/SRT/final con nombres canónicos (`core/artifacts.py:133-248`, `docs/dev/pipeline_products.md:131-133`) | Production JSON + `data/output/<pid>/` con convención `flow/Escena_NN_flow.png`, `Escena_NN_video_<part>.mp4`, clips, `subs.ass`, sidecars | YA EXISTE |
| Registro declarativo + manifest + borrado en cascada | `core/artifacts.py:43-58, 449-680` (descriptores, plan de cascada, manifests JSON/MD) | `meta.json` + `cleanup_intermediates` con lista fija de regenerables y conservación de lo valioso (`pipeline/video.py:351-375`) | IDEA ADAPTABLE (baja prioridad: nuestro catálogo de artefactos es pequeño y estable; la cascada declarativa compensa cuando el catálogo crece) |
| Grafo de dependencias producto→producto | `core/dependency_graph.py:66-149, 262-329` (impacto compute) | No existe grafo explícito; la reanudación decide por existencia + contrato | GAP FINO (no bloqueante; documentar como candidato v1.1 si el catálogo crece) |

**Coste-riesgo:** medio; el grafo y la cascada son elegantes pero acoplan a su modelo de tareas. **Tests necesarios:** una batería nueva de gobernanza de artefactos.

### 2.3 Regresión del artefacto final (MP4)

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Validación de contenedor | Plan F1-F7: existencia, duración, resolución ±15%, pista de audio+ASR (whisper), subtítulos visibles/coincidencia ASR>30% (`docs/dev/regression_test_plan.md:93-139`) | `video_qa.py`: ffprobe por escena y final (duración/resolución/fps/códec/audio) + forense de frames 25/50/75% (pantalla negra/azul) + `max_volume` (audio silencioso) (`services/video_qa.py:95-160, 195-266`); QA gate bloquea ready/publish con errores (`orchestrator.py` `_gate_qa_final`) | YA EXISTE (núcleo) |
| Tolerancia contractual duración pedida vs observada | F3 ±15% | Ejecución Contract V1.1: duration ±tolerance+epsilon 0.25, aspect 2% (más estricto) | YA EXISTE |
| Validación de contenido hablado (ASR) y subtítulos visibles | F4/F6 con whisper; F5 manual | No automatizado (nuestro timing nace de whisper sobre el TTS; no hay re-verificación ASR del MP4 final) | GAP REAL no bloqueante → **R1** (§4): extensión de `video_qa` con verificación ASR opcional del final; toca contrato QA → decisión separada |
| Ejecución del plan | Runner externo con servicio real (no pytest) | Batteries pytest herméticas + smoke scripts; el E2E real requiere Chrome+sesión (INT-012) | YA EXISTE (misma filosofía: lo real fuera de pytest) |

### 2.4 TTS y sincronización de subtítulos (recuperación de cues)

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Origen de los tiempos de subtítulo | Cues del stream de edge_tts (WordBoundary) como "verdad" (`core/audio/tts.py:93-139`) | `words_timeline.json` por faster-whisper sobre el audio TTS real (`tts_step.py:4-5, 106-109`) | YA EXISTE (mecanismo distinto y más robusto a cambios de proveedor TTS) |
| Recuperación de cues al reanudar con audio ya existente | Cache `{audio}.cues.json` + re-harvest (`core/pipelines/__init__.py:782-850`) | No necesario en la misma forma: si el audio existe, whisper puede re-derivar tiempos; whisper además nunca tumba el pipeline (`tts_step.py:146`) | NO APLICA (el problema de Agnes nace de que sus cues viven solo en memoria durante la generación; los nuestros se re-derivan del audio) |
| Patrón cache de cues | `.cues.json` barato y elegante | — | IDEA ADAPTABLE como conocimiento (registrar en `09_KNOWLEDGE` si algún día cambiamos a TTS con cues en-stream) → **R3** |

### 2.5 Gestión de errores y reintentos (área extra)

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Política de reintentos | Dos vías busy/fault (`core/api/retry_policy.py:40-124`), multi-key round-robin (`key_manager.py:36-151`), token-bucket (`rate_limiter.py:97-214`) | flow_adaptation V1.1: taxonomía A-I por evidencia, P1/P2, retry limitado `MAX_EXTRA_GRANTS=1` (`services/flow_adaptation.py`); reintento por attempts en cola (imagen 3/video 2) | NO APLICA (su proveedor es API con keys y cuotas; el nuestro es Flow vía navegador — la adaptación va por evidencia, no por códigos HTTP de una API) |
| Colección de errores persistida | `error_collector.py` JSONL rotado con task_id | ledger JSONL de adaptación + audit trail del Doctor + evidencia de red de la extensión | YA EXISTE |

### 2.6 Composición multimedia (área extra)

| | Agnes | YOUTUBE-AUTOMATION | Veredicto |
|---|---|---|---|
| Concatenación | fast path `-c copy` con firma ffprobe + fallback moviepy (`concat.py:35-180`) | concat por lista + Ken Burns/crossfade 100% ffmpeg (`pipeline/video.py:76-275`) | YA EXISTE (nuestros requisitos de transición/Ken Burns son distintos) |
| Quemado de subtítulos | Single-pass ffmpeg con ASS si hay libass (`_has_libass`), timeouts 120-600s por comando, fallback moviepy | `burn_subtitles` ASS libass, timeout 900s; **INT-020 añade preset veryfast + timeout degradado honestamente** (antes: `medium` sin captura de timeout = incidente INT-012) | IDEA ADAPTABLE → **materializada hoy en INT-020** (la idea de "cada comando ffmpeg con timeout acotado y degradación registrada" valida nuestro diseño; su sondeo `_has_libass` es un matiz adoptable a futuro) |
| Sondeo de capacidad (libass/binarios) | `ffmpeg_tool.py:205-281` resolución de binarios + `_has_libass` | No hay sondeo explícito de libass (el fallo se degrada con registro) | IDEA ADAPTABLE (baja prioridad; R2) |

## 3. Registro de adopciones y descartes (obligación documental de la orden)

### 3.1 Adoptadas como ideas de diseño (NO código)

1. **Degradación escalonada y honesta de cada comando ffmpeg** (Agnes: `audio_overlay.py`, timeouts por comando + fallbacks) → ya materializada en **INT-020**: preset veryfast + timeout capturado que degrada con `subs_status.json` visible en el QA. Coste: 0 (era el pendiente INT-012).
2. **Matriz de regresión del artefacto final estilo F1-F7** → candidata **R1**: añadir a `video_qa` verificación ASR opcional del MP4 final (coincidencia de narración) y duración total vs esperada. Pendiente de decisión porque amplía el contrato QA.
3. **Sondeo de capacidad de render (`_has_libass`/binarios) antes de gastar el render** → candidata **R2** para el preflight del Doctor (capa de herramientas): advertir si libass no está disponible ANTES de renderizar 4K. Bajo coste, sin contrato nuevo.

### 3.2 Descartadas (con motivo)

1. **Importar `task_manager`/`task_state.json`** — duplicaría `flow_jobs`+`meta.json` (segunda cola prohibida por INT-001/INT-018 §4); nuestro soporte multi-worker es más fuerte.
2. **Importar `artifacts.py`/`dependency_graph.py`** — sobrecarga para un catálogo pequeño y estable; acopla a su modelo.
3. **Importar `retry_policy`/`key_manager`/`rate_limiter`** — ligados a un proveedor API con keys; Flow se opera por navegador con adaptación por evidencia (flow_adaptation V1.1).
4. **Patrón cue-cache de edge_tts** — nuestro timing es whisper sobre audio real; el problema no existe aquí.
5. **Sustituir el ensamblador por moviepy o por su compositor** — `pipeline/video.py` es superficie estabilizada; moviepy≥2.0 es una dependencia pesada con API cambiante y no demostró ventaja sobre nuestro ffmpeg directo.
6. **Keyframes encadenados i2i con etiquetas `[PRESERVE]/[CHANGE]`** — acoplado a `agnes-image-2.5`; Flow tiene su propio sistema de Start Frame/referencias (INT-007/INT-008). Sus nombres/parámetros no son contrato de Flow.
7. **Usar Agnes como orquestador/generador alternativo o crear un "agente editor de vídeo"** — prohibido por la frontera arquitectónica (orden §3; INT-018 §4).

### 3.3 Riesgos si algún día se copiara código

MIT exige conservar aviso de copyright y licencia; vigilada la cadena de dependencias de Agnes (moviepy 2.x, edge_tts sin SLA, imageio-ffmpeg binario) y su acoplamiento a `models/task.py`. Recomendación vigente: adoptar ideas y patrones, no código.

## 4. Relación con la corrección INT-020 (esta misma misión)

Durante esta misión se ejecutó la corrección del pendiente INT-012 (ver `INT-020_RENDER_BURN_TIMEOUT_FIX.md`): `burn_subtitles` usa ahora `-preset veryfast` y captura `TimeoutExpired` degradando con honestidad. La auditoría de la composición de Agnes (§2.6) se usó como **referencia cruzada** de que el patrón "timeout acotado + degradación registrada" es práctica establecida, no un debilitamiento de protecciones. El re-run real en 4K del HARD E2E (con Chrome + sesión del usuario) permanece como validación de Antigravity.

## 5. Verificación de esta comparación

- Agnes: SOLO lectura del clon; ni sus tests ni su servicio se ejecutaron; ninguna afirmación de este documento proviene de ejecución.
- YOUTUBE-AUTOMATION: anclas verificadas sobre `main` `30535f2` + diff local INT-020; suite canónica completa re-ejecutada en esta misión (resultado en `INT-020` §4).
- Cero cambios en contratos públicos, producción, Flow LIVE, publicaciones reales o superficies protegidas.

## 6. Decisión registrada

**DECISIÓN (D-008 en `01_DECISIONS/DECISION_LOG.md`):** Agnes Video Generator permanece como **referencia externa de solo lectura**. No se importa código, no se añaden dependencias, no se crean agentes ni capas nuevas. Las 3 ideas seleccionadas quedan registradas como R1/R2/R3 con condiciones y separadas de las correcciones ordinarias. El valor demostrado de esta auditoría es (a) confirmar que nuestras capacidades de checkpoint/reanudación/QA/errores ya cubren lo que Agnes hace bien, y (b) materializar el fix INT-020 validado por su patrón de degradación por comando.
