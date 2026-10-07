"""
YOUTUBE AUTOMATION v2.0 — REGISTRO UNIVERSAL DE SKILLS (§10, contrato Skill)

Toda capacidad ejecutable del sistema se declara con los MISMOS campos
(SKILL_FIELDS) para que el agente pueda descubrirla, evaluarla y llamarla
sin código pegamento. Cada entrada declara además:

  kind      → naturaleza de la entrada (KINDS):
  TOOL             = función pura envuelta (entrada→salida, sin política)
  SKILL            = procedimiento multi-paso con verificación propia
  MEMORY           = lectura de memoria (no muta nada)
  KNOWLEDGE        = hecho estable (no ejecuta: describe)
  FEEDBACK         = registro de resultado (cierra el ciclo de evidencia)
  LEARNING         = candidato en validación (aún no promovible)
  SELF-IMPROVEMENT = promoción controlada: SOLO con humano en el bucle y
                     batería de regresión en verde (NUNCA salta seguridad
                     ni política de publicación — ver services/autonomy.py)

  target    → ruta importable (dotted path) de la función REAL del repo que
              implementa la skill. validate_registry() la resuelve con
              importlib: si el binding no existe, el registro NO valida.

Honestidad de métricas: confidence 0.8 si una batería de tests ejercita la
skill (0.5 si solo está cubierta por integración/mock); success_rate arranca
en 0.0 con origin "registrar_on_first_use" — la tasa REAL se registra en el
primer uso mediante mark_validated() (contadores en data/skills_state.json),
jamás se inventa una medición.
"""
import importlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Contrato §10: los 16 campos que TODA skill declara ──────────────────────
SKILL_FIELDS = ("identity", "purpose", "trigger", "prerequisites", "procedure",
                "tools_required", "expected_result", "verification", "pitfalls",
                "evidence", "version", "confidence", "success_rate", "origin",
                "last_validated", "regression_tests")

# ── Naturalezas declarables (docstring del módulo: qué significa cada una) ──
KINDS = ("TOOL", "SKILL", "MEMORY", "KNOWLEDGE", "FEEDBACK", "LEARNING",
         "SELF-IMPROVEMENT")

# ── Estado de validación (contadores reales de uso) ─────────────────────────
# Igual que config.DATA_DIR: backend/data/. La creación del directorio es
# PEREZOSA (en el momento de escribir) y STATE_PATH se lee en CADA llamada,
# así los tests pueden parchear el atributo del módulo (hermético).
STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "skills_state.json"

# tests/ del repo (para verificar que las baterías de regresión existen)
TESTS_DIR = Path(__file__).resolve().parents[2] / "tests"

_IDENT_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


