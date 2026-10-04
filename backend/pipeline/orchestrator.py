"""
YOUTUBE AUTOMATION v2.0 — Orquestador del pipeline
Ejecuta los 5 pasos en background, publica progreso por SSE y soporta
cancelación. Es el "engine" que consume el dashboard y la fábrica.
"""
import asyncio
import contextvars
import json
import logging
import os
import time
import traceback
from collections import deque
from pathlib import Path

import database as db
from config import OUTPUT_DIR
from pipeline import flow_import, images as imgs
from pipeline import script_gen, tts_step, video
from services import gemini_client, url_mode, whisper_service, youtube_publish
from services import library as library_svc

log = logging.getLogger("orchestrator")


def _archive_library(project_id: str, final_video: Path) -> None:
    """PASO 5b — biblioteca/{nicho}/{titulo}.mp4: carpeta por nicho,
    video por nombre. Nunca tumba el pipeline si falla el archivo."""
    try:
        archived = library_svc.archive(db.get_project(project_id), final_video)
        if archived:
            p = db.get_project(project_id)
            meta = dict(p.get("meta") or {})
            meta["library_path"] = str(archived)
            db.update_project(project_id, meta=meta)
    except Exception as e:  # noqa: BLE001
        log.warning("biblioteca: %s", e)


def _record_duration_deviations(project_id: str) -> None:
    """v2.14 · production_json: duration_target (lo que pidió el Creative
    Engine) vs duración real producida por el pipeline. La desviación queda
    REGISTRADA en la escena (meta.production_unit.duration_actual /
    .duration_deviation) — la duración pedida jamás se reescrita ni se
    silencia la discrepancia. Nunca tumba el pipeline si algo falla."""
    try:
        for sc in db.get_scenes(project_id):
            m = sc.get("meta") or {}
            pu = m.get("production_unit")
            if not isinstance(pu, dict):
                continue
            actual = round(float(sc.get("duration") or 0.0), 3)
            pu["duration_actual"] = actual
            target = pu.get("duration_target")
            if isinstance(target, (int, float)) and target > 0:
                pu["duration_deviation"] = round(actual - float(target), 3)
                if abs(pu["duration_deviation"]) >= 0.05:
                    log.info("production_json %s: unidad %s duración pedida "
                             "%.2fs ≠ real %.2fs (desviación %.2fs registrada)",
                             project_id, pu.get("id"), float(target), actual,
                             pu["duration_deviation"])
            m["production_unit"] = pu
            db.update_scene(sc["id"], meta=m)
    except Exception as e:  # noqa: BLE001
        log.warning("production_json: registro de desviaciones falló: %s", e)


# ── Control de concurrencia de renders (blindaje CPU) ──────────────────
# FFmpeg (zoompan + xfade) usa todos los núcleos: si 2+ proyectos renderizan
# a la vez, el servidor se queda sin CPU y el resto de peticiones sufre.
# El semáforo serializa SOLO la fase de mezcla de video; guion/TTS/imágenes
# de otros proyectos pueden seguir avanzando en paralelo.
try:
    MAX_CONCURRENT_RENDERS = max(1, int(os.getenv("MAX_CONCURRENT_RENDERS", "1")))
except ValueError:
    MAX_CONCURRENT_RENDERS = 1
RENDER_SEM = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)


