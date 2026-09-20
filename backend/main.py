"""
YOUTUBE AUTOMATION v2.0 — Servidor principal (FastAPI)
Dashboard en http://127.0.0.1:8000  ·  progreso por SSE  ·  coste $0/video
"""
import asyncio
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path

import config
import database as db
from config import DATA_DIR, HOST, OUTPUT_DIR, PORT, TMP_DIR
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pipeline import images as imgs_pipeline
from pipeline import orchestrator
from pipeline.subtitles import words_to_srt
from services import (gemini_client, scheduler, tts_service, url_mode,
                      whisper_service, youtube_publish)
from services.themes import STYLES, get_style

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="YT Automation v2.0", version="2.0.0")


@app.middleware("http")
async def no_cache_ui(request, call_next):
    """El dashboard (HTML/JS/CSS) siempre se revalida: evita que el navegador
    se quede con una versión vieja de la interfaz sin claves ni botones nuevos."""
    resp = await call_next(request)
    p = request.url.path
    if p.startswith("/static") or p in ("/", "/app", "/app/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

# ────────────────────────────────────────────────────────── básicos ──
@app.get("/api/health")
async def health():
    return {"ok": True, "version": "2.0.0", "gemini": gemini_client.available(),
            "whisper": whisper_service.available(),
            "youtube": youtube_publish.configured()}


@app.get("/api/styles")
async def styles():
    return STYLES


@app.get("/api/settings")
async def settings():
    return {
        "gemini_key": gemini_client.available(),
        "tts_provider": config.TTS_PROVIDER,
        "whisper": whisper_service.available(),
        "youtube_configured": youtube_publish.configured(),
        "youtube_token": youtube_publish.has_token(),
        "edge_voices": [
            {"id": "es-CO-SalomeNeural", "name": "Salomé (Colombia)"},
            {"id": "es-ES-ElviraNeural", "name": "Elvira (España)"},
            {"id": "es-MX-JorgeNeural", "name": "Jorge (México)"},
            {"id": "es-US-AlonsoNeural", "name": "Alonso (US Latino)"},
            {"id": "es-AR-ElenaNeural", "name": "Elena (Argentina)"},
        ],
        "gemini_voices": [
            {"id": "Fenrir", "name": "Fenrir — narrador épico"},
            {"id": "Puck", "name": "Puck — energético"},
            {"id": "Kore", "name": "Kore — femenina cálida"},
            {"id": "Charon", "name": "Charon — documental"},
            {"id": "Aoede", "name": "Aoede — juvenil"},
        ],
    }


# ─────────────────────────────── configuración desde el dashboard ──
def _mask(secret: str) -> str:
    if not secret:
        return ""
    return f"{secret[:6]}…{secret[-4:]}" if len(secret) > 14 else "•••"


@app.get("/api/config")
async def get_config():
    """Vista de configuración para ⚙️ Ajustes. Los secretos van enmascarados."""
    return {
        "env_path": str(config.ENV_PATH),
        "env_exists": config.ENV_PATH.exists(),
        "gemini_key_set": gemini_client.available(),
        "gemini_key_masked": _mask(config.GEMINI_API_KEY),
        "tts_provider": config.TTS_PROVIDER,
        "edge_tts_voice": config.EDGE_TTS_VOICE,
        "gemini_tts_voice": config.GEMINI_TTS_VOICE,
        "tts_rate": config.TTS_RATE,
        "whisper_model": config.WHISPER_MODEL,
        "whisper_device": config.WHISPER_DEVICE,
        "whisper_available": whisper_service.available(),
        "fps": config.FPS,
        "youtube_configured": youtube_publish.configured(),
        "youtube_token": youtube_publish.has_token(),
        "ext_pending": db.count_ext_images(),
    }


@app.post("/api/config")
async def save_config(body: dict):
    """Guarda claves/ajustes en .env y aplica los cambios AL INSTANTE
    (sin reiniciar el servidor)."""
    updates: dict[str, str] = {}
    for key, value in (body or {}).items():
        if key not in config.EDITABLE_KEYS:
            continue
        val = str(value).strip()
        if key == "GEMINI_API_KEY":
            # Enmascarado (el input placeholder) = NO tocar la clave guardada.
            # Vacío = borrado explícito (botón "Quitar clave").
            if val.startswith("•") or "…" in val:
                continue
            updates[key] = val
            continue
        if not val:
            continue
        if key == "TTS_PROVIDER" and val not in ("edge", "gemini"):
            raise HTTPException(400, "TTS_PROVIDER debe ser 'edge' o 'gemini'")
        if key == "FPS":
            try:
                if not (12 <= int(val) <= 60):
                    raise ValueError
            except ValueError:
                raise HTTPException(400, "FPS debe ser un número entre 12 y 60")
        if key == "TTS_RATE":
            try:
                pct = int(val.replace("%", "").replace("+", ""))
                if not (-50 <= pct <= 100):
                    raise ValueError
                val = f"{'+' if pct >= 0 else ''}{pct}%"
            except ValueError:
                raise HTTPException(400, "TTS_RATE debe ser tipo +8% o -10%")
        if key == "WHISPER_MODEL" and val not in ("tiny", "base", "small", "medium"):
            raise HTTPException(400, "modelo Whisper inválido")
        if key == "WHISPER_DEVICE" and val not in ("cpu", "cuda"):
            raise HTTPException(400, "dispositivo Whisper inválido")
        updates[key] = val
    if not updates:
        raise HTTPException(400, "nada que guardar")
    saved = config.save_env(updates)
    return {
        "ok": True, "saved": saved,
        "gemini": gemini_client.available(),
        "tts_provider": config.TTS_PROVIDER,
        "message": "Configuración guardada y aplicada al instante",
    }


@app.post("/api/config/test-gemini")
async def test_gemini():
    """Prueba la clave de Gemini con una llamada real mínima."""
    if not gemini_client.available():
        return {"ok": False, "error": "No hay ninguna clave configurada"}
    try:
        txt = await gemini_client.generate_text("Responde únicamente: OK")
        return {"ok": True, "reply": (txt or "").strip()[:40] or "OK"}
    except Exception as e:  # noqa: BLE001
        msg = str(e)[:300]
        if "API key not valid" in msg or "API_KEY_INVALID" in msg:
            msg = "La clave no es válida — revisa que la copiaste completa"
        elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            msg = "Clave válida, pero sin cuota disponible ahora (reintenta luego)"
        elif "not found" in msg.lower() or "ModuleNotFoundError" in msg:
            msg = f"Falta la librería google-genai: pip install google-genai · {msg[:150]}"
        return {"ok": False, "error": msg}


@app.post("/api/config/client-secret")
async def upload_client_secret(file: UploadFile = File(...)):
    """Sube el client_secret.json de YouTube desde el dashboard."""
    name = (file.filename or "").lower()
    if not name.endswith(".json"):
        raise HTTPException(400, "El archivo debe ser client_secret.json")
    raw = await file.read()
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "JSON inválido")
    if "installed" not in data and "web" not in data:
        raise HTTPException(400, "No parece un client_secret OAuth (falta 'installed' o 'web')")
    dest = DATA_DIR / "client_secret.json"
    dest.write_bytes(raw)
    return {"ok": True, "configured": youtube_publish.configured()}