# ═══════════════════════════ REGISTRO (17 skills mínimas) ═══════════════════
# Cada entrada: SKILL_FIELDS + kind + target. Bindings verificados contra el
# repo real (grep + importlib). Fields guidance: version "1.0.0"; confidence
# 0.8 (batería la ejercita) / 0.5 (solo integración); success_rate 0.0 hasta
# primera medición real (mark_validated); origin "registrar_on_first_use".
REGISTRY: list[dict] = [
    {
        "identity": "CREATE_SCRIPT",
        "kind": "SKILL",
        "target": "pipeline.script_gen.from_idea",
        "purpose": "Generar el guion estructurado (título, hook, escenas con "
                   "narration + image_prompt + cta) desde una idea, con reglas "
                   "de retención viral y fallback local de coste $0.",
        "trigger": "Operador o modo fábrica crea un proyecto nuevo desde una "
                   "idea (paso 1 del pipeline).",
        "prerequisites": ["idea o semilla textual", "style_id válido "
                          "(services.themes.get_style)", "formato fmt válido"],
        "procedure": ["resolver estilo y formato",
                      "llamar al LLM con _base_instructions + "
                      "VIRAL_RETENTION_RULES (o fallback local sin key)",
                      "sanitizar escenas (pipeline.sanitizer)",
                      "build_result → JSON estructurado del proyecto"],
        "tools_required": ["services.gemini_client (opcional)",
                           "services.avatar_schema", "services.originality",
                           "services.themes"],
        "expected_result": "dict build_result con título/hook/escenas listas "
                           "para ingest en BD.",
        "verification": "El resultado tiene ≥1 escena con narration + "
                        "image_prompt y pasa el sanitizador sin perder escenas.",
        "pitfalls": ["sin GEMINI_API_KEY usa el fallback local (calidad "
                     "menor): no es un error, es degradación con gracia",
                     "el LLM puede envolver el JSON en cercas markdown → "
                     "parse defensivo"],
        "evidence": "binding real verificado: pipeline/script_gen.py:190 "
                    "(async def from_idea); integración ejercitada por "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "PREPARE_IMAGE_PROMPT",
        "kind": "TOOL",
        "target": "pipeline.flow_export.build_script_json",
        "purpose": "Construir el script.json del export Flow: image_prompt y "
                   "video_prompt por unidad (contrato P1, última escena "
                   "SOLO-imagen por diseño).",
        "trigger": "Antes de encolar jobs o de una prueba real con Google Flow "
                   "(payload del export).",
        "prerequisites": ["proyecto con escenas en BD",
                          "fmt y brand resueltos"],
        "procedure": ["leer proyecto + escenas",
                      "componer bloques de imagen (pool, camera, safeguards)",
                      "componer bloques de video (motion verbatim)",
                      "devolver dict scenes[] con prompts"],
        "tools_required": ["pipeline.flow_export (bloques artesano)"],
        "expected_result": "dict con scenes[]; cada unidad generadora lleva "
                           "image_prompt y video_prompt.",
        "verification": "validate_execution sobre las unidades no reporta "
                        "unidades_bloqueadas (preflight P-PJSON-*).",
        "pitfalls": ["la ÚLTIMA escena es SOLO-imagen por diseño del export: "
                     "no exigirle video_prompt",
                     "el formatter transformacion incrusta image_prompt en "
                     "composition (no duplicar)"],
        "evidence": "binding real verificado: "
                    "pipeline/flow_export.py:761 (def build_script_json); "
                    "ejercitada de verdad por test_golden_fixture.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_golden_fixture.py", "test_doctor_preflight.py"],
    },
    {
        "identity": "GENERATE_IMAGE",
        "kind": "SKILL",
        "target": "pipeline.images.generate_all",
        "purpose": "Producir las imágenes de todas las escenas con 3 rutas: "
                   "Gemini image (primario), cola de la extensión (plan B) y "
                   "placeholder PIL (plan C, nunca bloquea el render).",
        "trigger": "Paso 2 del pipeline, tras el guion.",
        "prerequisites": ["escenas con image_prompt",
                          "OUTPUT_DIR escribible"],
        "procedure": ["por escena: full_prompt (avatar + camera + safeguards)",
                      "ruta primaria Gemini → PNG",
                      "si falla → cola extensión; si falla → placeholder",
                      "registrar método de estilo real por imagen (sidecar)"],
        "tools_required": ["services.gemini_client", "PIL (placeholders)",
                           "database (meta de escenas)"],
        "expected_result": "PNG por escena en OUTPUT_DIR/<pid>/scenes/ + "
                           "método anotado.",
        "verification": "qa_image (video_qa) sin errores por PNG generado.",
        "pitfalls": ["placeholder NO es imagen real: los gates del "
                     "orquestador (_gate_imagenes_reales) lo detectan",
                     "consistencia visual: primera imagen resuelta se usa "
                     "como referencia de estilo de las siguientes"],
        "evidence": "binding real verificado: pipeline/images.py:259 "
                    "(async def generate_all); integración en "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "GENERATE_TTS",
        "kind": "SKILL",
        "target": "pipeline.tts_step.synthesize_scenes",
        "purpose": "Sintetizar la voz de todas las escenas (ruta batched "
                   "Gemini 1 llamada/15 escenas o por escena edge/gemini) y "
                   "alinear palabra a palabra con Whisper → voice_full.wav + "
                   "words.json.",
        "trigger": "Paso 3 del pipeline, tras las imágenes.",
        "prerequisites": ["escenas con narration", "TTS_PROVIDER configurado "
                          "(edge|gemini)"],
        "procedure": ["detectar escenas pendientes (skip-if-exists por hash)",
                      "sintetizar (batched → fallback por escena)",
                      "transcribir con faster-whisper y computar fronteras "
                      "de escena",
                      "split ffmpeg por escena + build_full_track + "
                      "save_words_timeline"],
        "tools_required": ["services.gemini_client", "services.tts_service",
                           "services.whisper_service", "ffmpeg"],
        "expected_result": "voice_full.wav + words.json + WAV por escena; "
                           "idempotente (no re-sintetiza lo existente).",
        "verification": "durations coherentes: sum(duraciones de escena) ≈ "
                        "duración de voice_full (±GAP); words.json no vacío.",
        "pitfalls": ["unidades con tts_skip reciben silencio (no error)",
                     "si el lote batched falla en CUALQUIER punto se cae a la "
                     "ruta por escena: nada queda a medias"],
        "evidence": "binding real verificado: pipeline/tts_step.py:49 (async "
                    "def synthesize_scenes); integración en "
                    "test_autopublish_generate.py + compat tts_skip en "
                    "test_merge_216_pyav.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py",
                             "test_merge_216_pyav.py"],
    },
    {
        "identity": "GENERATE_VIDEO",
        "kind": "TOOL",
        "target": "services.flow_jobs.enqueue_project",
        "purpose": "Encolar los jobs de la cola P1 (imágenes y videos) leyendo "
                   "los prompts ÚNICAMENTE del script.json del export.",
        "trigger": "Al lanzar la producción o re-encolar tras reparación.",
        "prerequisites": ["production.json / script.json válido para el "
                          "proyecto", "cola limpia (sin jobs no-done previos "
                          "del mismo pid)"],
        "procedure": ["validar que el proyecto existe y tiene escenas",
                      "derivar jobs por unidad desde el export",
                      "insertar en la tabla flow_jobs (idempotente)"],
        "tools_required": ["database (tabla flow_jobs)"],
        "expected_result": "dict con jobs creados (created>0) o created=0 si "
                           "ya había cola activa.",
        "verification": "status_for_project refleja los jobs; re-enqueue "
                        "devuelve created=0 (idempotencia).",
        "pitfalls": ["enqueue de proyecto inexistente → error controlado",
                     "no re-encolar encima de una cola viva: interferiría con "
                     "el worker"],
        "evidence": "binding real verificado: services/flow_jobs.py:100 (def "
                    "enqueue_project); ejercitada de verdad por test_flow_"
                    "bridge.py, test_chaos.py y test_10_escenas.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_flow_bridge.py", "test_chaos.py",
                             "test_10_escenas.py"],
    },
    {
        "identity": "GENERATE_SUBTITLES",
        "kind": "TOOL",
        "target": "pipeline.video.burn_subtitles",
        "purpose": "Quemar los subtítulos (timeline words.json) sobre el video "
                   "con el estilo del formato.",
        "trigger": "Paso de postproducción, tras mux de audio y música.",
        "prerequisites": ["video_raw existente", "words.json del proyecto"],
        "procedure": ["construir el filtro subtitles con estilos",
                      "ejecutar ffmpeg sobre el video",
                      "devolver el MP4 subtitulado"],
        "tools_required": ["ffmpeg"],
        "expected_result": "Path del MP4 con subtítulos quemados.",
        "verification": "ffprobe del archivo de salida reporta duración ≈ la "
                        "del video de entrada.",
        "pitfalls": ["rutas con caracteres especiales rompen el filtro → "
                     "escapar / usar cwd seguro",
                     "words.json ausente → sin subtítulos (degradar, no "
                     "revienta)"],
        "evidence": "binding real verificado: pipeline/video.py:275 (async "
                    "def burn_subtitles); integración en "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "ASSEMBLE_VIDEO",
        "kind": "TOOL",
        "target": "pipeline.video.concat_clips",
        "purpose": "Unir los clips de escena en un solo video (concat o "
                   "xfade según formato).",
        "trigger": "Paso de postproducción, tras render_scenes.",
        "prerequisites": ["clips de escena renderizados y listados en orden"],
        "procedure": ["elegir ruta concat o xfade",
                      "ejecutar ffmpeg (demuxer concat / filtros xfade)",
                      "devolver el MP4 ensamblado"],
        "tools_required": ["ffmpeg"],
        "expected_result": "Path del MP4 ensamblado (silencioso, sin música).",
        "verification": "duración del MP4 ≈ suma de clips (tolerancia de "
                        "transiciones).",
        "pitfalls": ["xfade consume duración en las transiciones: la suma no "
                     "es exacta",
                     "clips con resolución distinta → video corrupto: "
                     "render_scenes normaliza antes"],
        "evidence": "binding real verificado: pipeline/video.py:185 (async "
                    "def concat_clips); integración en "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "ADD_MUSIC",
        "kind": "TOOL",
        "target": "pipeline.video.mux_audio_music",
        "purpose": "Mezclar la voz completa con la música de fondo (volumen "
                   "config.MUSIC_VOLUME) y producir el audio final.",
        "trigger": "Paso de postproducción, tras ensamblar el video.",
        "prerequisites": ["video silencioso", "voice_full.wav",
                          "música disponible en MUSIC_DIR"],
        "procedure": ["elegir pista de música (_pick_music)",
                      "mezclar voz + música con ffmpeg (sidechain/volumen)",
                      "mux sobre el video"],
        "tools_required": ["ffmpeg"],
        "expected_result": "Path del MP4 con audio final (voz + música).",
        "verification": "volumedetect: la voz domina sobre la música (max_"
                        "volume coherente); qa_video sin flag de silencio.",
        "pitfalls": ["sin música disponible → mux solo con voz (no error)",
                     "volumen de música por encima de la voz mata la "
                     "inteligibilidad (MUSIC_VOLUME=0.18)"],
        "evidence": "binding real verificado: pipeline/video.py:243 (async "
                    "def mux_audio_music); integración en "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "RENDER_VIDEO",
        "kind": "TOOL",
        "target": "pipeline.video.render_scenes",
        "purpose": "Renderizar cada imagen de escena a clip de video con el "
                   "movimiento Ken Burns 3 fases y la duración objetivo.",
        "trigger": "Paso de render, cuando la cola reporta assets completos.",
        "prerequisites": ["imágenes de escena en disco", "durations "
                          "resueltas por escena"],
        "procedure": ["por escena: scene_clip_cmd (Ken Burns 3 fases) o "
                      "retime del clip de Flow",
                      "cache: si el clip ya existe y es válido, saltar",
                      "ejecutar ffmpeg y devolver clips[]"],
        "tools_required": ["ffmpeg"],
        "expected_result": "lista de Paths de clips 9:16/16:9 normalizados.",
        "verification": "cada clip pasa qa_video (sin negro/azul/silencio "
                        "inesperado).",
        "pitfalls": ["cache de clips: si cambió la imagen hay que invalidar "
                     "(_clip_cache_ok)",
                     "duración 0 o negativa → clip inválido"],
        "evidence": "binding real verificado: pipeline/video.py:124 (async "
                    "def render_scenes); auto-render ejercitado en "
                    "test_10_escenas.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py",
                             "test_10_escenas.py"],
    },
    {
        "identity": "VALIDATE_ASSET",
        "kind": "TOOL",
        "target": "services.production_json.validate_execution",
        "purpose": "Validar el Production JSON en nivel 2 (ejecución): "
                   "unidades bloqueadas, video_prompt faltante, faltantes no "
                   "bloqueantes.",
        "trigger": "Antes de ingest/encolar y en el preflight REAL FLOW.",
        "prerequisites": ["payload parseado (production_json.parse_payload)"],
        "procedure": ["normalizar aliases del contrato (una sola tabla de "
                      "verdad)",
                      "auditar unidad por unidad (image_prompt, video_prompt, "
                      "duration)",
                      "devolver reporte con contadores"],
        "tools_required": ["services.production_json"],
        "expected_result": "dict con unidades_auditadas, unidades_bloqueadas, "
                           "unidades_sin_video_prompt, etc.",
        "verification": "el propio reporte: 0 unidades_bloqueadas → apto para "
                        "cola.",
        "pitfalls": ["los aliases son canónicos: no inventar claves nuevas",
                    "unidad sin image_prompt BLOQUEA (Flow no podría "
                    "ejecutarla)"],
        "evidence": "binding real verificado: "
                    "services/production_json.py:528 (def validate_"
                    "execution); ejercitada de verdad por test_production_"
                    "json.py y test_golden_fixture.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_production_json.py", "test_golden_fixture.py"],
    },
    {
        "identity": "RUN_VIDEO_QA",
        "kind": "SKILL",
        "target": "services.video_qa.qa_project",
        "purpose": "QA forense del proyecto: valida cada asset y el video "
                   "final (ffprobe + PIL + forense de frames: pantalla "
                   "negra/azul, audio silencioso).",
        "trigger": "Tras el render final y bajo demanda del operador.",
        "prerequisites": ["assets del proyecto en disco (escenas y/o final)"],
        "procedure": ["qa_image por imagen de escena",
                      "qa_video por clip y por final (forense de frames al "
                      "25/50/75% + volumedetect)",
                      "agregar peor veredicto → status ok|warn|error"],
        "tools_required": ["ffmpeg/ffprobe", "PIL"],
        "expected_result": "dict de QA con status global, detalle por escena "
                           "y flags forenses; NUNCA lanza.",
        "verification": "status coherente con los flags: warn sin errors; "
                        "HTML disfrazado de MP4 → error sin crash.",
        "pitfalls": ["fade legítimo puede parecer pantalla negra → severidad "
                     "WARN, no bloquea",
                     "proyecto inexistente → error controlado, no excepción"],
        "evidence": "binding real verificado: services/video_qa.py:274 (def "
                    "qa_project); ejercitada de verdad por test_qa_forensics."
                    "py y test_10_escenas.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_qa_forensics.py", "test_10_escenas.py"],
    },
    {
        "identity": "RUN_FLOW_PREFLIGHT",
        "kind": "TOOL",
        "target": "services.production_doctor.preflight.real_flow_preflight",
        "purpose": "Barrera REAL FLOW PREFLIGHT: verifica TODOS los requisitos "
                   "determinísticos antes de gastar una prueba real con Google "
                   "Flow; NUNCA ejecuta Flow ni repara nada.",
        "trigger": "Antes de cualquier prueba real con Flow (regla 8 del "
                   "contrato).",
        "prerequisites": ["backend arrancado (o backend_url dado)",
                          "project_id opcional para checks por proyecto"],
        "procedure": ["checks de herramientas (ffmpeg/ffprobe/PIL) y "
                      "directorios",
                      "checks estructurales de la extensión (manifest, "
                      "host_permissions, archivos, bridge)",
                      "checks de contrato (Production JSON, prompts por "
                      "unidad), cola limpia y estado del proyecto",
                      "veredicto: PASS o REAL FLOW BLOCKED con motivos "
                      "exactos"],
        "tools_required": ["services.doctor (probes)", "database",
                           "services.production_json", "pipeline.flow_export"],
        "expected_result": "dict con verdict, ok, blocked_reasons[] y checks[] "
                           "con estado por check.",
        "verification": "checks bloqueantes todos ok → verdict REAL FLOW "
                        "PREFLIGHT PASS.",
        "pitfalls": ["EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME "
                     "CONNECTED: sin lease vigente la conexión es "
                     "NOT_DEMONSTRATED, JAMÁS PASS",
                     "solo los checks bloqueantes bloquean el veredicto"],
        "evidence": "binding real verificado: "
                    "services/production_doctor/preflight.py:50 (def "
                    "real_flow_preflight — el callable real del módulo; "
                    "'preflight' solo existe como wrapper del paquete); "
                    "ejercitada de verdad por test_doctor_preflight.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_doctor_preflight.py"],
    },
    {
        "identity": "QUEUE_PRODUCTION",
        "kind": "SKILL",
        "target": "pipeline.orchestrator.start_pipeline",
        "purpose": "Lanzar la producción completa: preflight de lanzamiento, "
                   "guion → imágenes → TTS → render → QA (y autopublish si la "
                   "política lo permite).",
        "trigger": "Operador lanza el proyecto o el modo fábrica en su "
                   "horario.",
        "prerequisites": ["proyecto en BD", "sin pipeline activo para el mismo "
                          "project_id", "gates de assets/voz reales "
                          "satisfechos"],
        "procedure": ["registrar job en el orquestador (JOBS + log handler)",
                      "preflight de lanzamiento (_preflight_lanzamiento)",
                      "ejecutar pasos en orden con emisión de progreso",
                      "gates: _gate_imagenes_reales / _gate_voz_real",
                      "al terminar: archivar en biblioteca + desviaciones de "
                      "duración"],
        "tools_required": ["services.production_json", "pipeline.* (pasos)",
                           "services.video_qa", "database"],
        "expected_result": "job_id del orquestador; el pipeline corre en "
                           "background con progreso consultable.",
        "verification": "JOBS[job_id] termina done; QA final ok; video en "
                        "output/ y biblioteca.",
        "pitfalls": ["segundo start_pipeline sobre el mismo proyecto "
                     "interferiría: el preflight lo bloquea",
                     "autopublish respeta FACTORY_AUTOPUBLISH y la política "
                     "de publicación (nivel L3 en autonomy)"],
        "evidence": "binding real verificado: pipeline/orchestrator.py:269 "
                    "(async def start_pipeline); ejercitada de verdad por "
                    "test_lanzar_preflight.py y test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_lanzar_preflight.py",
                             "test_autopublish_generate.py"],
    },
    {
        "identity": "RECOVER_PRODUCTION",
        "kind": "TOOL",
        "target": "services.flow_jobs.recover_expired",
        "purpose": "Recuperar jobs zombie: re-encolar los 'claimed' cuyo lease "
                   "expiró (worker muerto) y devolver cuántos se recuperaron.",
        "trigger": "Al detectar cola atascada o desde DOCTOR FIX "
                   "(reparación recover_expired_leases).",
        "prerequisites": ["cola legible (tabla flow_jobs)"],
        "procedure": ["detectar claimed con lease_until vencido",
                      "devolverlos a queued para otro worker",
                      "retornar el número de jobs recuperados"],
        "tools_required": ["database (tabla flow_jobs)"],
        "expected_result": "int ≥ 0 con la cantidad de jobs re-encolados.",
        "verification": "tras recover, status_for_project no muestra claimed "
                        "con lease vencido.",
        "pitfalls": ["un lease VIGENTE no se toca (el worker puede estar "
                     "vivo: heartbeat)",
                     "recuperar dos veces es inofensivo (idempotente)"],
        "evidence": "binding real verificado: services/flow_jobs.py:165 (def "
                    "recover_expired); ruta de reparación cubierta por "
                    "test_production_doctor.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_production_doctor.py"],
    },
    {
        "identity": "RETRY_FAILED_STEP",
        "kind": "TOOL",
        "target": "services.flow_jobs.fail",
        "purpose": "Marcar un job como fallido con su error real: consume el "
                   "token, incrementa attempts y re-encola si no agotó "
                   "max_attempts (mecanismo de retry).",
        "trigger": "El worker reporta un fallo de generación de asset.",
        "prerequisites": ["job claimed con job_token VIGENTE"],
        "procedure": ["verificar token (claim ya no vale tras fail)",
                      "registrar el error en el job",
                      "attempts < max_attempts → re-encolar; si no → dead"],
        "tools_required": ["database (tabla flow_jobs)"],
        "expected_result": "dict del job actualizado o None si el token es "
                           "inválido/viejo.",
        "verification": "attempts incrementa en 1 por fail; al agotar "
                        "max_attempts el job queda dead.",
        "pitfalls": ["token viejo (zombie) → None: el fail NO aplica",
                     "registrar el error REAL: un error inventado envenena el "
                     "diagnóstico del doctor"],
        "evidence": "binding real verificado: services/flow_jobs.py:350 (def "
                    "fail); ejercitada de verdad por test_chaos.py y "
                    "test_10_escenas.py (fail/retry attempts 1/2).",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_chaos.py", "test_10_escenas.py"],
    },
    {
        "identity": "PUBLISH_VIDEO",
        "kind": "SKILL",
        "target": "services.youtube_publish.upload",
        "purpose": "Publicar el video final en YouTube vía API resumable "
                   "(OAuth de escritorio con retorno loopback).",
        "trigger": "Autopublish del pipeline (si FACTORY_AUTOPUBLISH) o "
                   "publicación manual del operador.",
        "prerequisites": ["client_secret.json en backend/data/",
                          "token OAuth vigente (token.json)",
                          "política de publicación respetada (nivel L3 en "
                          "autonomy)"],
        "procedure": ["verificar credenciales (_credentials)",
                      "subida resumable a YouTube con title/description/tags",
                      "registrar video_id resultante"],
        "tools_required": ["googleapiclient (YouTube Data API v3)"],
        "expected_result": "respuesta de la API con video_id (o error "
                           "controlado si no hay credenciales).",
        "verification": "has_token() y la API acepta la subida; el video "
                        "aparece en la cuenta (readonly scope).",
        "pitfalls": ["sin client_secret.json la skill no está configurada: "
                     "no reintentar en bucle",
                     "PUBLICAR toca el mundo exterior: exige nivel L3 y "
                     "NUNCA puede ser autorizada por self-improvement "
                     "(autonomy.assert_no_bypass)"],
        "evidence": "binding real verificado: services/youtube_publish.py:75 "
                    "(def upload); integración (mock) en "
                    "test_autopublish_generate.py.",
        "version": "1.0.0",
        "confidence": 0.5,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_autopublish_generate.py"],
    },
    {
        "identity": "ANALYZE_PRODUCTION_FAILURE",
        "kind": "SKILL",
        "target": "services.production_doctor.layers.auditar_capas",
        "purpose": "Diagnosticar fallos de producción auditando las 9 capas "
                   "del sistema (A contrato → I render) SOLO LECTURA, "
                   "produciendo findings con causa probable y reparación "
                   "disponible.",
        "trigger": "Cuando una producción falla o el operador pide "
                   "diagnóstico (modo audit del PRODUCTION DOCTOR).",
        "prerequisites": ["repo accesible (REPO_ROOT)",
                          "capas opcionales: lista A-I o None para todas"],
        "procedure": ["ejecutar en orden las funciones audit_* de cada capa "
                      "(audit_input, audit_adapter, audit_export, "
                      "audit_jobs, audit_extension, audit_external, "
                      "audit_assets, audit_qa, audit_render)",
                      "agregar findings tipificados (clase, capa, "
                      "componente, causa probable)",
                      "resumen agregado para el DoctorReport"],
        "tools_required": ["services.production_doctor.core (Finding)",
                           "database", "services.production_json"],
        "expected_result": "lista[Finding] (solo lectura: NUNCA modifica nada "
                           "— reparar es cosa de doctor fix).",
        "verification": "resumen_de(findings) coherente; cada finding lleva "
                        "capa y componente reales.",
        "pitfalls": ["audit es SOLO LECTURA: aplicar reparaciones aquí "
                     "violaría la regla 4 del contrato del doctor",
                     "nota: production_doctor/core.py NO define 'diagnose' — "
                     "el diagnóstico real de capas es auditar_capas "
                     "(layers.py)"],
        "evidence": "binding real verificado: "
                    "services/production_doctor/layers.py:804 (def "
                    "auditar_capas — registro de capas del doctor); "
                    "ejercitada de verdad por test_production_doctor.py.",
        "version": "1.0.0",
        "confidence": 0.8,
        "success_rate": 0.0,
        "origin": "registrar_on_first_use",
        "last_validated": None,
        "regression_tests": ["test_production_doctor.py"],
    },
]