# ── Broker SSE ────────────────────────────────────────────────────────────
class JobBroker:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}
        # historial por job para REPLAY: un cliente que conecta tarde (o se
        # reconecta a mitad del pipeline) recibe primero lo ya emitido
        # (patrón JobWriter de AI-Content-Automation-Engine, sin websockets)
        self.history: dict[str, deque] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=400)
        self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        lst = self._subs.get(job_id, [])
        if q in lst:
            lst.remove(q)

    def replay(self, job_id: str) -> list[dict]:
        return list(self.history.get(job_id, ()))

    def detach_history(self, job_id: str) -> None:
        self.history.pop(job_id, None)

    def _deliver(self, job_id: str, event: dict) -> None:
        if event.get("type") in ("log", "progress"):
            self.history.setdefault(job_id, deque(maxlen=400)).append(event)
        for q in list(self._subs.get(job_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def publish(self, job_id: str, event: dict) -> None:
        self._deliver(job_id, event)

    def publish_now(self, job_id: str, event: dict) -> None:
        """Versión síncrona para logging.Handler.emit (mismo hilo del loop;
        put_nowait no bloquea y QueueFull se descarta)."""
        self._deliver(job_id, event)


broker = JobBroker()

# contexto del job activo (async-safe: cada tarea establece su job_id y
# asyncio.to_thread hereda el contexto — los logs de hilos worker también
# llegan al job correcto)
current_job: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_job", default="")


class JobLogHandler(logging.Handler):
    """JobWriter (patrón AI-Content-Automation-Engine): captura los logs de
    pipeline.* y services.* y los emite por SSE como eventos type="log" →
    el dashboard muestra un terminal en vivo del pipeline sin websockets."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            job_id = current_job.get()
            if not job_id:
                return
            broker.publish_now(job_id, {
                "type": "log", "job_id": job_id,
                "level": record.levelname.lower(),
                "logger": record.name,
                "message": record.getMessage(),
                "ts": time.strftime("%H:%M:%S")})
        except Exception:  # noqa: BLE001  (un handler de log NUNCA falla)
            pass


_job_log_handler = JobLogHandler(level=logging.INFO)
_log_handler_installed = False


def install_log_handler() -> None:
    """Idempotente: conecta el JobLogHandler a los loggers pipeline/services
    y garantiza nivel INFO para que el terminal SSE vea detalle."""
    global _log_handler_installed
    if _log_handler_installed:
        return
    _log_handler_installed = True
    for name in ("pipeline", "services"):
        lg = logging.getLogger(name)
        lg.addHandler(_job_log_handler)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)


install_log_handler()

# Registro en memoria: job_id → {"task": Task, "cancelled": bool}
JOBS: dict[str, dict] = {}


def is_cancelled(job_id: str):
    return lambda: JOBS.get(job_id, {}).get("cancelled", False)


def cancel_job(job_id: str) -> bool:
    info = JOBS.get(job_id)
    if not info:
        return False
    info["cancelled"] = True
    task: asyncio.Task | None = info.get("task")
    if task and not task.done():
        task.cancel()
    return True


# ── emisión de progreso ───────────────────────────────────────────────────
async def _emit(job_id: str, project_id: str, step: str, pct: int, msg: str,
                extra: dict | None = None) -> None:
    db.update_job(job_id, step=step, progress=pct, message=msg)
    db.update_project(project_id, status=step if step != "done" else "ready",
                      progress=pct, step_label=msg,
                      **({"error": None} if step != "failed" else {}))
    await broker.publish(job_id, {"type": "progress", "job_id": job_id,
                                  "project_id": project_id, "step": step,
                                  "pct": pct, "message": msg, **(extra or {})})


# ── inicio ────────────────────────────────────────────────────────────────
def _zombie_job(active: dict | None) -> bool:
    """True si el job 'running' de la BD no tiene tarea viva en ESTE proceso.

    Los jobs no sobreviven a un crash/reinicio del servidor, pero su fila queda
    status='running' en SQLite: start_pipeline devolvería ese job fantasma para
    siempre y el proyecto quedaría atascado (bug detectado tras un SIGKILL del
    servidor con un render a medias)."""
    if not active:
        return False
    reg = JOBS.get(active.get("id", ""))
    return not (reg and reg.get("task"))


# ── preflight de lanzamiento: barrera «draft → ejecución» ────────────────
def _preflight_lanzamiento(project_id: str) -> None:
    """Revalida el Production JSON almacenado ANTES de crear el job.

    submit_production_json(lanzar=false) conserva a propósito drafts con
    unidades incompletas (p. ej. sin image_prompt) — el reporte queda en
    meta.production_json.validacion_ejecucion. Pero cuando ese draft pasa a
    ejecución (MCP lanzar_proyecto, API /generate, scheduler, agent…), el
    pipeline SÍ exige esos datos creativos. Aquí se revalida el original
    guardado en data/output/<pid>/production.json con
    production_json.validate_execution (nivel 2) — la MISMA política que la
    ingesta aplica en auto_start: si hay unidades bloqueantes NO se crea
    job y se lanza ValueError con el detalle unidad por unidad.

    Proyectos sin production.json (modos idea / guion_json / nicho / legacy,
    o cuyo original fue borrado del disco) no se ven afectados: no hay
    contrato Production JSON que comprobar y su puerta ya validó lo suyo.
    Si production.json existe pero no puede releerse, se registra aviso y
    se continúa: el pipeline ejecuta desde BD y un archivo de trazabilidad
    dañado no debe tumbar el lanzamiento.
    """
    pfile = OUTPUT_DIR / project_id / "production.json"
    if not pfile.exists():
        return
    # import diferido (mismo patrón que production_json.ingest): no hay
    # círculo a nivel de módulo y la carga de orchestrator sigue ligera
    from services import production_json as production_svc
    try:
        data = production_svc.parse_payload(pfile.read_bytes())
    except ValueError as e:
        log.warning("preflight lanzamiento %s: production.json ilegible (%s) "
                    "— no se puede revalidar; se continúa", project_id, e)
        return
    reporte = production_svc.validate_execution(data)
    bloqueadas = int(reporte.get("unidades_bloqueadas") or 0)
    if not bloqueadas:
        return
    faltantes = []
    for item in reporte.get("unidades_con_faltantes", []):
        for f in item.get("faltantes", []):
            if f.get("bloqueante"):
                faltantes.append(f"{item['unidad']} ({item['id']}): {f['campo']}")
    raise ValueError(
        f"no se puede lanzar el proyecto {project_id}: el Production JSON "
        f"almacenado tiene {bloqueadas} unidad(es) bloqueada(s) para la "
        f"ejecución actual — faltan datos creativos: " + "; ".join(faltantes)
        + ". El Adapter no inventa prompts: completa el Production JSON "
          "desde el Creative Engine, vuelve a hacer submit_production_json "
          "y lanza de nuevo."
    )


async def start_pipeline(project_id: str, autopublish: bool = False) -> str:
    project = db.get_project(project_id)
    if not project:
        raise ValueError("proyecto no existe")
    active = db.active_job_for_project(project_id)
    if _zombie_job(active):
        # job huérfano de un proceso muerto → fallarlo y relanzar limpio
        db.update_job(active["id"], status="failed",
                      error="interrumpido por reinicio del servidor")
        active = None
    if active:
        return active["id"]  # ya hay un pipeline corriendo

    # preflight: un draft de Production JSON con unidades incompletas no
    # puede pasar a ejecución (misma barrera que la ingesta en auto_start).
    # No-op para proyectos sin production.json (idea/guion_json/legacy).
    _preflight_lanzamiento(project_id)

    job_id = db.create_job(project_id, kind="pipeline")
    JOBS[job_id] = {"task": None, "cancelled": False}
    task = asyncio.create_task(_run(job_id, project_id, autopublish))
    JOBS[job_id]["task"] = task
    task.add_done_callback(lambda t: _job_done(job_id, t))
    return job_id


async def start_flow_render(project_id: str) -> str:
    """Renderiza con los assets REALES importados de Flow (sin regenerar guion ni imágenes).

    Saltos: PASO 0-2 del pipeline normal. Ejecuta TTS → alineación → Ken Burns
    → mezcla → subtítulos → thumbnail, usando scene.image_path tal cual está en BD.
    """
    project = db.get_project(project_id)
    if not project:
        raise ValueError("proyecto no existe")
    active = db.active_job_for_project(project_id)
    if _zombie_job(active):
        db.update_job(active["id"], status="failed",
                      error="interrumpido por reinicio del servidor")
        active = None
    if active:
        return active["id"]

    job_id = db.create_job(project_id, kind="flow_render")
    JOBS[job_id] = {"task": None, "cancelled": False}
    task = asyncio.create_task(_run_flow_render(job_id, project_id))
    JOBS[job_id]["task"] = task
    task.add_done_callback(lambda t: _job_done(job_id, t))
    return job_id


def _job_done(job_id: str, task: asyncio.Task) -> None:
    """Limpieza al terminar el job: registro en memoria e historial SSE
    (los datos finales viven en BD; el historial solo sirve en vivo)."""
    JOBS.pop(job_id, None)
    broker.detach_history(job_id)


async def _run_flow_render(job_id: str, project_id: str) -> None:
    token = current_job.set(job_id)
    try:
        log.info("flow_render iniciado (proyecto %s)", project_id)
        scenes = db.get_scenes(project_id)
        if not scenes:
            raise RuntimeError("El proyecto no tiene escenas")
        faltan_img = [i + 1 for i, sc in enumerate(scenes) if not sc.get("image_path")
                      or not Path(str(sc["image_path"])).exists()]
        if faltan_img:
            raise RuntimeError(f"Escenas sin imagen de Flow: {faltan_img}. "
                               "Importa el ZIP de Escena_XX primero.")
        db.update_project(project_id, status="processing", error=None,
                          step_label="Render Flow", progress=50)
        await _emit(job_id, project_id, "tts", 50, "Sintetizando voz (assets Flow)…")

        async def tts_prog(i, total, used):
            await _emit(job_id, project_id, "tts", 50 + int(20 * i / total),
                        f"Locución {i}/{total} ({used})")

        durations, words_per_scene = await tts_step.synthesize_scenes(
            db.get_project(project_id), scenes, tts_prog, is_cancelled(job_id))
        _gate_voz_real(project_id, db.get_scenes(project_id))
        await _emit(job_id, project_id, "align", 72, "Alineando palabras (Whisper)…")
        voice_full = await tts_step.build_full_track(db.get_project(project_id), durations)
        words_path = tts_step.save_words_timeline(db.get_project(project_id),
                                                  words_per_scene)
        meta = {**(db.get_project(project_id).get("meta") or {}), "durations": durations}
        db.update_project(project_id, meta=meta)

        await _emit(job_id, project_id, "render", 76,
                    "Renderizando escenas Flow (video real + Ken Burns)…")
        # Videos REALES de Flow (Veo) con retime setpts a la narración;
        # fallback automático a Ken Burns por escena sin video.
        flow_videos = flow_import.find_flow_videos(
            OUTPUT_DIR / project_id, list(range(len(scenes))))
        if flow_videos:
            await _emit(job_id, project_id, "render", 77,
                        f"Usando {len(flow_videos)} clip(s) reales de Flow (retime)…")
        transitions = bool((db.get_project(project_id).get("meta") or {}).get("transitions", True))
        async with RENDER_SEM:  # 1 mezcla de video a la vez (blindaje CPU)
            clips = await video.render_scenes(
                db.get_project(project_id), scenes, durations,
                None, is_cancelled(job_id),
                flow_videos=flow_videos or None,
                transition_pad=video.TRANSITION_DUR if transitions else 0.0)
            await _emit(job_id, project_id, "render", 82, "Uniendo clips…")
            silent = await video.concat_clips(db.get_project(project_id), clips,
                                              transition="fade" if transitions else None)
            await _emit(job_id, project_id, "render", 86, "Mezclando voz y música…")
            raw_video = await video.mux_audio_music(db.get_project(project_id),
                                                    silent, voice_full)
        await _emit(job_id, project_id, "subtitles", 90, "Quemando subtítulos Hormozi…")
        final = await video.burn_subtitles(db.get_project(project_id), raw_video, words_path)
        thumb = video.make_thumbnail(db.get_project(project_id), scenes[0].get("image_path"))

        total_dur = sum(durations)
        db.update_project(project_id, status="ready", progress=100,
                          step_label="Listo (Flow)", video_url=str(final),
                          thumbnail_url=str(thumb) if thumb else None)
        _archive_library(project_id, final)
        db.update_job(job_id, status="done", progress=100, step="done",
                      message=f"Video Flow listo · {total_dur:.0f}s")
        if os.getenv("KEEP_INTERMEDIATES", "0") != "1":  # libera el disco
            video.cleanup_intermediates(project_id)
        await broker.publish(job_id, {
            "type": "done", "job_id": job_id, "project_id": project_id,
            "video_url": f"/api/projects/{project_id}/video",
            "thumbnail_url": f"/api/projects/{project_id}/thumbnail",
            "duration": total_dur,
            "message": f"¡Video con assets Flow listo en {total_dur:.0f}s!"})
    except asyncio.CancelledError:
        db.update_job(job_id, status="cancelled", step="cancelled",
                      message="Cancelado por el usuario")
        db.update_project(project_id, status="failed", step_label="Cancelado",
                          error="cancelado")
        await broker.publish(job_id, {"type": "cancelled", "job_id": job_id,
                                      "project_id": project_id})
    except Exception as e:  # noqa: BLE001
        log.error("flow_render %s: %s\n%s", job_id, e, traceback.format_exc())
        db.update_job(job_id, status="failed", step="failed", error=str(e)[:500],
                      message=f"Error: {str(e)[:120]}")
        db.update_project(project_id, status="failed", error=str(e)[:500],
                          step_label="Error")
        await broker.publish(job_id, {"type": "error", "job_id": job_id,
                                      "project_id": project_id,
                                      "message": str(e)[:200]})
    finally:
        current_job.reset(token)


# ── gates de producto real (anti «video morado mudo marcado ready») ──────
# El pipeline degradaba en silencio: placeholder PIL cuando todos los
# proveedores de imagen fallaban y silencio cuando TTS fallaba, llegando a
# 100%/ready con un producto inutilizable. Estos gates hacen que el Builder
# FALLE con causa accionable cuando el producto sería degradado en su
# totalidad (100%). Una degradación PARCIAL (algunas escenas) no detiene el
# render: se registra warning en el log (el gate no falso-fracasa productos
# con 1 escena degradada de N).

def _gate_imagenes_reales(project_id: str, scenes: list[dict]) -> None:
    """Falla si TODAS las escenas quedaron con imagen placeholder PIL."""
    metodos: list[str] = []
    for sc in scenes:
        p = sc.get("image_path")
        if not p:
            continue
        sf = Path(str(p)).with_suffix(".style.json")
        try:
            metodo = (json.loads(sf.read_text()) or {}).get("method") or "?"
        except Exception:  # noqa: BLE001 — sin style.json no se puede saber
            metodo = "?"
        metodos.append(metodo)
    if not metodos:
        return
    n_ph = sum(1 for m in metodos if m == "placeholder")
    if n_ph == len(metodos):
        raise RuntimeError(
            f"Preflight de producto: TODAS las imágenes ({len(metodos)}) son "
            "placeholder — el video sería un degradado sin contenido real. "
            "Causas posibles: GEMINI_API_KEY ausente/inválida o sin cuota, "
            "CLI z-ai no instalado y sin capturas de la extensión. Configura "
            "un proveedor de imágenes real y relanza el proyecto.")
    if n_ph:
        log.warning("preflight imágenes: degradación parcial %d/%d placeholder "
                    "(el render continúa)", n_ph, len(metodos))


def _gate_voz_real(project_id: str, scenes: list[dict]) -> None:
    """Falla si hay texto hablado y TODAS las pistas con texto quedaron mudas.

    Un proyecto sin texto (b-roll + música) es legítimo y NO dispara el gate.
    """
    con_texto = [sc for sc in scenes
                 if not (sc.get("meta") or {}).get("tts_skip")]
    if not con_texto:
        return
    mudas = [sc for sc in con_texto
             if (sc.get("meta") or {}).get("tts") in ("silent", "silence")]
    if len(mudas) == len(con_texto):
        raise RuntimeError(
            f"Preflight de producto: {len(con_texto)} escena(s) con texto "
            "quedaron SIN voz real (100% silencio) — el video sería mudo. "
            "Causas posibles: red bloqueada hacia el proveedor TTS o "
            "TTS_PROVIDER mal configurado. Revisa conectividad/cuota y "
            "relanza el proyecto.")
    if mudas:
        log.warning("preflight voz: degradación parcial %d/%d escenas mudas "
                    "(el render continúa)", len(mudas), len(con_texto))


# ── pipeline completo ─────────────────────────────────────────────────────
async def _run(job_id: str, project_id: str, autopublish: bool) -> None:
    token = current_job.set(job_id)
    project = db.get_project(project_id)
    try:
        log.info("pipeline iniciado (proyecto %s, modo %s)",
                 project_id, project.get("mode", "?"))
        # PASO 0 — material de origen según modo
        meta = project.get("meta") or {}
        viral_ctx = None
        # contratos (guion_json/production_json): no hay `result` del
        # guionista LLM; el título de publicación vive en el proyecto
        result = None

        # Avatar (personaje consistente): se carga una vez y se inyecta en
        # meta para guion (personalidad) e imágenes (apariencia estable).
        avatar = None
        if project.get("avatar_id"):
            avatar = db.get_avatar(project["avatar_id"])
            if avatar:
                meta["avatar"] = {"name": avatar["name"],
                                  "description": avatar.get("description", ""),
                                  "appearance": avatar.get("appearance") or {}}
                db.update_project(project_id, meta=meta)

        if project["mode"] == "url" and meta.get("source_url"):
            await _emit(job_id, project_id, "importing", 3,
                        "Descargando audio del video viral…")
            base = f"url_{project_id}"
            viral_ctx = await url_mode.transcript_from_url(
                meta["source_url"], base,
                cookies=meta.get("cookies_from_browser"))
            await _emit(job_id, project_id, "importing", 8,
                        f"Viral detectado: {viral_ctx['metadata'].get('title', '')[:50]}")

        elif project["mode"] == "audio" and meta.get("audio_path"):
            await _emit(job_id, project_id, "importing", 5,
                        "Transcribiendo tu voz con Whisper…")
            words = await whisper_service.transcribe_words(meta["audio_path"])
            if words:
                text = " ".join(w["word"] for w in words)
            else:
                text = meta.get("audio_text", "")
            if not text.strip():
                raise RuntimeError("No se pudo transcribir el audio (¿instalaste faster-whisper?)")
            meta["audio_text"] = text
            db.update_project(project_id, meta=meta)

        # PASO 1 — guion (o guion ya ingerido vía contrato guion_json)
        if project["mode"] == "guion_json":
            # v2.10 · contrato guion_json: las escenas ya están en BD
            # (services/guion_json.py las ingesta SIN LLM interno) — la
            # fábrica NO regenera nada: imágenes, TTS y montaje directos.
            scenes = db.get_scenes(project_id)
            if not scenes:
                raise RuntimeError("guion_json sin escenas en la base de datos")
            await _emit(job_id, project_id, "scripting", 18,
                        f"Guion externo listo: {len(scenes)} escenas · "
                        f"«{project['title']}» (contrato guion_json)",
                        {"title": project["title"]})
        elif project["mode"] == "production_json":
            # v2.14 · Creative Production JSON (Creative Engine → Adapter):
            # las unidades ya están traducidas a escenas en BD por
            # services/production_json.py SIN LLM interno — la fábrica NO
            # regenera nada; lo específico del nicho vive en scenes.meta.
            scenes = db.get_scenes(project_id)
            if not scenes:
                raise RuntimeError("production_json sin escenas en la base de datos")
            await _emit(job_id, project_id, "scripting", 18,
                        f"Production JSON listo: {len(scenes)} unidades · "
                        f"«{project['title']}» (Creative Engine → Adapter)",
                        {"title": project["title"]})
        else:
            if project["mode"] == "script" and meta.get("script_text"):
                raw = await script_gen.from_script(
                    meta["script_text"], project["style"], project["format"],
                    meta.get("custom_style_prompt"), avatar)
            elif project["mode"] == "url" and viral_ctx:
                raw = await script_gen.from_url_transcript(
                    viral_ctx["metadata"], viral_ctx["transcript"],
                    project["style"], project["format"], meta.get("custom_style_prompt"),
                    avatar)
            elif project["mode"] == "audio" and meta.get("audio_text"):
                raw = await script_gen.from_audio_transcript(
                    meta["audio_text"], project["style"], project["format"],
                    meta.get("custom_style_prompt"), avatar)
            else:
                await _emit(job_id, project_id, "scripting", 10, "Generando guion viral…")
                raw = await script_gen.from_idea(
                    meta.get("idea") or project["title"], project["style"],
                    project["format"], meta.get("custom_style_prompt"), avatar)

            result = script_gen.build_result(raw)
            if not result["scenes"]:
                raise RuntimeError("Gemini devolvió un guion vacío")
            # originalidad verificable del modo URL: el informe del guion
            # (overlap de 5-gramas contra la transcripción) queda en meta
            if result.get("originality"):
                meta = {**(db.get_project(project_id).get("meta") or {}),
                        "originality": result["originality"]}
                db.update_project(project_id, meta=meta)
                rep = result["originality"]
                await _emit(job_id, project_id, "scripting", 17,
                            f"Originalidad {100 - rep['overlap'] * 100:.0f}% "
                            f"(solape {rep['overlap'] * 100:.0f}%"
                            + (", relanzado anti-copia" if rep.get("retried") else "")
                            + ")")
            db.replace_scenes(project_id, result["scenes"])
            db.update_project(project_id, title=result["title"])
            scenes = db.get_scenes(project_id)
            n = len(scenes)
            await _emit(job_id, project_id, "scripting", 18,
                        f"Guion listo: {n} escenas · «{result['title']}»"
                        + (" · MODO DEMO $0" if result.get("engine") == "local-demo" else ""),
                        {"title": result["title"]})

        # PASO 2 — imágenes (híbridas)
        async def img_prog(i, total, method):
            m = f" [{method}]" if method and method != "gemini" else ""
            await _emit(job_id, project_id, "images",
                        18 + int(32 * i / total),
                        f"Generando imágenes {i}/{total}{m}")

        await _emit(job_id, project_id, "images", 20, "Generando imágenes…")
        await imgs.generate_all(db.get_project(project_id), scenes, img_prog,
                                is_cancelled(job_id))
        scenes = db.get_scenes(project_id)
        _gate_imagenes_reales(project_id, scenes)

        # PASO 3 — TTS + alineación
        async def tts_prog(i, total, used):
            await _emit(job_id, project_id, "tts", 50 + int(20 * i / total),
                        f"Locución {i}/{total} ({used})")

        await _emit(job_id, project_id, "tts", 50, "Sintetizando voz…")
        durations, words_per_scene = await tts_step.synthesize_scenes(
            db.get_project(project_id), scenes, tts_prog, is_cancelled(job_id))
        scenes = db.get_scenes(project_id)
        _gate_voz_real(project_id, scenes)

        await _emit(job_id, project_id, "align", 72, "Alineando palabras (Whisper)…")
        voice_full = await tts_step.build_full_track(db.get_project(project_id), durations)
        words_path = tts_step.save_words_timeline(db.get_project(project_id),
                                                  words_per_scene)
        meta = {**(db.get_project(project_id).get("meta") or {}), "durations": durations}
        db.update_project(project_id, meta=meta)
        if project["mode"] == "production_json":
            _record_duration_deviations(project_id)

        # PASO 4 — render (con transiciones xfade y pad compensado para
        # mantener la sincronía exacta con la pista de voz)
        await _emit(job_id, project_id, "render", 76, "Renderizando escenas (Ken Burns + transiciones)…")
        transitions = bool((db.get_project(project_id).get("meta") or {}).get("transitions", True))
        async with RENDER_SEM:  # 1 mezcla de video a la vez (blindaje CPU)
            clips = await video.render_scenes(
                db.get_project(project_id), scenes, durations,
                None, is_cancelled(job_id),
                transition_pad=video.TRANSITION_DUR if transitions else 0.0)
            await _emit(job_id, project_id, "render", 82, "Uniendo clips…")
            silent = await video.concat_clips(db.get_project(project_id), clips,
                                              transition="fade" if transitions else None)
            await _emit(job_id, project_id, "render", 86, "Mezclando voz y música…")
            raw_video = await video.mux_audio_music(db.get_project(project_id),
                                                    silent, voice_full)

        # PASO 5 — subtítulos + thumbnail
        await _emit(job_id, project_id, "subtitles", 90, "Quemando subtítulos Hormozi…")
        final = await video.burn_subtitles(db.get_project(project_id), raw_video, words_path)
        thumb = video.make_thumbnail(db.get_project(project_id), scenes[0].get("image_path"))

        total_dur = sum(durations)
        db.update_project(project_id, status="ready", progress=100,
                          step_label="Listo", video_url=str(final),
                          thumbnail_url=str(thumb) if thumb else None)
        _archive_library(project_id, final)
        db.update_job(job_id, status="done", progress=100, step="done",
                      message=f"Video listo · {total_dur:.0f}s")
        if os.getenv("KEEP_INTERMEDIATES", "0") != "1":  # libera el disco
            video.cleanup_intermediates(project_id)
        await broker.publish(job_id, {
            "type": "done", "job_id": job_id, "project_id": project_id,
            "video_url": f"/api/projects/{project_id}/video",
            "thumbnail_url": f"/api/projects/{project_id}/thumbnail",
            "duration": total_dur,
            "message": f"¡Video listo en {total_dur:.0f}s!"})

        # PASO 6 — autopublicar (opcional)
        if autopublish:
            await _emit(job_id, project_id, "publishing", 97, "Subiendo a YouTube…")
            try:
                vid = youtube_publish.upload(
                    str(final), (result or project)["title"],
                    description=_description(result or {}, project),
                    tags=_tags(project),
                    private=True)
                db.update_project(project_id, status="published", youtube_id=vid)
                await broker.publish(job_id, {"type": "published",
                                              "project_id": project_id,
                                              "youtube_id": vid})
            except Exception as e:  # noqa: BLE001
                log.error("autopublish: %s", e)
                await _emit(job_id, project_id, "ready", 100,
                            f"Listo (autopublish falló: {str(e)[:80]})")

    except asyncio.CancelledError:
        db.update_job(job_id, status="cancelled", step="cancelled",
                      message="Cancelado por el usuario")
        db.update_project(project_id, status="failed", step_label="Cancelado",
                          error="cancelado")
        await broker.publish(job_id, {"type": "cancelled", "job_id": job_id,
                                      "project_id": project_id})
    except Exception as e:  # noqa: BLE001
        log.error("pipeline %s: %s\n%s", job_id, e, traceback.format_exc())
        db.update_job(job_id, status="failed", step="failed", error=str(e)[:500],
                      message=f"Error: {str(e)[:120]}")
        db.update_project(project_id, status="failed", error=str(e)[:500],
                          step_label="Error")
        await broker.publish(job_id, {"type": "error", "job_id": job_id,
                                      "project_id": project_id,
                                      "message": str(e)[:200]})
    finally:
        current_job.reset(token)


def _description(result: dict, project: dict) -> str:
    desc = f"{result.get('hook', '')}\n\n"
    desc += "🎬 Creado con YT Automation v2.0 — pipeline 100% IA\n"
    desc += f"#shorts #viral #{project.get('style', '').replace('-', '')}"
    return desc


def _tags(project: dict) -> list[str]:
    from services.themes import get_style
    base = ["shorts", "viral", "ia", "historias"]
    base.append(project.get("style", ""))
    base.append(get_style(project.get("style", ""))["name"].lower().replace(" ", ""))
    return base