@app.get("/api/stats")
async def stats():
    return db.stats()


# ──────────────────────────────────────────────────────── proyectos ──
@app.get("/api/projects")
async def projects():
    out = []
    for p in db.list_projects():
        p["scenes_count"] = len(db.get_scenes(p["id"]))
        out.append(p)
    return out


@app.post("/api/projects")
async def create_project(body: dict):
    mode = body.get("mode", "idea")
    if mode not in ("script", "idea", "url", "audio"):
        raise HTTPException(400, "modo inválido")
    meta = {}
    title = (body.get("title") or "Nuevo proyecto")[:60]
    if mode == "script":
        script = (body.get("script") or "").strip()
        if not script:
            raise HTTPException(400, "falta el guion")
        meta["script_text"] = script
        title = body.get("title") or script.strip().split("\n")[0][:60] or "Desde guion"
    if mode == "idea":
        meta["idea"] = (body.get("idea") or "").strip()
    if mode == "url":
        url = (body.get("url") or "").strip()
        if not url:
            raise HTTPException(400, "falta la URL")
        try:
            clean = url_mode.clean_url(url)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"URL inválida: {e}")
        meta["source_url"] = clean
        title = body.get("title") or "Viral recreado"
    if mode == "audio" and body.get("audio_text"):
        meta["audio_text"] = body["audio_text"]
    if body.get("custom_style_prompt"):
        meta["custom_style_prompt"] = body["custom_style_prompt"].strip()

    project = db.create_project(
        title=title, mode=mode, style=body.get("style", "graphic-novel"),
        format=body.get("format", "short"), voice=body.get("voice"),
        tts_provider=body.get("tts_provider"), meta=meta)
    return project