# Identidades canónicas (orden estable para validación externa)
IDENTITIES = tuple(s["identity"] for s in REGISTRY)


# ──────────────────────────────── API pública ────────────────────────────────
def get(identity: str) -> dict | None:
    """Devuelve la skill por identity (dict vivo del registro) o None."""
    for skill in REGISTRY:
        if skill.get("identity") == identity:
            return skill
    return None


def list() -> list[dict]:
    """Devuelve todas las skills registradas (lista nueva, entradas vivas)."""
    # NOTA: no usar el builtin list() aquí — este módulo lo sombrea con su
    # propia API list(); una copia por slicing evita la recursión.
    return REGISTRY[:]


def _resolve_target(target) -> object | None:
    """Resuelve 'paquete.modulo.funcion' con importlib y devuelve el callable
    (o None si el binding no existe). Nota: import_module devuelve SIEMPRE el
    módulo (aunque el paquete sombre el nombre con un atributo del mismo
    nombre, como ocurre con production_doctor.preflight)."""
    if not isinstance(target, str) or "." not in target:
        return None
    mod_path, _, func = target.rpartition(".")
    try:
        mod = importlib.import_module(mod_path)
    except Exception:  # noqa: BLE001 — el gate reporta, no revienta
        return None
    obj = getattr(mod, func, None)
    return obj if callable(obj) else None