@app.get("/api/projects/{pid}")
async def get_project(pid: str):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    p["scenes"] = db.get_scenes(pid)
    job = db.active_job_for_project(pid)
    p["job"] = job
    return p


@app.patch("/api/projects/{pid}")
async def patch_project(pid: str, body: dict):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    fields = {k: v for k, v in body.items()
              if k in ("title", "style", "format", "voice", "tts_provider")}
    meta_patch = body.get("meta_patch")
    if meta_patch:
        fields["meta"] = {**(p.get("meta") or {}), **meta_patch}
    if fields:
        db.update_project(pid, **fields)
    return db.get_project(pid)


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    job = db.active_job_for_project(pid)
    if job:
        orchestrator.cancel_job(job["id"])
    shutil.rmtree(OUTPUT_DIR / pid, ignore_errors=True)
    db.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/generate")
async def generate(pid: str, body: dict | None = None):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    autopublish = bool((body or {}).get("autopublish", False))
    job_id = await orchestrator.start_pipeline(pid, autopublish=autopublish)
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    if not orchestrator.cancel_job(job_id):
        raise HTTPException(404, "job no activo")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    q = orchestrator.broker.subscribe(job_id)

    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") in ("done", "error", "cancelled"):
                    break
        finally:
            orchestrator.broker.unsubscribe(job_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ── media de proyectos ────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/video")
async def project_video(pid: str):
    p = db.get_project(pid)
    if not p or not p.get("video_url") or not Path(p["video_url"]).exists():
        raise HTTPException(404, "video no disponible")
    return FileResponse(p["video_url"], media_type="video/mp4",
                        filename=f"{p['title'][:40]}.mp4")


@app.get("/api/projects/{pid}/thumbnail")
async def project_thumb(pid: str):
    p = db.get_project(pid)
    if not p or not p.get("thumbnail_url") or not Path(p["thumbnail_url"]).exists():
        raise HTTPException(404, "sin miniatura")
    return FileResponse(p["thumbnail_url"], media_type="image/jpeg")


@app.get("/api/projects/{pid}/subtitles.srt")
async def project_srt(pid: str):
    words_file = OUTPUT_DIR / pid / "words.json"
    if not words_file.exists():
        raise HTTPException(404, "sin subtítulos")
    words = json.loads(words_file.read_text())
    from fastapi import Response
    return Response(words_to_srt(words), media_type="text/plain",
                    headers={"Content-Disposition": "attachment"})


# ── editor de escenas ─────────────────────────────────────────────────────
@app.patch("/api/scenes/{scene_id}")
async def patch_scene(scene_id: str, body: dict):
    allowed = {k: v for k, v in body.items()
               if k in ("title", "narration", "image_prompt")}
    if allowed:
        db.update_scene(scene_id, **allowed)
    return db.get_scenes(body["project_id"]) if body.get("project_id") else {"ok": True}


@app.post("/api/projects/{pid}/reorder")
async def reorder(pid: str, body: dict):
    ids: list[str] = body.get("scene_ids", [])
    db.reorder_scenes(pid, ids)
    return db.get_scenes(pid)


@app.post("/api/scenes/{scene_id}/regenerate-image")
async def regen_image(scene_id: str, body: dict):
    scene = next((s for s in db.get_scenes(body["project_id"]) if s["id"] == scene_id), None)
    if not scene:
        raise HTTPException(404, "escena no existe")
    project = db.get_project(body["project_id"])
    path, method = await imgs_pipeline.generate_scene_image(scene, project, int(scene["idx"]))
    db.update_scene(scene_id, image_path=str(path))
    return {"image": f"/api/scenes/{scene_id}/image?v={path}", "method": method}


@app.get("/api/scenes/{scene_id}/image")
async def scene_image(scene_id: str):
    with db.connect() as con:
        row = con.execute("SELECT image_path FROM scenes WHERE id=?", (scene_id,)).fetchone()
    if not row or not row["image_path"] or not Path(row["image_path"]).exists():
        raise HTTPException(404, "sin imagen")
    return FileResponse(row["image_path"])


@app.get("/api/scenes/{scene_id}/audio")
async def scene_audio(scene_id: str):
    with db.connect() as con:
        row = con.execute("SELECT audio_path FROM scenes WHERE id=?", (scene_id,)).fetchone()
    if not row or not row["audio_path"] or not Path(row["audio_path"]).exists():
        raise HTTPException(404, "sin audio")
    return FileResponse(row["audio_path"], media_type="audio/wav")


# ────────────────────────────────────────────────── modo fábrica ──
@app.get("/api/factory")
async def factory_status():
    return scheduler.status()


@app.post("/api/factory/config")
async def factory_config(body: dict):
    allowed = {k: v for k, v in body.items()
               if k in ("enabled", "times", "timezone", "niche", "style",
                        "format", "autopublish", "voice", "tts_provider")}
    return scheduler.save_config(**allowed)


@app.post("/api/factory/run-now")
async def factory_run_now():
    return await scheduler.run_one_cycle(reason="manual")


@app.get("/api/factory/ideas")
async def factory_ideas():
    return scheduler.get_ideas()


@app.post("/api/factory/ideas")
async def add_idea(body: dict):
    idea = (body.get("idea") or "").strip()
    if not idea:
        raise HTTPException(400, "idea vacía")
    return scheduler.add_idea(idea)


@app.delete("/api/factory/ideas")
async def clear_ideas():
    db.kv_set("factory.ideas", [])
    return []


# ─────────────────────────────────────────────── autopublish YouTube ──
@app.get("/api/publish/status")
async def publish_status():
    return {"configured": youtube_publish.configured(),
            "token": youtube_publish.has_token()}


@app.get("/api/publish/auth-url")
async def publish_auth_url():
    url = youtube_publish.build_auth_url()
    if not url:
        raise HTTPException(400, "Falta client_secret.json en backend/data/")
    return {"url": url}


@app.post("/api/publish/exchange")
async def publish_exchange(body: dict):
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "falta el código")
    ok = youtube_publish.exchange_code(code)
    return {"ok": ok}