def validate_registry() -> dict:
    """PUERTA DE VALIDACIÓN del registro §10. Comprueba que TODA skill:
      1) trae los 16 SKILL_FIELDS (+ kind + target),
      2) declara un kind ∈ KINDS y una identity única en formato
         SCREAMING_SNAKE,
      3) su target es resoluble DE VERDAD con importlib (binding real),
      4) cada test de regresión listado existe en tests/.
    Devuelve {"ok": bool, "errores": [...], "total": n} — nunca lanza."""
    errores: list[str] = []
    vistas: set[str] = set()
    for skill in REGISTRY:
        if not isinstance(skill, dict):
            errores.append(f"entrada no-dict en el registro: {skill!r}")
            continue
        ident = skill.get("identity") or "<sin identity>"
        if ident in vistas:
            errores.append(f"identity duplicada: {ident}")
        vistas.add(ident)
        if not _IDENT_RE.match(str(ident)):
            errores.append(f"{ident}: identity no es SCREAMING_SNAKE")
        for campo in SKILL_FIELDS:
            if campo not in skill:
                errores.append(f"{ident}: falta campo '{campo}' del contrato")
        for extra in ("kind", "target"):
            if extra not in skill:
                errores.append(f"{ident}: falta campo obligatorio '{extra}'")
        if skill.get("kind") not in KINDS:
            errores.append(f"{ident}: kind inválido {skill.get('kind')!r} "
                           f"(no está en KINDS)")
        if _resolve_target(skill.get("target")) is None:
            errores.append(f"{ident}: target no resoluble con importlib: "
                           f"{skill.get('target')!r}")
        for test in skill.get("regression_tests") or []:
            if not (TESTS_DIR / str(test)).exists():
                errores.append(f"{ident}: test de regresión inexistente: "
                               f"{test}")
    return {"ok": not errores, "errores": errores, "total": len(REGISTRY)}