@app.post("/api/publish/{pid}")
async def publish_video(pid: str, body: dict):
    p = db.get_project(pid)
    if not p or not p.get("video_url"):
        raise HTTPException(404, "video no disponible")
    if not youtube_publish.configured():
        raise HTTPException(400, "Configura client_secret.json (README §Publicar)")
    try:
        vid = youtube_publish.upload(
            p["video_url"], body.get("title") or p["title"],
            description=body.get("description", ""),
            tags=body.get("tags", []),
            private=bool(body.get("private", True)),
            publish_at=body.get("publish_at"),
        )
        db.update_project(pid, status="published", youtube_id=vid)
        return {"youtube_id": vid,
                "url": f"https://youtube.com/watch?v={vid}"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e)[:300])


# ─────────────────────────────────────────────── cola de extensión ──
@app.get("/api/extension/download")
async def extension_download():
    """Descarga la extensión Chrome (Plan B) como ZIP listo para cargar."""
    ext_dir = Path(__file__).resolve().parent.parent / "extension"
    if not ext_dir.exists():
        raise HTTPException(404, "carpeta extension/ no encontrada")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(ext_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(ext_dir.parent))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      "attachment; filename=yt_extension_chrome.zip"})


@app.post("/api/extension/images")
async def extension_images(body: dict):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "falta url")
    eid = db.add_ext_image(url, body.get("project_id"), body.get("source", "imagefx"))
    return {"ok": True, "id": eid}


@app.get("/api/extension/pending")
async def extension_pending():
    return {"pending": db.count_ext_images()}


# ────────────────────────────────────────────────────── import audio ──
@app.post("/api/import/audio")
async def import_audio(file: UploadFile = File(...)):
    dest = TMP_DIR / f"voice_upload_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest)}


# ─────────────────────────────────────────────────────── dashboard ──
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