# ── estado de validación (contadores reales, JSON pequeño en backend/data) ──
def _leer_estado() -> dict:
    try:
        data = json.loads(Path(STATE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _escribir_estado(estado: dict) -> None:
    p = Path(STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)  # patrón config.DATA_DIR: perezoso
    p.write_text(json.dumps(estado, ensure_ascii=False, indent=2,
                            sort_keys=True) + "\n", encoding="utf-8")


def mark_validated(identity: str, success: bool) -> dict | None:
    """Registra el resultado de UNA ejecución real de la skill:
      · counters rolling ok/fail en el JSON de estado (STATE_PATH se lee en
        cada llamada → los tests pueden parchearlo),
      · last_validated = ahora (en el registro vivo y en la copia devuelta),
      · success_rate derivado HONESTO: ok/(ok+fail) — 0.0 mientras no haya
        mediciones.
    Devuelve una COPIA actualizada de la skill; None si la identity no existe
    (nunca lanza por skill desconocida)."""
    skill = get(identity)
    if skill is None:
        return None
    estado = _leer_estado()
    reg = estado.get(identity)
    if not isinstance(reg, dict):
        reg = {"ok": 0, "fail": 0}
    clave = "ok" if success else "fail"
    reg[clave] = int(reg.get(clave, 0)) + 1
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg["last_validated"] = ahora
    estado[identity] = reg
    _escribir_estado(estado)
    total = int(reg["ok"]) + int(reg["fail"])
    skill["last_validated"] = reg["last_validated"]
    skill["success_rate"] = round(int(reg["ok"]) / total, 4) if total else 0.0
    return dict(skill)
