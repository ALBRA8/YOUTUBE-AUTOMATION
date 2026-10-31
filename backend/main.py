"""
YOUTUBE AUTOMATION v2.0 — Servidor principal (FastAPI)
Dashboard en http://127.0.0.1:8000  ·  progreso por SSE  ·  coste $0/video
"""
import asyncio
import time
import io
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

import config
import database as db
import security
from config import DATA_DIR, HOST, OUTPUT_DIR, PORT, TMP_DIR
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pipeline import images as imgs_pipeline
from pipeline import orchestrator
from pipeline import video as video_pipeline
from pipeline.subtitles import words_to_srt
from services import (general_agent as agent_svc,  # INT-028: cerebro único (ex-VÓRTICE)
                      backup as backup_svc, camera_recipes,
                      doctor as doctor_svc,
                      gemini_client, guion_json as guion_svc,
                      library as library_svc,
                      niches as niches_svc, nvidia_client,
                      production_json as prod_svc, scheduler,
                      trend_research as trends_svc,
                      tts_service, url_mode, whisper_service, youtube_publish)
from services import avatar_schema
from services.themes import STYLES, get_style

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="YT Automation v2.0", version="2.20.0")

# [flow-bridge v1.1] CORS endurecido (fusión con la línea 2.2 del repo):
# solo la extensión Chrome (chrome-extension:// con ID válido de 32 chars a-p)
# y clientes locales (localhost/127.0.0.1). El fetch del Service Worker con
# host_permissions del manifest 2.2 pasa sin CORS; el popup y un worker
# remoto local sí lo necesitan. Sin credenciales.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-p]+|https?://(localhost|127\.0\.0\.1)(:\d+)?)$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# PHASE 1 · M10 — techo global anti bomba de descompresión (Pillow)
security.harden_pil(config.LIMITS["MAX_IMAGE_PIXELS"])


@app.on_event("startup")
async def _startup_tasks():
    """v2.12.2 · hallazgo de la auditoría: la DB moría sin réplica.
    Backup al arrancar (consistente, WAL-safe) + loop cada BACKUP_INTERVAL_H."""
    try:
        r = await asyncio.to_thread(backup_svc.create_backup, "arranque")
        if r:
            log.info("backup de arranque: %s (%.1f KB)", r["name"], r["size"] / 1024)
    except Exception as e:  # noqa: BLE001
        log.warning("backup de arranque falló: %s", str(e)[:120])
    backup_svc.start_scheduler()

AVATARS_DIR = DATA_DIR / "avatars"
VALID_PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")


@app.middleware("http")
async def no_cache_ui(request, call_next):
    """El dashboard (HTML/JS/CSS) siempre se revalida: evita que el navegador
    se quede con una versión vieja de la interfaz sin claves ni botones nuevos."""
    resp = await call_next(request)
    p = request.url.path
    if p.startswith("/static") or p in ("/", "/app", "/app/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.middleware("http")
async def auth_guard(request, call_next):
    """Blindaje opcional del panel (auditoría externa: «cero autenticación»).
    Si MASTER_API_KEY está definida en backend/.env, TODAS las rutas /api/*
    exigen la clave vía header X-API-Key, Bearer, cookie (SSE) o ?api_key=.
    v2.19 · también cubre /mcp (antes el servidor MCP quedaba FUERA del
    guard incluso con clave maestra: exponía lanzar_proyecto, cancelar
    y doctor fix sin autenticación). En modo local (sin clave definida)
    no bloquea nada: cero ruptura."""
    _p = request.url.path
    # PHASE 1 · M1: la documentación y el schema abierto también exigen
    # clave (/docs, /redoc, /openapi.json — /mcp/* ya quedaba cubierto).
    _is_docs = (_p in ("/docs", "/redoc", "/openapi.json")
                or _p.startswith("/docs/") or _p.startswith("/redoc/"))
    if security.enabled() and (_p.startswith("/api/") or _p.startswith("/mcp")
                               or _is_docs) \
            and _p not in security.PUBLIC_PATHS:
        provided = request.headers.get("X-API-Key", "")
        if not provided:
            auth = request.headers.get("Authorization", "")
            provided = auth[7:] if auth.startswith("Bearer ") else ""
        if not provided:
            provided = request.cookies.get(security.COOKIE_NAME, "")
        if not provided:
            provided = request.query_params.get("api_key", "")
        if not security.verify(provided):
            return JSONResponse(status_code=401,
                                content={"detail": "clave maestra requerida "
                                                   "(X-API-Key / MASTER_API_KEY)"})
    return await call_next(request)


@app.middleware("http")
async def csrf_guard(request, call_next):
    """PHASE 1 · M2 — política CSRF para mutaciones + tope de body.

    POST/PUT/PATCH/DELETE con Origin o Referer PRESENTE deben pasar la
    política security.origin_allowed (mismo host, cliente local o la
    extensión Chrome); un origen externo (p. ej. https://evil.example que
    lanza fetch no-cors/sendBeacon) → 403. Sin Origin/Referer (curl, API
    clients, workers internos) se PERMITE: los navegadores siempre envían
    Origin en mutaciones cross-site, así que la ausencia implica cliente
    no-navegador. Además, Content-Length por encima del tope global → 413
    (nunca consumir bodies ilimitados — A7/DoS)."""
    m = request.method.upper()
    if m in ("POST", "PUT", "PATCH", "DELETE"):
        source = (request.headers.get("Origin")
                  or request.headers.get("Referer") or "")
        if source and not security.origin_allowed(
                source, request.headers.get("Host", "")):
            return JSONResponse(status_code=403,
                                content={"detail": "origen no permitido para "
                                                   "mutaciones (política CSRF)"})
    cl = request.headers.get("content-length") or ""
    if cl.isdigit() and int(cl) > config.LIMITS["MAX_BODY_BYTES"]:
        return JSONResponse(status_code=413, content={"detail": "body demasiado grande"})
    return await call_next(request)


# ── PHASE 1 · helpers centralizados de seguridad de endpoints ──────────
def _pid(pid: str) -> str:
    """C1 · formato canónico del project_id (12 hex, política única en
    security.validate_project_id). Todo endpoint que reciba pid pasa por
    aquí: traversal («..», «%2e%2e»), rutas absolutas y caracteres
    inesperados mueren con 400 ANTES de tocar filesystem/db."""
    try:
        return security.validate_project_id(pid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _project_or_404(pid: str) -> dict:
    """Formato válido (400) + proyecto existente (404) — sin filtrar nada."""
    p = db.get_project(_pid(pid))
    if not p:
        raise HTTPException(404, "no existe")
    return p


async def _read_upload(file: UploadFile, max_bytes: int, what: str) -> bytes:
    """Lee un UploadFile CON TOPE (antes file.read() volcaba el body entero
    a RAM). Excede → 413 controlado, nunca 500 ni OOM."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, f"{what} (> {max_bytes // (1024 * 1024)} MB)")
    return bytes(buf)


async def _read_body(request: Request, max_bytes: int) -> bytes:
    """Lee el body crudo por stream con tope (flow jobs complete)."""
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, "body demasiado grande")
    return bytes(buf)


# M6 · estado interno propiedad del SISTEMA: el cliente NUNCA puede
# falsificarlo vía meta_patch (qa_final = gate de publicación, estado de
# publish, rutas de asset, estados del Execution Contract, binding). Todo lo
# demás en meta sigue editable (transitions, subtitle_style, ideas…).
_SYSTEM_META_KEYS = {
    "qa_final", "publish_state", "publish_error", "youtube_id",
    "audio_path", "video_url", "thumbnail_url",
    "exec_state", "execution_state", "contract_result", "binding",
    "asset_validity", "publishability",
}


# ──────────────────────────────────────────────────────── básicos ──
@app.get("/api/health")
async def health():
    return {"ok": True, "version": "2.20.0", "gemini": gemini_client.available(),
            "nvidia": nvidia_client.available(),
            "nvidia_model": nvidia_client.last_model(),
            "whisper": whisper_service.available(),
            "youtube": youtube_publish.configured(),
            "canales": False}  # puente WhatsApp/Telegram pendiente de re-cosecha (v2.11.2)


@app.get("/api/auth/status")
async def auth_status():
    """El dashboard consulta esto al cargar: si hay clave maestra, pide login."""
    return {"auth_required": security.enabled()}


@app.get("/api/styles")
async def styles():
    return STYLES


@app.get("/api/cameras")
async def cameras():
    """v2.11 · Catálogo de recetas de cámara (cine + UGC) para el campo
    «camara» del contrato guion_json y para el selector de escenas."""
    return camera_recipes.list()


@app.get("/api/production_json/contrato")
async def production_json_contrato():
    """v2.14 · Spec machine-readable del contrato Creative Production JSON
    (Creative Engine → Adapter). guion_json sigue intacto para guiones."""
    return prod_svc.spec([s["id"] for s in STYLES])


@app.post("/api/production_json/validate")
async def production_json_validate(body: dict):
    """v2.14 · Dry-run del Adapter: valida y traduce el envelope SIN crear
    proyecto, escenas ni archivos. Ideal para el Creative Engine antes de
    ingerir."""
    try:
        payload = body.get("production",
                           body.get("production_json",
                                    body if "sequence" in body else None))
        if payload is None:
            raise ValueError("falta «production» — envía el Creative "
                             "Production JSON (objeto o string JSON)")
        return prod_svc.validate_only(payload, {s["id"] for s in STYLES})
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/guion_json/contrato")
async def guion_json_contrato():
    """v2.11 · Spec machine-readable del contrato guion_json
    (para Actions de ChatGPT y para humanos)."""
    return guion_svc.spec([s["id"] for s in STYLES])


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
            {"id": "es-CO-GonzaloNeural", "name": "Gonzalo (Colombia)"},
            {"id": "es-MX-JorgeNeural", "name": "Jorge (México)"},
            {"id": "es-MX-DaliaNeural", "name": "Dalia (México)"},
            {"id": "es-AR-ElenaNeural", "name": "Elena (Argentina)"},
            {"id": "es-AR-TomasNeural", "name": "Tomás (Argentina)"},
            {"id": "es-US-AlonsoNeural", "name": "Alonso (US Latino)"},
            {"id": "es-US-IsabellaNeural", "name": "Isabella (US Latino)"},
            {"id": "es-ES-ElviraNeural", "name": "Elvira (España)"},
            {"id": "es-ES-AlvaroNeural", "name": "Álvaro (España)"},
        ],
        "gemini_voices": [
            {"id": "Fenrir", "name": "Fenrir — narrador épico"},
            {"id": "Puck", "name": "Puck — energético"},
            {"id": "Kore", "name": "Kore — femenina cálida"},
            {"id": "Charon", "name": "Charon — documental"},
            {"id": "Aoede", "name": "Aoede — juvenil"},
        ],
    }


# ────── 🎙️ Galería de Voces con Preescucha Interactiva (INT-040) ─────────
@app.get("/api/voices")
async def list_voices(provider: str = "", gender: str = "", country: str = "", q: str = ""):
    """Catálogo enriquecido de voces con filtrado por proveedor, país, género o texto."""
    from services import voices_catalog
    return {
        "ok": True,
        "gemini_available": gemini_client.available(),
        "current_provider": config.TTS_PROVIDER,
        "current_edge_voice": config.EDGE_TTS_VOICE,
        "current_gemini_voice": config.GEMINI_TTS_VOICE,
        "voices": voices_catalog.get_all_voices(
            provider=provider or None,
            gender=gender or None,
            country=country or None,
            query=q or None,
        ),
    }


@app.post("/api/voices/preview")
async def voice_preview(payload: dict):
    """Genera o sirve desde caché una muestra de audio para preescucha de voz."""
    from services import voices_catalog
    voice_id = (payload.get("voice_id") or "").strip()
    if not voice_id:
        raise HTTPException(400, "voice_id es requerido")
    text = (payload.get("text") or "").strip() or None
    provider = (payload.get("provider") or "").strip().lower() or None
    try:
        path, duration, mime = await voices_catalog.synthesize_preview(
            voice_id, text=text, provider=provider
        )
        return {
            "ok": True,
            "voice_id": voice_id,
            "audio_url": f"/api/voices/audio/{path.name}",
            "duration": round(duration, 2),
            "mime": mime,
        }
    except Exception as e:
        log.error("Error generando preescucha de voz %s: %s", voice_id, e)
        raise HTTPException(500, f"Error generando preview: {str(e)[:200]}") from e


@app.get("/api/voices/audio/{filename}")
async def serve_voice_audio(filename: str):
    """Sirve el archivo de audio generado para preescucha en el navegador."""
    from services import voices_catalog
    clean_name = Path(filename).name
    file_path = voices_catalog.PREVIEWS_DIR / clean_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "Audio de preescucha no encontrado")
    media_type = "audio/mpeg" if clean_name.endswith(".mp3") else "audio/wav"
    return FileResponse(file_path, media_type=media_type)


@app.post("/api/voices/select")
async def select_voice(payload: dict):
    """Selecciona y aplica una voz a nivel global o a un proyecto específico."""
    from services import voices_catalog
    voice_id = (payload.get("voice_id") or "").strip()
    if not voice_id:
        raise HTTPException(400, "voice_id es requerido")
    voice = voices_catalog.get_voice_by_id(voice_id)
    if not voice:
        raise HTTPException(404, "Voz no encontrada en el catálogo")

    provider = voice["provider"]
    project_id = (payload.get("project_id") or "").strip()

    if project_id:
        pid = _pid(project_id)
        p = db.get_project(pid)
        if not p:
            raise HTTPException(404, "Proyecto no encontrado")
        db.update_project(pid, voice=voice_id, tts_provider=provider)
        return {"ok": True, "scope": "project", "project_id": pid, "voice": voice}

    if provider == "gemini":
        config.GEMINI_TTS_VOICE = voice_id
        config.TTS_PROVIDER = "gemini"
        config.save_env({"GEMINI_TTS_VOICE": voice_id, "TTS_PROVIDER": "gemini"})
    else:
        config.EDGE_TTS_VOICE = voice_id
        config.TTS_PROVIDER = "edge"
        config.save_env({"EDGE_TTS_VOICE": voice_id, "TTS_PROVIDER": "edge"})

    return {"ok": True, "scope": "global", "voice": voice, "tts_provider": provider}


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
        "nvidia_key_set": nvidia_client.available(),
        "nvidia_key_masked": _mask(config.NVIDIA_API_KEY),
        "nvidia_model": config.NVIDIA_MODEL,
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
        if key in ("GEMINI_API_KEY", "NVIDIA_API_KEY"):
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
    try:
        saved = config.save_env(updates)
    except ValueError as e:  # A2: valor con \r/\n — rechazo explícito, 400
        raise HTTPException(400, str(e)) from e
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
    raw = await _read_upload(file, config.LIMITS["MAX_UPLOAD_JSON_BYTES"],
                             "archivo demasiado grande")
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


# ─────────────────────────────── avatars (v2.1 · personajes) ──
# Campos de menú desplegable del schema PRO + campos de texto libre
_SCHEMA_FIELDS = set(avatar_schema.AVATAR_OPTIONS)
_FREE_FIELDS = {"accesorios", "extras", "referencia"}
# Compatibilidad v2.1.0: claves antiguas de texto libre
_LEGACY_MAP = {"estilo_ropa": "ropa", "ojos": "ojos_color",
               "cabello": "cabello_color"}


def _clean_appearance(raw) -> dict:
    """Normaliza la apariencia: valida dropdowns del schema y conserva
    campos de texto libre (accesorios/extras/referencia). Mantiene las
    claves antiguas (piel, ojos, cabello…) por compatibilidad."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        key = str(k).strip().lower().replace(" ", "_")[:30]
        key = _LEGACY_MAP.get(key, key)
        val = str(v).strip()
        if not key or not val or val == "Ninguno" and key == "maquillaje":
            continue
        val = val[:80]
        if key in _SCHEMA_FIELDS:
            out[key] = val
        elif key in _FREE_FIELDS:
            out[key] = val
        else:
            out[key] = val  # claves desconocidas: preservar (no romper datos)
    return out


@app.get("/api/avatars/schema")
async def avatars_schema():
    """Opciones de todos los menús desplegables del formulario de avatares."""
    return avatar_schema.schema()


@app.get("/api/avatars")
async def avatars_list():
    return db.list_avatars()


@app.post("/api/avatars")
async def avatars_create(body: dict):
    name = (body.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "el avatar necesita un nombre")
    voice = (body.get("voice") or "").strip() or None
    tts_provider = (body.get("tts_provider") or "").strip().lower() or None
    if tts_provider and tts_provider not in ("edge", "gemini"):
        raise HTTPException(400, "tts_provider debe ser edge o gemini")
    style = (body.get("style") or "").strip() or None
    av = db.create_avatar(
        name=name,
        description=(body.get("description") or "").strip()[:400],
        appearance=_clean_appearance(body.get("appearance")),
        voice=voice, tts_provider=tts_provider, style=style)
    return av


@app.patch("/api/avatars/{aid}")
async def avatars_update(aid: str, body: dict):
    av = db.get_avatar(aid)
    if not av:
        raise HTTPException(404, "avatar no existe")
    fields = {}
    if "name" in body:
        name = (body.get("name") or "").strip()[:60]
        if not name:
            raise HTTPException(400, "el nombre no puede quedar vacío")
        fields["name"] = name
    for k in ("description", "voice", "style"):
        if k in body:
            fields[k] = (str(body.get(k) or "").strip() or None)
    if "tts_provider" in body:
        tp = (body.get("tts_provider") or "").strip().lower() or None
        if tp and tp not in ("edge", "gemini"):
            raise HTTPException(400, "tts_provider debe ser edge o gemini")
        fields["tts_provider"] = tp
    if "appearance" in body:
        fields["appearance"] = _clean_appearance(body.get("appearance"))
    if fields:
        db.update_avatar(aid, **fields)
    return db.get_avatar(aid)


@app.delete("/api/avatars/{aid}")
async def avatars_delete(aid: str):
    av = db.get_avatar(aid)
    if not av:
        raise HTTPException(404, "avatar no existe")
    if av.get("image_path"):
        Path(av["image_path"]).unlink(missing_ok=True)
    db.delete_avatar(aid)
    return {"ok": True}


@app.post("/api/avatars/{aid}/image")
async def avatars_image(aid: str):
    """Genera el retrato del avatar: Gemini si hay clave; si no, retrato
    local elegante con Pillow (coste $0)."""
    av = db.get_avatar(aid)
    if not av:
        raise HTTPException(404, "avatar no existe")
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    out = AVATARS_DIR / f"{aid}.png"
    prompt = avatar_schema.portrait_prompt(av)
    method = "placeholder"
    if gemini_client.available():
        try:
            data = await gemini_client.generate_image(prompt)
            out.write_bytes(data)
            method = "gemini"
        except Exception as e:  # noqa: BLE001
            log.warning("Retrato Gemini falló: %s", str(e)[:120])
    if method == "placeholder":
        try:
            import urllib.request
            import urllib.parse
            encoded = urllib.parse.quote(prompt[:300])
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    out.write_bytes(resp.read())
                    method = "pollinations_ai"
        except Exception as e2:  # noqa: BLE001
            log.warning("Retrato Pollinations falló: %s", str(e2)[:120])
    if method == "placeholder":
        _avatar_placeholder(out, av)
    db.update_avatar(aid, image_path=str(out))
    return {"ok": True, "method": method, "image_url": f"/api/avatars/{aid}/image"}


def _avatar_placeholder(out: Path, av: dict) -> None:
    """Retrato local con Pillow: gradiente según estilo + iniciales grandes."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        out.write_bytes(b"")
        return
    grad = next((s["grad"] for s in STYLES
                 if s["id"] == (av.get("style") or "")),
                "linear-gradient(135deg,#1a1a2e,#e94560)")
    # Reutiliza el parser robusto de pipeline.images para evitar el bug
    # de "not enough values to unpack" si el grad no tiene 2 colores.
    from pipeline.images import _parse_grad
    c1, c2 = _parse_grad(grad)
    W, H = 768, 768
    img = Image.new("RGB", (W, H), c1)
    draw = ImageDraw.Draw(img)
    c1rgb = tuple(int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    c2rgb = tuple(int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    for y in range(H):
        t = y / H
        rgb = tuple(int(c1rgb[i] * (1 - t) + c2rgb[i] * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=rgb)
    initials = "".join(w[0] for w in av["name"].split()[:2]).upper() or "A"
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 240)
    except Exception:  # noqa: BLE001
        font = None
    bbox = draw.textbbox((0, 0), initials, font=font) if font else (0, 0, 200, 240)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((W - tw) / 2 - bbox[0], (H - th) / 2 - bbox[1]), initials,
              fill=(255, 255, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


@app.get("/api/avatars/{aid}/prompt")
async def avatars_prompt(aid: str):
    """Prompts derivados del avatar (transparencia total, como Vórtice
    pero con prompts RICOS que sí usan las características)."""
    av = db.get_avatar(aid)
    if not av:
        raise HTTPException(404, "avatar no existe")
    return {
        "name": av["name"],
        "portrait": avatar_schema.portrait_prompt(av),
        "scene": avatar_schema.scene_suffix(av),
        "persona": avatar_schema.persona_text(av).strip(),
    }


@app.get("/api/avatars/{aid}/image")
async def avatars_image_get(aid: str):
    av = db.get_avatar(aid)
    if not av:
        raise HTTPException(404, "avatar no existe")
    # Si no existe el retrato en disco, auto-generar uno local al vuelo.
    # Así la UI nunca muestra 404 aunque el usuario no haya hecho clic en
    # "Generar retrato".
    if not av.get("image_path") or not Path(av["image_path"]).exists():
        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        out = AVATARS_DIR / f"{aid}.png"
        _avatar_placeholder(out, av)
        db.update_avatar(aid, image_path=str(out))
        av = db.get_avatar(aid)
    return FileResponse(av["image_path"], media_type="image/png")


# ──────────────────── chat-agente (v2.12 · Agente General, INT-028) ──
@app.get("/api/cerebros")
async def cerebros_list():
    """v2.12.1 · CEREBROS: catálogo de modelos NVIDIA con estado vivo
    (ok/fail/untested + latencia del último uso) y el activo."""
    if not nvidia_client.available():
        return {"activo": None, "cerebros": [], "aviso": "sin NVIDIA_API_KEY"}
    act = nvidia_client.active_cerebro()
    return {"activo": act["alias"], "modelo": act["model"],
            "cerebros": nvidia_client.list_cerebros()}


_IMAGE_RE = re.compile(
    r"^data:image/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$|^https?://\S+$")


@app.post("/api/cerebros")
async def cerebros_pick(body: dict):
    """Elige el cerebro del Agente General (persistente en .env, aplica al instante)."""
    alias = str((body or {}).get("alias") or "").strip()
    c = nvidia_client.find_cerebro(alias)
    if not c:
        raise HTTPException(400, "cerebro desconocido: " + alias)
    nvidia_client.set_preferred(alias)
    config.save_env({"NVIDIA_MODEL": c["model"]})
    return {"ok": True, "activo": c["alias"], "model": c["model"],
            "name": c["name"], "vision": c["vision"],
            "message": f"Cerebro cambiado a {c['emoji']} {c['name']}"}


@app.post("/api/chat")
async def chat(body: dict):
    """Agente General (services/general_agent.py — INT-028 absorbe VÓRTICE):
    entiende la fábrica (contexto vivo) y ejecuta acciones reales. Acciones
    destructivas exigen confirmación del usuario: la primera llamada devuelve
    needs_confirm+pending; la ejecución real llega en la segunda llamada con
    {confirm: {action, params}}."""
    confirm = body.get("confirm") or None
    if confirm:
        action = str(confirm.get("action") or "")
        if action not in agent_svc.DESTRUCTIVE_ACTIONS:
            raise HTTPException(400, "acción no confirmable")
        plan_out = {"action": action, "params": confirm.get("params") or {},
                    "reply": "", "engine": "confirm"}
        result = await agent_svc.execute(plan_out, db, orchestrator, db.list_avatars())
        result["engine"] = "confirm"
        return result
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        raise HTTPException(400, "mensaje vacío")
    # v2.12.1 · CEREBROS: cerebro elegido (alias) + imagen adjunta (solo visión)
    prefer = str(body.get("cerebro") or "").strip() or None
    image = str(body.get("image") or "").strip() or None
    if image and not _IMAGE_RE.match(image):
        raise HTTPException(400, "imagen inválida (usa data URL o http(s))")
    if image and len(image) > 5_500_000:
        raise HTTPException(413, "imagen demasiado grande (máx ~4MB)")
    cinfo = nvidia_client.find_cerebro(prefer) if prefer else None
    if image and cinfo and not cinfo["vision"]:
        raise HTTPException(400, f"el cerebro {cinfo['name']} no ve imágenes — "
                                 "cambia a uno con visión (👁️)")
    plan_out = await agent_svc.plan(message, history, db.list_avatars(), db,
                                    prefer=prefer, image=image)
    if plan_out.get("action") in agent_svc.DESTRUCTIVE_ACTIONS:
        what = (plan_out.get("params", {}).get("name")
                or plan_out.get("params", {}).get("project_name") or "").strip()
        if plan_out["action"] == "cleanup_failed":
            ask = "¿Confirmas que borre TODOS los proyectos fallidos?"
        else:
            ask = f"¿Confirmas borrar «{what}»?"
        return {"reply": f"{plan_out.get('reply', '')}\n\n{ask}",
                "needs_confirm": True,
                "pending": {"action": plan_out["action"],
                            "params": plan_out.get("params", {})},
                "engine": plan_out.get("engine", "local")}
    result = await agent_svc.execute(plan_out, db, orchestrator, db.list_avatars())
    result["engine"] = plan_out.get("engine", "local")
    return result


# ─────────────────────────── backups (v2.12.2 · resiliencia) ──
@app.get("/api/backups")
async def backups_list():
    """Backups disponibles (DB + token.json + .env) — el más nuevo primero."""
    return {"dir": str(backup_svc.BACKUP_DIR), "keep": backup_svc.KEEP,
            "interval_h": backup_svc.INTERVAL_H, "backups": backup_svc.list_backups()}


@app.post("/api/backups")
async def backups_create():
    """Crea un backup ahora mismo (manual)."""
    r = await asyncio.to_thread(backup_svc.create_backup, "manual")
    if not r:
        raise HTTPException(500, "el backup falló — revisa el log del servidor")
    return {"ok": True, "backup": r, "message": "Backup creado ✅"}


@app.post("/api/backups/restore")
async def backups_restore(body: dict):
    """Restaura un backup (antes deja uno de seguridad pre-restore)."""
    name = str((body or {}).get("name") or "")
    try:
        r = await asyncio.to_thread(backup_svc.restore_backup, name)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **r,
            "message": f"Restaurado {name} — reinicia el servidor para recargar todo"}


# ──────────────────────────────────────────────────────── proyectos ──
@app.get("/api/projects")
async def projects():
    out = []
    for p in db.list_projects():
        scenes = db.get_scenes(p["id"])
        p["scenes_count"] = len(scenes)
        # v2.11.1 · portada para la tarjeta: 1ª imagen de escena en disco > miniatura > None
        cover = next((f"/api/scenes/{s['id']}/image?project_id={p['id']}" for s in scenes
                      if s.get("image_path") and Path(s["image_path"]).exists()), None)
        if not cover and p.get("thumbnail_url") and Path(p["thumbnail_url"]).exists():
            cover = f"/api/projects/{p['id']}/thumbnail"
        p["cover_url"] = cover
        out.append(p)
    return out


@app.post("/api/projects")
async def create_project(body: dict):
    mode = body.get("mode", "idea")
    if mode not in ("script", "idea", "url", "audio", "nicho", "guion_json",
                    "production_json", "product"):
        raise HTTPException(400, "modo inválido")
    if mode == "guion_json":
        # v2.10 · contrato guion_json: el guion llega HECHO desde ChatGPT —
        # cero LLM interno. Valida, normaliza (alias/fences/fallbacks) y
        # crea el proyecto con sus escenas; auto_start lanza el pipeline.
        def _crear(g: dict):
            av = g.get("avatar_id")
            if av and not db.get_avatar(av):
                av = None
            # v2.11 · receta de cámara por defecto del proyecto → meta
            pmeta = {"camara": g["camara"]} if g.get("camara") else {}
            return db.create_project(
                title=(g.get("titulo") or "Video desde guion JSON"),
                mode="guion_json", style=g.get("estilo") or "auto",
                format=g.get("formato") or "short", voice=g.get("voz"),
                meta=pmeta, avatar_id=av,
                platforms=g.get("plataformas") or ["youtube"],
                niche=g.get("nicho"))
        try:
            return await guion_svc.ingest(body, {s["id"] for s in STYLES}, _crear)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if mode == "production_json":
        # v2.14 · Creative Production JSON (Creative Engine → Adapter): el
        # nicho llega HECHO desde el motor creativo — cero LLM interno. El
        # Adapter valida, traduce a unidades ejecutables, CONSERVA el JSON
        # original como production.json y deja todo lo específico del nicho
        # en meta. guion_json queda intacto como la otra puerta.
        def _crear_pj(g: dict):
            av = g.get("avatar_id")
            if av and not db.get_avatar(av):
                av = None
            pmeta = {"transitions": bool(body.get("transitions", True)),
                     "style_reference": bool(body.get("style_reference", True))}
            if g.get("camara"):
                pmeta["camara"] = g["camara"]
            sub = (body.get("subtitle_style") or "shorts").lower()
            if sub in video_pipeline.subs_mod.SUB_STYLES:
                pmeta["subtitle_style"] = sub
            return db.create_project(
                title=(g.get("titulo") or "Video desde Production JSON"),
                mode="production_json", style=g.get("estilo") or "auto",
                format=g.get("formato") or "short", voice=g.get("voz"),
                meta=pmeta, avatar_id=av,
                platforms=g.get("plataformas") or ["youtube"],
                niche=g.get("nicho"))
        try:
            payload = body.get("production", body.get("production_json"))
            if payload is None:
                raise ValueError("falta «production» — envía el Creative "
                                 "Production JSON (objeto o string JSON)")
            return await prod_svc.ingest(
                payload, {s["id"] for s in STYLES}, _crear_pj,
                auto_start_override=body.get("auto_start"))
        except ValueError as e:
            raise HTTPException(400, str(e))
    meta = {"pacing": (body.get("pacing") or "normal").strip().lower()}
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
            security.validar_url(url)  # A8: SSRF — file://, LAN, metadatos…
            clean = url_mode.clean_url(url)
        except ValueError as e:
            raise HTTPException(400, f"URL no permitida: {e}")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"URL inválida: {e}")
        meta["source_url"] = clean
        title = body.get("title") or "Viral recreado"
    if mode == "audio" and body.get("audio_text"):
        meta["audio_text"] = body["audio_text"]
    if mode == "product":
        from services import ugc_ad_generator
        raw_target = str(body.get("url") or body.get("idea") or body.get("product") or "").strip()
        angle = str(body.get("angle") or "3_reasons").strip()
        p_info = ugc_ad_generator.scrape_product_info(raw_target)
        ugc = ugc_ad_generator.generate_ugc_script(p_info, angle=angle)
        title = body.get("title") or ugc["title"]
        script = ugc["full_script"]
        meta["product_data"] = p_info
        meta["ugc_angle"] = angle
        meta["script"] = script
        meta["ecommerce_badge"] = body.get("ecommerce_badge") or body.get("badge_type") or "rating"
        meta["studio_style"] = body.get("studio_style") or "luxury_dark"
    # v2.6 — modo "nicho": plantilla predeterminada del nicho compone la idea
    # (plantilla + ángulo aleatorio + ajuste opcional) y hereda estilo/formato/
    # voz/subtítulos de la plantilla salvo que el usuario elija otros.
    niche_label = None
    if mode == "nicho":
        tpl = niches_svc.get_template(body.get("niche_template") or "")
        if not tpl:
            raise HTTPException(400, "nicho desconocido — elige una plantilla válida")
        niche_label = tpl.get("name")
        meta["idea"] = niches_svc.compose_idea(tpl, body.get("idea"))
        meta["niche_template"] = tpl.get("id")
        title = (body.get("title") or f"{tpl.get('name')}: video nuevo")[:60]
        # herencia de la plantilla: mutamos body para que las líneas de abajo
        # (style/voice/sub_style) tomen el valor del nicho sin duplicar lógica
        if not body.get("style"):
            body["style"] = tpl.get("style") or "auto"
        if not body.get("format"):
            body["format"] = tpl.get("format") or "short"
        if not body.get("voice"):
            body["voice"] = tpl.get("voice") or None
        if not body.get("subtitle_style"):
            body["subtitle_style"] = tpl.get("subtitles") or "shorts"
    if body.get("custom_style_prompt"):
        meta["custom_style_prompt"] = body["custom_style_prompt"].strip()
    # v2.4 — toggles de producción expuestos en el dashboard
    meta["transitions"] = bool(body.get("transitions", True))
    meta["style_reference"] = bool(body.get("style_reference", True))
    if body.get("circle_avatar_pip"):
        meta["circle_avatar_pip"] = body["circle_avatar_pip"]
    sub_style = (body.get("subtitle_style") or "shorts").lower()
    if sub_style in video_pipeline.subs_mod.SUB_STYLES:
        meta["subtitle_style"] = sub_style
    cookies = (body.get("cookies_from_browser") or "").strip().lower()
    if cookies in ("chrome", "firefox", "edge", "brave", "safari", "vivaldi"):
        meta["cookies_from_browser"] = cookies

    # v2.1 — avatar + plataformas multi-red
    avatar_id = (body.get("avatar_id") or "").strip() or None
    voice = body.get("voice") or None
    tts_provider = body.get("tts_provider") or None
    style = body.get("style", "auto")
    # Validar style contra la lista real de estilos disponibles.
    # Si viene un style inválido (por API o auditoría), usar "auto" (el primero).
    valid_style_ids = {s["id"] for s in STYLES}
    if style not in valid_style_ids:
        style = "auto"
    if avatar_id and not db.get_avatar(avatar_id):
        avatar_id = None
    if avatar_id:
        av = db.get_avatar(avatar_id)
        voice = voice or av.get("voice")
        tts_provider = tts_provider or av.get("tts_provider")
        style = style or av.get("style") or style
    brand_pid = (body.get("brand_profile_id") or "").strip()
    if brand_pid:
        from services import brand_profiles as bp_svc
        bp = bp_svc.get_brand_profile(brand_pid)
        if bp:
            meta["brand_profile_id"] = bp["id"]
            meta["brand_profile"] = bp
            if bp.get("prompt_rules"):
                meta["prompt_rules"] = bp["prompt_rules"]
            if bp.get("tone"):
                meta["tone"] = bp["tone"]
            if bp.get("audience"):
                meta["audience"] = bp["audience"]
            if not niche_label and bp.get("niche"):
                niche_label = bp["niche"]
            if not body.get("voice") and bp.get("voice"):
                voice = bp["voice"]
            if not body.get("tts_provider") and bp.get("tts_provider"):
                tts_provider = bp["tts_provider"]
            if (not body.get("style") or body.get("style") == "auto") and bp.get("visual_style") and bp.get("visual_style") != "auto":
                style = bp["visual_style"]
            if not body.get("subtitle_style") and bp.get("subtitle_style"):
                meta["subtitle_style"] = bp["subtitle_style"]

    platforms = body.get("platforms")
    if not isinstance(platforms, list):
        platforms = ["youtube"]
    platforms = [p for p in platforms if p in VALID_PLATFORMS] or ["youtube"]

    project = db.create_project(
        title=title, mode=mode, style=style,
        format=body.get("format", "short"), voice=voice,
        tts_provider=tts_provider, meta=meta,
        avatar_id=avatar_id, platforms=platforms,
        niche=niche_label)
    if brand_pid:
        with db.connect() as con:
            cols = [r[1] for r in con.execute("PRAGMA table_info(projects)").fetchall()]
            if "brand_profile_id" in cols:
                con.execute("UPDATE projects SET brand_profile_id = ? WHERE id = ?", (brand_pid, project["id"]))
        project["brand_profile_id"] = brand_pid
    if mode == "nicho" and body.get("auto_start"):
        # flujo de un clic: crea el proyecto Y lanza el pipeline completo
        job_id = await orchestrator.start_pipeline(project["id"], autopublish=False)
        project["job_id"] = job_id
    return project


@app.get("/api/projects/{pid}")
async def get_project(pid: str):
    p = _project_or_404(pid)  # C1: formato + existencia
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
              if k in ("title", "style", "format", "voice", "tts_provider", "niche")}
    # Validar style si viene en el PATCH
    if "style" in fields:
        valid_style_ids = {s["id"] for s in STYLES}
        if fields["style"] not in valid_style_ids:
            del fields["style"]  # ignorar style inválido en PATCH
    if "avatar_id" in body:
        aid = (body.get("avatar_id") or "").strip() or None
        if aid and not db.get_avatar(aid):
            aid = None
        fields["avatar_id"] = aid
    if "platforms" in body:
        plats = body.get("platforms")
        fields["platforms"] = ([p for p in plats if p in VALID_PLATFORMS]
                               if isinstance(plats, list) else ["youtube"])
    meta_patch = body.get("meta_patch")
    if meta_patch:
        if not isinstance(meta_patch, dict):
            raise HTTPException(400, "meta_patch debe ser un objeto")
        protegidas = sorted(set(map(str, meta_patch)) & _SYSTEM_META_KEYS)
        if protegidas:  # M6: el estado interno no se falsifica
            raise HTTPException(403, "campos del sistema no editables vía "
                                     f"meta_patch: {', '.join(protegidas)}")
        fields["meta"] = {**(p.get("meta") or {}), **meta_patch}
    if fields:
        db.update_project(pid, **fields)
    return db.get_project(pid)


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    # PHASE 1 · C1: formato canónico → existencia → ruta resuelta y
    # CONTENIDA en OUTPUT_DIR; solo entonces rmtree (el exploit
    # DELETE /api/projects/%2e%2e que borraba backend/data muere con 400).
    _pid(pid)
    if not db.get_project(pid):
        raise HTTPException(404, "no existe")
    job = db.active_job_for_project(pid)
    if job:
        orchestrator.cancel_job(job["id"])
    shutil.rmtree(security.safe_project_output_dir(pid), ignore_errors=True)
    db.delete_project(pid)  # ahora también purga flow_jobs (integridad)
    return {"ok": True}


@app.post("/api/projects/{pid}/cleanup")
async def cleanup_project(pid: str):
    """Libera el disco: borra clips intermedios del proyecto (el MP4 final,
    imágenes, Flow y audio TTS se conservan). Útil si KEEP_INTERMEDIATES=1."""
    _pid(pid)
    if not db.get_project(pid):
        raise HTTPException(404, "no existe")
    freed = video_pipeline.cleanup_intermediates(pid)
    return {"ok": True, "freed_bytes": freed,
            "freed_mb": round(freed / 1e6, 1)}


@app.post("/api/projects/{pid}/generate")
async def generate(pid: str, body: dict | None = None):
    _pid(pid)
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    autopublish = bool((body or {}).get("autopublish", False))
    job_id = await orchestrator.start_pipeline(pid, autopublish=autopublish)
    return {"job_id": job_id}


# ───────────────────────────────────────── módulo "Desde Nicho" (v2.6) ──
@app.get("/api/niches")
async def niches_list():
    """Plantillas de nicho + nº de proyectos que usan cada una."""
    templates = niches_svc.list_templates()
    counts: dict[str, int] = {}
    for p in db.list_projects(limit=500):
        key = (p.get("niche") or "").strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    out = []
    for t in templates:
        t = dict(t)
        t["projects"] = counts.get((t.get("name") or "").strip().lower(), 0)
        t["folder"] = niches_svc.folder_name(t)
        out.append(t)
    return out


@app.get("/api/niches/templates")
async def niches_templates():
    return niches_svc.list_templates()


@app.post("/api/niches/templates")
async def niches_template_save(body: dict):
    try:
        return niches_svc.upsert_template(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/niches/templates/{tid}")
async def niches_template_delete(tid: str):
    if not niches_svc.delete_template(tid):
        raise HTTPException(404, "plantilla no encontrada")
    return {"ok": True}


@app.get("/api/library")
async def library():
    """Biblioteca en disco: biblioteca/{nicho}/{titulo}.mp4."""
    return library_svc.tree()


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
            # REPLAY: el cliente que conecta tarde recibe primero lo emitido
            # (logs + progreso) — terminal SSE sin huecos ni websockets
            for ev in orchestrator.broker.replay(job_id):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
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
    _pid(pid)
    p = db.get_project(pid)
    if not p or not p.get("video_url") or not Path(p["video_url"]).exists():
        raise HTTPException(404, "video no disponible")
    return FileResponse(p["video_url"], media_type="video/mp4",
                        filename=f"{p['title'][:40]}.mp4")


@app.get("/api/projects/{pid}/thumbnail")
async def project_thumb(pid: str):
    _pid(pid)
    p = db.get_project(pid)
    if not p or not p.get("thumbnail_url") or not Path(p["thumbnail_url"]).exists():
        raise HTTPException(404, "sin miniatura")
    return FileResponse(p["thumbnail_url"], media_type="image/jpeg")


@app.get("/api/projects/{pid}/subtitles.srt")
async def project_srt(pid: str):
    words_file = security.safe_project_output_dir(_pid(pid)) / "words.json"  # M5
    if not words_file.exists():
        raise HTTPException(404, "sin subtítulos")
    words = json.loads(words_file.read_text())
    from fastapi import Response
    return Response(words_to_srt(words), media_type="text/plain",
                    headers={"Content-Disposition": "attachment"})


# ── exportación a Google Flow (extensión Flow Script Processor) ────────────
_FMTS_FLOW = ("transformacion", "generic", "artesano")


@app.get("/api/projects/{pid}/export/flow.json")
async def export_flow_json(pid: str, format: str = "transformacion",
                           brand: str | None = None, character: str | None = None):
    """ScriptData con el contrato exacto de la extensión.
    format=transformacion|generic|artesano (fabricación de personaje)."""
    from pipeline.flow_export import DEFAULT_BRAND, build_script_json
    _pid(pid)
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    scenes = db.get_scenes(pid)
    if not scenes:
        raise HTTPException(400, "el proyecto no tiene escenas aún")
    data = build_script_json(p, scenes, fmt=format if format in _FMTS_FLOW else "transformacion",
                             brand=brand if brand is not None else DEFAULT_BRAND,
                             character=character or None)
    from fastapi import Response
    return Response(json.dumps(data, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=script.json"})


@app.get("/api/projects/{pid}/export/flow.zip")
async def export_flow_zip(pid: str, idea: int = 1, format: str = "transformacion",
                          ai: bool = False, brand: str | None = None,
                          character: str | None = None):
    """ZIP método completo: <SLUG>/out/ideas/idea_NNNNNN/{script.json, prompts_maestro,
    guion, metodo_chatgpt} + README. format=transformacion|generic|artesano · ai=1 usa
    Gemini free tier · character= nombre del héroe (modo artesano)."""
    from pipeline.flow_export import DEFAULT_BRAND, export_zip_bytes
    _pid(pid)
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    scenes = db.get_scenes(pid)
    if not scenes:
        raise HTTPException(400, "el proyecto no tiene escenas aún")
    idea = max(1, min(idea or 1, 999999))
    content, slug, ai_used = await export_zip_bytes(
        p, scenes, idea_number=idea,
        fmt=format if format in _FMTS_FLOW else "transformacion",
        use_ai=bool(ai), brand=brand if brand is not None else DEFAULT_BRAND,
        character=character or None)
    from fastapi import Response
    suffix = "_flow_ia" if ai_used else "_flow"
    return Response(content, media_type="application/zip",
                    headers={"Content-Disposition":
                             f"attachment; filename={slug}{suffix}.zip"})


@app.post("/api/projects/{pid}/import-flow")
async def import_flow(pid: str, file: UploadFile = File(...), overwrite: bool = True):
    """Importa el ZIP de Escena_XX generado por la extensión Flow Script Processor.

    Mapea cada Escena_XX a la escena X del proyecto y actualiza image_path.
    """
    from pipeline import flow_import
    _pid(pid)
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    scenes = db.get_scenes(pid)
    if not scenes:
        raise HTTPException(400, "el proyecto no tiene escenas aún")
    data = await _read_upload(file, config.LIMITS["MAX_ZIP_COMPRESSED_BYTES"],
                              "ZIP demasiado grande")  # A7
    try:
        result = flow_import.import_flow_zip(pid, data,
                                             security.safe_project_output_dir(pid),
                                             overwrite=overwrite)
    except ValueError as e:
        raise HTTPException(400, str(e))
    applied = flow_import.apply_to_scenes(scenes, result)
    return {**result, "applied": applied,
            "scenes_in_project": len(scenes),
            "next": f"POST /api/projects/{pid}/render-flow para ensamblar el video"}


@app.post("/api/projects/{pid}/render-flow")
async def render_flow(pid: str):
    """Ensambla el MP4 final con las imágenes reales de Flow (sin regenerar guion/imágenes)."""
    from pipeline import orchestrator
    _pid(pid)
    if not db.get_project(pid):  # M4: antes ValueError→500
        raise HTTPException(404, "no existe")
    scenes = db.get_scenes(pid)
    sin_img = [i + 1 for i, sc in enumerate(scenes)
               if not sc.get("image_path") or not Path(sc["image_path"]).exists()]
    if sin_img:
        raise HTTPException(400, f"Escenas sin imagen de Flow: {sin_img}. Importa el ZIP primero.")
    job_id = await orchestrator.start_flow_render(pid)
    return {"job_id": job_id}


# ── editor de escenas ─────────────────────────────────────────────────────
@app.patch("/api/scenes/{scene_id}")
async def patch_scene(scene_id: str, body: dict):
    # PHASE 1 · M3: la escena se verifica SIEMPRE contra su proyecto padre
    # (id + project_id) — un scene_id de OTRO proyecto responde 404.
    pid = _pid((body or {}).get("project_id") or "")
    allowed = {k: v for k, v in (body or {}).items()
               if k in ("title", "narration", "image_prompt")}
    if allowed and db.update_scene(scene_id, project_id=pid, **allowed) == 0:
        raise HTTPException(404, "escena no existe en ese proyecto")
    return db.get_scenes(pid)


@app.post("/api/projects/{pid}/reorder")
async def reorder(pid: str, body: dict):
    _pid(pid)
    ids: list[str] = body.get("scene_ids", [])
    db.reorder_scenes(pid, ids)
    return db.get_scenes(pid)


@app.post("/api/scenes/{scene_id}/regenerate-image")
async def regen_image(scene_id: str, body: dict):
    pid = _pid((body or {}).get("project_id") or "")  # M4: nunca KeyError→500
    scene = db.get_scene_for_project(pid, scene_id)   # M3: scoped al proyecto
    if not scene:
        raise HTTPException(404, "escena no existe")
    project = db.get_project(pid)
    path, method = await imgs_pipeline.generate_scene_image(scene, project, int(scene["idx"]))
    db.update_scene(scene_id, image_path=str(path))
    return {"image": f"/api/scenes/{scene_id}/image?project_id={pid}&v={path}", "method": method}


@app.post("/api/scenes/{scene_id}/regenerate-flow")
async def regen_flow_scene(scene_id: str, body: dict):
    """🎬 Tarjetas de Escenas con Regeneración Quirúrgica:
    Regenera una toma individual directamente mediante Google Flow MCP."""
    pid = _pid((body or {}).get("project_id") or "")  # M4: nunca KeyError→500
    scene = db.get_scene_for_project(pid, scene_id)   # M3: scoped al proyecto
    if not scene:
        raise HTTPException(404, "escena no existe")
    project = db.get_project(pid)
    path, method = await imgs_pipeline.generate_scene_image(scene, project, int(scene["idx"]))
    db.update_scene(scene_id, image_path=str(path))
    return {
        "ok": True,
        "scene_id": scene_id,
        "project_id": pid,
        "method": method,
        "image": f"/api/scenes/{scene_id}/image?project_id={pid}&v={int(time.time())}"
    }


@app.get("/api/scenes/{scene_id}/image")
async def scene_image(scene_id: str, project_id: str = ""):
    # M3: el asset de una escena solo se sirve con el project_id correcto.
    _pid(project_id)
    with db.connect() as con:
        row = con.execute("SELECT image_path FROM scenes WHERE id=? AND project_id=?",
                          (scene_id, project_id)).fetchone()
    if not row or not row["image_path"] or not Path(row["image_path"]).exists():
        raise HTTPException(404, "sin imagen")
    return FileResponse(row["image_path"])


@app.get("/api/scenes/{scene_id}/audio")
async def scene_audio(scene_id: str, project_id: str = ""):
    _pid(project_id)  # M3
    with db.connect() as con:
        row = con.execute("SELECT audio_path FROM scenes WHERE id=? AND project_id=?",
                          (scene_id, project_id)).fetchone()
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


# ─────────────────────────────────────────── autopublish YouTube ──
@app.get("/api/publish/status")
async def publish_status():
    return {"configured": youtube_publish.configured(),
            "token": youtube_publish.has_token(),
            "redirect_uri": youtube_publish.redirect_uri()}


@app.get("/api/publish/auth-url")
async def publish_auth_url():
    url = youtube_publish.build_auth_url()
    if not url:
        raise HTTPException(400, "Falta client_secret.json en backend/data/")
    return {"url": url}


def _oauth_page(ok: bool, msg: str) -> str:
    """Página mínima de confirmación del retorno OAuth (loopback)."""
    color = "#22c55e" if ok else "#ef4444"
    icon = "✅" if ok else "❌"
    safe = (msg or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f"<!doctype html><html lang=es><meta charset=utf-8>"
            f"<title>YouTube · {icon}</title>"
            f"<body style='font-family:system-ui;background:#0b1020;color:#e5e7eb;"
            f"display:grid;place-items:center;height:100vh;margin:0;text-align:center'>"
            f"<div><div style='font-size:56px'>{icon}</div>"
            f"<h1 style='color:{color};font-size:22px'>"
            f"{'Canal conectado' if ok else 'No se pudo conectar'}</h1>"
            f"<p style='opacity:.75;max-width:520px'>{safe}</p>"
            f"<p><a href='/' style='color:#60a5fa'>← Volver al dashboard</a></p></div></body>")


@app.get("/api/publish/callback")
async def publish_callback(code: str = "", error: str = ""):
    """Retorno OAuth de Google (loopback, reemplaza el flujo OOB retirado):
    intercambia el código, guarda el token en backend/data/token.json y
    muestra confirmación. El usuario solo autoriza en el navegador."""
    if error:
        return HTMLResponse(_oauth_page(False, f"Google devolvió: {error}"))
    if not code:
        return HTMLResponse(_oauth_page(False, "Faltó el parámetro ?code= en el retorno."),
                            status_code=400)
    if not youtube_publish.configured():
        return HTMLResponse(_oauth_page(False, "Falta backend/data/client_secret.json"),
                            status_code=400)
    try:
        ok = youtube_publish.exchange_code(code)
        msg = ("Token guardado en backend/data/token.json. Ya puedes publicar "
               "desde el dashboard.") if ok else "No se pudo intercambiar el código."
    except Exception as e:  # noqa: BLE001
        ok = False
        msg = f"Error al intercambiar el código: {str(e)[:220]}"
    return HTMLResponse(_oauth_page(ok, msg))


@app.post("/api/publish/exchange")
async def publish_exchange(body: dict):
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "falta el código")
    try:  # M4: un fallo OAuth jamás vuelve a ser un 500
        ok = youtube_publish.exchange_code(code)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"intercambio OAuth falló: {str(e)[:200]}") from e
    return {"ok": ok}


@app.post("/api/publish/{pid}")
async def publish_video(pid: str, body: dict):
    """Publicación manual (side effect EXTERNO). v2.19:
    · IDEMPOTENTE: un proyecto con youtube_id responde 409 (nunca doble
      upload — §idempotencia: publicaciones duplicadas).
    · QA GATE: si meta.qa_final quedó con errores del QA técnico del render
      final, se rechaza 409 (nunca publicar un render fallido — §publishing).
    · publish_state en meta (DRAFT→PUBLISHING→PUBLISHED/FAILED) + cada
      intento queda como job kind=publish (historial auditable)."""
    _pid(pid)
    p = db.get_project(pid)
    if not p or not p.get("video_url"):
        raise HTTPException(404, "video no disponible")
    if p.get("youtube_id"):
        raise HTTPException(409, f"ya publicado (idempotencia): youtube_id={p['youtube_id']}")
    meta = dict(p.get("meta") or {})
    qa = meta.get("qa_final") or {}
    if qa.get("worst") == "error":
        raise HTTPException(409, "QA del render final con errores — "
                                 "publicación bloqueada; re-renderiza el proyecto")
    if not youtube_publish.configured():
        raise HTTPException(400, "Configura client_secret.json (README §Publicar)")
    jid = db.create_job(pid, kind="publish")
    db.update_job(jid, status="running", step="publishing",
                  message="Subiendo a YouTube…")
    db.update_project(pid, meta={**meta, "publish_state": "PUBLISHING"})
    try:
        vid = youtube_publish.upload(
            p["video_url"], body.get("title") or p["title"],
            description=body.get("description", ""),
            tags=body.get("tags", []),
            private=bool(body.get("private", True)),
            publish_at=body.get("publish_at"),
        )
    except Exception as e:  # noqa: BLE001
        db.update_job(jid, status="failed", step="failed", error=str(e)[:500],
                      message=f"publish falló: {str(e)[:120]}")
        db.update_project(pid, meta={**(db.get_project(pid).get("meta") or {}),
                                     "publish_state": "FAILED"})
        raise HTTPException(500, str(e)[:300])
    db.update_job(jid, status="done", step="done", message=f"publicado {vid}")
    db.update_project(pid, status="published", youtube_id=vid,
                      meta={**(db.get_project(pid).get("meta") or {}),
                            "publish_state": "PUBLISHED"})
    return {"youtube_id": vid,
            "url": f"https://youtube.com/watch?v={vid}"}


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
    pid = ((body or {}).get("project_id") or "").strip() or None
    if pid:  # M8/M3: no registrar imágenes contra proyectos inexistentes
        _pid(pid)
        if not db.get_project(pid):
            raise HTTPException(404, "proyecto no existe")
    eid = db.add_ext_image(url, pid, body.get("source", "imagefx"))
    return {"ok": True, "id": eid}


@app.get("/api/extension/pending")
async def extension_pending():
    return {"pending": db.count_ext_images()}


# ─────────────────────── [flow-bridge v1] cola de jobs de Google Flow ──
# Circuito real: enqueue (desde build_script_json, única fuente de prompts)
# → claim atómico por la extensión → heartbeat → complete (binario validado)
# → auto-render con orchestrator.start_flow_render. Contrato en
# services/flow_jobs.py. La autenticación la cubre auth_guard (X-API-Key).

@app.post("/api/extension/flow/jobs/enqueue")
async def flow_jobs_enqueue(body: dict):
    """(Re)genera la cola de jobs del proyecto desde build_script_json.
    Idempotente: conserva los jobs ya done (no re-trabaja assets subidos)."""
    from services import flow_jobs
    pid = ((body or {}).get("project_id") or "").strip()
    if not pid:
        raise HTTPException(400, "falta project_id")
    _pid(pid)  # C1
    fmt = (body or {}).get("format") or "transformacion"
    try:
        return flow_jobs.enqueue_project(pid, fmt=fmt,
                                         brand=(body or {}).get("brand"),
                                         character=(body or {}).get("character"))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/extension/flow/jobs/next")
async def flow_jobs_next(worker: str = "", project_id: str = ""):
    """Claim ATÓMICO del siguiente job (imagen antes que video, escena
    ascendente). 204 = no hay trabajo. Recupera leases expirados al vuelo."""
    from services import flow_jobs
    if not (worker or "").strip():
        raise HTTPException(400, "falta worker")
    if project_id.strip():
        _pid(project_id.strip())  # C1
    job = flow_jobs.claim_next(worker.strip(),
                               pid=project_id.strip() or None)
    if not job:
        from fastapi import Response
        return Response(status_code=204)
    return {"ok": True, "job": job}


@app.post("/api/extension/flow/jobs/{job_id}/heartbeat")
async def flow_jobs_heartbeat(job_id: str, token: str = "", worker: str = ""):
    """Renueva el lease del job reclamado (worker vivo). PHASE 1 · M7:
    exige worker + token + lease vigente — el token SOLO ya no autoriza."""
    from services import flow_jobs
    if not (worker or "").strip():
        raise HTTPException(400, "falta worker (identidad M7 obligatoria)")
    res = flow_jobs.heartbeat(job_id, token, worker=worker.strip())
    if not res:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    return res


@app.post("/api/extension/flow/jobs/{job_id}/complete")
async def flow_jobs_complete(job_id: str, request: Request, token: str = "",
                             worker: str = ""):
    """Sube el asset generado en Flow (binario crudo en el body). Valida
    PNG/JPEG/WEBP con PIL · MP4 con ffprobe. Si es el último job del proyecto
    mapea los assets a las escenas y, si están completas, lanza el render
    automáticamente (orchestrator.start_flow_render)."""
    from services import flow_jobs
    if not (worker or "").strip():  # M7: identidad obligatoria
        raise HTTPException(400, "falta worker (identidad M7 obligatoria)")
    data = await _read_body(request, config.LIMITS["FLOW_JOB_BODY_BYTES"])  # M10/DoS
    try:
        res = flow_jobs.complete(job_id, token, data, worker=worker.strip())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not res:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    pid = res.get("project_id") or ""
    res["auto_render"] = False
    if res.get("project_done") and res.get("renderable") and pid \
            and not db.active_job_for_project(pid):
        try:
            res["render_job_id"] = await orchestrator.start_flow_render(pid)
            res["auto_render"] = True
            log.info("[flow-bridge] assets completos para %s → render automático "
                     "(job %s)", pid, res["render_job_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("[flow-bridge] auto-render falló para %s: %s",
                        pid, str(e)[:200])
    return res


@app.post("/api/extension/flow/jobs/{job_id}/fail")
async def flow_jobs_fail(job_id: str, token: str = "", worker: str = "",
                         body: dict | None = None):
    """Marca error y reintenta (queued) o deja dead al agotar max_attempts
    (imagen 3 · video 2). [execution-contract v1]: errores con prefijo
    CONFIG_* → terminal dead (sin reintento, sin adaptación)."""
    from services import flow_jobs
    if not (worker or "").strip():  # M7: identidad obligatoria
        raise HTTPException(400, "falta worker (identidad M7 obligatoria)")
    res = flow_jobs.fail(job_id, token,
                         ((body or {}).get("error") or "")[:500],
                         worker=worker.strip())
    if not res:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    return res


@app.post("/api/extension/flow/jobs/{job_id}/progress")
async def flow_jobs_progress(job_id: str, token: str = "", worker: str = "",
                             body: dict | None = None):
    """[execution-contract v1] §9 — progreso fino de la máquina de estados
    (FLOW_TAB_READY → CAPABILITIES_CAPTURED → CONTROLS_CONFIGURED →
    CONTROLS_VERIFIED → GENERATION_SUBMITTED → ...). Endpoint ADITIVO: no
    forma parte del contrato de lease congelado (un 400/409 jamás rompe la
    cola; la extensión lo trata fire-and-forget)."""
    from services import flow_jobs
    b = body or {}
    res = flow_jobs.set_exec_state(job_id, token, (b.get("state") or "")[:40],
                                   (b.get("detail") or "")[:300],
                                   b.get("evidence")
                                   if isinstance(b.get("evidence"), dict)
                                   else None,
                                   worker=(worker.strip() or None))  # M7 verify-if-provided
    if res is None:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    if not res.get("ok") and res.get("error") == "invalid_state":
        raise HTTPException(400, "estado no reportable")
    return res


@app.post("/api/extension/flow/jobs/{job_id}/generate-consent")
async def flow_jobs_generate_consent(job_id: str, token: str = "", worker: str = "",
                                     body: dict | None = None):
    """[execution-contract v1.1] §7.1 — CONSENTIMIENTO DE GENERACIÓN
    (corrige CF-E2E-01: PRE-GENERATION CONTRACT GATE NOT ENFORCED, P0).

    Puerta OBLIGATORIA antes de pulsar Generate para jobs de video: la
    extensión/HANDS envía capabilities + control_results y el backend
    re-evalúa execution_contract.config_gate (el juez es el servidor).
      - ALLOW → {ok: True, allowed: True, exec_state: CONTROLS_VERIFIED} —
                solo entonces procede GENERATION_SUBMITTED.
      - DENY  → {ok: True, allowed: False, decision: CONFIG_*} y el job ya
                quedó TERMINAL (dead) en la misma transacción: sin retry,
                sin adaptación de prompt, jamás DONE.
    409 si el token/claim no es válido. Endpoint aditivo: no altera el
    contrato de lease congelado (claim/heartbeat/complete/fail intactos)."""
    from services import flow_jobs
    b = body if isinstance(body, dict) else {}
    res = flow_jobs.generation_consent(job_id, token, b,
                                       worker=(worker.strip() or None))  # M7 verify-if-provided
    if res is None:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    return res


@app.get("/api/extension/flow/jobs/status/{pid}")
async def flow_jobs_status(pid: str):
    """Estado de la cola del proyecto: counts por status + exec_states
    finos del Execution Contract + detalle de jobs. PHASE 1 · A6: la
    consulta recupera leases vencidos (idempotente) — la extensión nunca
    se estanca esperando un claim que no llega."""
    from services import flow_jobs
    _pid(pid)
    return flow_jobs.status_for_project(pid)


# ─────────────────────────────── [qa v1] control de calidad de assets ──
@app.get("/api/video_qa/{pid}")
async def video_qa_endpoint(pid: str):
    """QA REAL del proyecto con ffprobe/PIL: imágenes y clips de Flow por
    escena + render final (si existe). Reporta flags error/warn/ok; nunca
    lanza por assets malos (404 solo si el proyecto no existe)."""
    _pid(pid)
    from services import video_qa
    try:
        return video_qa.qa_project(pid)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


# ─────────────────────────────── [obs v1] métricas de la fábrica ──
@app.get("/api/metrics")
async def metrics_endpoint():
    """Snapshot de observabilidad: proyectos/cola Flow/jobs por estado,
    escenas sin imagen, disco y tasas §observabilidad (producción/pasos/
    reintentos/QA/publicación — lo no medible localmente queda null)."""
    from services import metrics
    return metrics.snapshot()


# ───────────────────────────────────── contrato agente-a-agente (A2A) ──
@app.post("/api/agent/execute")
async def agent_execute(body: dict):
    """CONTRATO A2A — la única puerta formal para que OTRO agente (p. ej. el
    Creative Engine) encargue una producción. No acepta comandos ambiguos
    como autoridad: exige requester + creative_spec; spec inválida →
    VALIDATION_ERROR; spec con avisos (defaults mecánicos) y sin lanzar →
    REQUIRES_CLARIFICATION (§creative boundary: la fábrica NO inventa).
    Salida: {status, production_id, result, evidence, confidence,
    execution_id, warnings}."""
    requester = (body.get("requester") or "").strip()
    spec = body.get("creative_spec",
                    body.get("production", body.get("production_json")))
    requested = body.get("requested_output") or {}
    if not requester:
        raise HTTPException(400, "contrato A2A: falta «requester» "
                                 "(identidad del agente solicitante)")
    if spec is None:
        raise HTTPException(400, "contrato A2A: falta «creative_spec» "
                                 "(Creative Production JSON)")
    lanzar = bool(requested.get("launch") or body.get("auto_start"))

    def _crear(g: dict):
        pmeta = {}
        if g.get("camara"):
            pmeta["camara"] = g["camara"]
        return db.create_project(
            title=(g.get("titulo") or f"Producción A2A ({requester})"),
            mode="production_json", style=g.get("estilo") or "auto",
            format=g.get("formato") or "short", voice=g.get("voz"),
            meta=pmeta, platforms=g.get("plataformas") or ["youtube"],
            niche=g.get("nicho"))

    try:
        rep = await prod_svc.ingest(
            spec, {s["id"] for s in STYLES}, _crear,
            auto_start_override=True if lanzar else None)
    except ValueError as e:
        return {"status": "VALIDATION_ERROR", "production_id": None,
                "result": None,
                "evidence": [{"kind": "value_error", "msg": str(e)[:500]}],
                "confidence": 0.0, "execution_id": None, "warnings": []}
    avisos = list(rep.get("avisos") or [])
    status = ("EXECUTING" if rep.get("job_id")
              else ("REQUIRES_CLARIFICATION" if avisos else "ACCEPTED"))
    return {
        "status": status,
        "production_id": rep.get("project_id"),
        "result": {"unidades": rep.get("unidades"),
                   "unit_types": rep.get("unit_types"),
                   "formato": rep.get("formato"), "estilo": rep.get("estilo")},
        "evidence": [{"kind": "production_json",
                      "sha256": (rep.get("production_file") or {}).get("sha256"),
                      "path": (rep.get("production_file") or {}).get("path")}],
        "confidence": 1.0 if status == "EXECUTING" else 0.7,
        "execution_id": rep.get("job_id"),
        "warnings": avisos,
    }


# ────────────────────────────────────────────────────── import audio ──
@app.post("/api/import/audio")
async def import_audio(file: UploadFile = File(...)):
    """v2.19 · blindaje: el nombre del upload era origen NO confiable
    (path traversal: «../../.env» escribía fuera de TMP_DIR). Ahora basename
    + lista blanca [A-Za-z0-9._-] (security.safe_filename) + prefijo uuid
    (anti colisión) + tope de tamaño (50 MB)."""
    import uuid as _uuid
    try:
        base = security.safe_filename(file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    dest = TMP_DIR / f"voice_upload_{_uuid.uuid4().hex[:8]}_{base}"
    MAX_BYTES = 50 * 1024 * 1024
    written = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "audio demasiado grande (>50 MB)")
            f.write(chunk)
    return {"path": str(dest)}


# ───────────────────────────────────── doctor de salud (Fase 3) ──
@app.get("/api/doctor")
async def doctor():
    """Sondas REALES del stack $0 (ffmpeg, TTS, whisper, claves, disco).
    Patrón probe_command: cada check ejecuta un comando, no supone nada."""
    return await doctor_svc.run_doctor()


# ───────────────────────────── PRODUCTION DOCTOR V1.0 (transversal) ──
# Diagnóstico por capas A-I del pipeline completo + reparaciones seguras
# (lista blanca) + REAL FLOW PREFLIGHT. Capa de diagnóstico SOBRE el
# sistema existente: no crea backend/cola/tests paralelos.

@app.post("/api/production_doctor/audit")
async def production_doctor_audit(body: dict | None = None):
    """DOCTOR AUDIT: diagnostica las 9 capas sin modificar nada."""
    from services.production_doctor import audit as pdoc_audit
    body = body or {}
    return await asyncio.to_thread(
        pdoc_audit, deep=bool(body.get("deep")),
        in_process=True)  # dentro del servidor: juicio preciso de zombies


@app.post("/api/production_doctor/fix")
async def production_doctor_fix(body: dict | None = None):
    """DOCTOR FIX: diagnostica, aplica SOLO reparaciones seguras
    (lista blanca determinista), re-verifica capas y tests afectados."""
    from services.production_doctor import fix as pdoc_fix
    body = body or {}
    return await asyncio.to_thread(
        pdoc_fix, deep=bool(body.get("deep")), in_process=True,
        ejecutar_tests=bool(body.get("ejecutar_tests", True)))


@app.post("/api/production_doctor/verify")
async def production_doctor_verify(body: dict | None = None):
    """DOCTOR VERIFY: re-ejecuta checks + baterías de los componentes."""
    from services.production_doctor import verify as pdoc_verify
    body = body or {}
    return await asyncio.to_thread(
        pdoc_verify, deep=bool(body.get("deep")), in_process=True,
        capas=body.get("capas"), componentes=body.get("componentes"),
        ejecutar_tests=bool(body.get("ejecutar_tests", True)))


@app.get("/api/production_doctor/report")
async def production_doctor_report():
    """DOCTOR REPORT: último informe persistido (o audit fresco)."""
    from services.production_doctor import report as pdoc_report
    return await asyncio.to_thread(pdoc_report)


@app.get("/api/production_doctor/preflight")
async def production_doctor_preflight(project_id: str | None = None):
    """REAL FLOW PREFLIGHT: barrera antes de una prueba real con Google
    Flow. Devuelve REAL FLOW PREFLIGHT PASS o REAL FLOW BLOCKED + motivos."""
    if project_id:
        _pid(project_id)  # C1
    from services.production_doctor import preflight as pdoc_preflight
    return await asyncio.to_thread(pdoc_preflight, project_id)


# ──────────────────────────────── tendencias $0 sin API key (Fase 3) ──
@app.get("/api/trends/probe")
async def trends_probe():
    return trends_svc.probe_ytdlp()


@app.post("/api/trends/research")
async def trends_research(body: dict):
    """Investiga un nicho en YouTube con yt-dlp (metadata real, sin API key)
    y devuelve insights + ideas de shorts (Gemini o heurístico)."""
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "falta query")
    try:
        research = await trends_svc.research_topic(
            query, int(body.get("max_videos") or 8),
            bool(body.get("with_comments")),
            body.get("cookies_from_browser") or None)
    except RuntimeError as e:
        raise HTTPException(400, str(e)[:200])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"investigación falló: {str(e)[:150]}")
    ideas = await trends_svc.ideas_from_research(
        research, int(body.get("n_ideas") or 5))
    return {"ok": True, "research": research, "ideas": ideas}


# ─────────────────────────────────────────────────────── dashboard ──
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# v2.8/v2.10.2 · servidor MCP (JSON-RPC 2.0) — puerta para agentes locales
from fastapi import Request as _Req
from services import mcp_server  # noqa: E402  (tras crear `app` para evitar círculos)
app.mount("/mcp", mcp_server.app)

# ── YOUTUBE HARNESS CONTRACT V1 (transformación final §6/§16) ──────
# Arnés especializado agnóstico del host: fachada de dominio sobre la
# fábrica. Router versionado /api/harness/v1 — hereda auth_guard,
# csrf_guard y límites de body por ser middlewares de app (sin bypass).
from services.youtube_harness import api as harness_api  # noqa: E402
app.include_router(harness_api.router)

# ── Extensiones de Calidad Audiovisual (Adopción CHAT-X) ───────────
from services import lighting_presets as _lighting_svc  # noqa: E402
from services import qa_forensics_checker as _qa_forensics_svc  # noqa: E402
from services import voice_cloner as _voice_cloner_svc  # noqa: E402


@app.get("/api/studio/lighting-presets")
async def get_lighting_presets(categoria: Optional[str] = None):
    """Presets de iluminación de estudio y estilo UGC auténtico de CHAT-X."""
    return {"ok": True, "presets": _lighting_svc.list_lighting_presets(categoria)}


@app.get("/api/studio/voice-clon/probe")
async def probe_voice_clon():
    """Sonda honesta de capacidades de clonación local de voz."""
    return {"ok": True, "status": _voice_cloner_svc.check_cloning_subsystem()}


@app.post("/api/studio/media/inspect")
async def inspect_media_binary(body: dict):
    """Inspección de integridad forense por magic bytes reales y silencio."""
    file_path = (body.get("file_path") or "").strip()
    expected = (body.get("expected_type") or "").strip() or None
    if not file_path:
        raise HTTPException(400, "falta file_path")
    return _qa_forensics_svc.inspect_media_file(file_path, expected_type=expected)



@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp_sin_barra(req: _Req):
    """Proxy de /mcp exacto → evita el 307 a /mcp/ para clientes MCP."""
    if req.method == "GET":
        return await mcp_server.info()
    return await mcp_server.entry(req)


# ─────────────── MCP Connection Manager (INT-022) · panel ↔ servidores ──
# Cliente MCP persistente en el backend: el panel (navegador) no puede
# hablar stdio; estos endpoints exponen conectar/estado/ejecutar/probar.
# Heredan auth_guard y csrf_guard por ser middlewares de app (sin bypass).
from services import mcp_manager as _mcpm  # noqa: E402


def _svc(body: dict) -> str:
    s = (body.get("service") or "").strip().lower()
    if s not in _mcpm.SERVICES:
        raise HTTPException(400, "service debe ser 'google-flow' o 'notebooklm'")
    return s


@app.post("/api/mcp/connect")
async def mcp_connect(body: dict):
    """Conecta el servicio MCP y ejecuta el preflight de sesión (§2).
    AUTH_REQUIRED llega como estado (no como 5xx) para pintar el badge rojo."""
    try:
        return await _mcpm.manager.connect(
            _svc(body), notebook_id=(body.get("notebook_id") or "").strip() or None)
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.post("/api/mcp/disconnect")
async def mcp_disconnect(body: dict):
    return await _mcpm.manager.disconnect(_svc(body))


@app.get("/api/mcp/status")
async def mcp_status():
    """Estado en vivo de ambos servicios + pistas de configuración."""
    return await _mcpm.manager.status()


@app.post("/api/mcp/execute")
async def mcp_execute(body: dict):
    """Despacha una tool al servidor MCP activo (§1).
    - tool: nombre exacto (validado contra tools/list y allowlist si aplica)
    - arguments: dict libre; para notebooklm se inyecta notebook_id dinámico (§3)
      con fallback NOTEBOOKLM_NOTEBOOK_ID y validación de patrón.
    - auth_required/timeout se reportan con código estable para la UI."""
    tool = (body.get("tool") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", tool):
        raise HTTPException(400, "tool inválida")
    args = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
    try:
        return await _mcpm.manager.execute(
            _svc(body), tool, args,
            timeout=float(body.get("timeout")) if body.get("timeout") else None,
            notebook_id=(body.get("notebook_id") or "").strip() or None,
            auto_connect=bool(body.get("auto_connect", True)))
    except _mcpm.MCPManagerError as e:
        status = 504 if e.code == "TIMEOUT" else 502
        raise HTTPException(status, f"[{e.code}] {e}") from e


@app.post("/api/mcp/test-pipeline")
async def mcp_test_pipeline(body: dict):
    """Dry-run (§4 'Test Pipeline'): conecta si hace falta, verifica sesión
    Google, CDP del Chrome dedicado y validez del notebookId. No genera nada."""
    service = (body.get("service") or "").strip().lower()
    targets = list(_mcpm.SERVICES) if not service else [_svc(body)]
    notebook_id = (body.get("notebook_id") or "").strip() or None
    out = {t: await _mcpm.manager.test_pipeline(t, notebook_id=notebook_id)
           for t in targets}
    out["ok"] = all(v.get("ok") for v in out.values())
    return out


@app.post("/api/mcp/list-notebooks")
async def mcp_list_notebooks(body: dict):
    """Lista los notebooks de la cuenta vía la tool de listado del MCP de
    NotebookLM (notebook_list / list_notebooks). Alimenta el dropdown
    «📋 Listar mis Notebooks» del panel para fijar el notebook activo con
    1 click (HOTFIX INT-023.4: fin de copiar UUIDs desde la URL)."""
    try:
        return await _mcpm.manager.list_notebooks(
            notebook_id=(body.get("notebook_id") or "").strip() or None)
    except _mcpm.MCPManagerError as e:
        status = 502
        raise HTTPException(status, f"[{e.code}] {e}") from e


# ─────────── Sesión Google unificada (INT-025) · google_profile_global ──
@app.post("/api/mcp/launch-auth-browser")
async def mcp_launch_auth_browser():
    """🔑 «Vincular Sesión Google (Login Único)» — lanza el Chrome REAL con
    el perfil persistente COMPARTIDO (google_profile_global) y CDP en
    GOOGLE_LOGIN_CDP_PORT (= FLOW_CDP_PORT 9333), abriendo
    https://flow.google.com/ + NotebookLM (GOOGLE_LOGIN_PAGES).
    Si ya hay Chrome vivo en ese puerto NO lo relanza (already_up=true):
    el singleton del perfil reenvía la petición a la instancia existente y
    el flujo humano continúa en su ventana. Tras loguearse, «🔄 Refrescar
    estado» o «🧪 Test Pipeline» validan las cookies y ponen los badges
    green (preflight de sesión §2)."""
    try:
        return await _mcpm.manager.launch_google_login(
            list(getattr(config, "GOOGLE_LOGIN_PAGES", []) or []) or None)
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.post("/api/mcp/launch-clean-login")
async def mcp_launch_clean_login():
    """🔑 Abre Chrome en modo limpio (sin CDP) para login humano sin bloqueo de Google."""
    try:
        pages = list(getattr(config, "GOOGLE_LOGIN_PAGES", [])) or [
            "https://accounts.google.com/ServiceLogin?continue=https://labs.google/fx/tools/flow",
            "https://notebooklm.google.com/"
        ]
        return await _mcpm.manager.launch_google_login(pages, cdp=False)
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.post("/api/mcp/connect-all-google")
async def mcp_connect_all_google():
    """🚀 1-Clic: Sanea perfil, levanta Chrome interactivo en puerto 9333 y conecta Flow + NotebookLM."""
    try:
        return await _mcpm.manager.connect_all_google()
    except Exception as e:
        raise HTTPException(500, f"Error al conectar servicios Google: {e}") from e


@app.post("/api/mcp/repair-profile")
async def mcp_repair_profile():
    """🔧 Sanea el perfil de Chrome (elimina Local State.bad, bloqueos y repara exit_type)."""
    try:
        return _mcpm.manager.repair_profile()
    except Exception as e:
        raise HTTPException(500, f"Error al reparar perfil: {e}") from e


@app.post("/api/mcp/login-google")
async def mcp_login_google():
    """🔑 Lanza (o reutiliza) el Chrome REAL con el user-data-dir global
    (google_profile_global) abierto en el login de Google. Un solo login
    humano: Flow hereda la sesión por CDP (mismo Chrome/puerto) y NotebookLM
    la captura con «📥 Capturar sesión»."""
    try:
        return await _mcpm.manager.launch_google_login()
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.get("/api/mcp/login-google")
async def mcp_login_google_status():
    """Estado de la sesión unificada: Chrome CDP arriba/abajo, perfil
    compartido, y storage_state de NotebookLM (ruta activa/existencia)."""
    return await _mcpm.manager.google_login_status()


@app.post("/api/mcp/capture-google-session")
async def mcp_capture_google_session():
    """📥 Extrae las cookies Google del Chrome de login (CDP) y las escribe
    en el storage_state.json de notebooklm-py → un login manual cubre ambos
    MCP. Errores estables: CHROME_NOT_UP / PLAYWRIGHT_MISSING /
    NO_GOOGLE_COOKIES."""
    try:
        return await _mcpm.manager.capture_google_session()
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


# ───────── Google One-Tap Hub (INT-071) · [G] Continuar con Google ──
@app.post("/api/mcp/google-sso")
async def mcp_google_sso():
    """[G] Estado A del Hub: abre Chrome con el perfil global (CDP 9333)
    en el selector de cuentas (AccountChooser → Flow) + NotebookLM y arranca
    el watchdog (poll GOOGLE_SSO_POLL_S=2s) que detecta la cookie
    __Secure-1PSID/SID; al verla captura storage_state.json, conecta
    Flow + NotebookLM y extrae la cuenta. Respuesta inmediata (watching)."""
    try:
        return await _mcpm.manager.google_sso_start()
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.get("/api/mcp/google-sso/status")
async def mcp_google_sso_status():
    """Estado del Hub para la UI: fase SSO (idle/watching/connecting/
    connected/timeout), cuenta activa (si se pudo extraer), pills por
    servicio (Google Flow · NotebookLM MCP · Workspace & Gemini), CDP y
    storage_state. Barato: 1 llamada CDP por poll."""
    try:
        return await _mcpm.manager.google_sso_status()
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


@app.post("/api/mcp/google-sso/logout")
async def mcp_google_sso_logout():
    """🚪 Cambiar cuenta / Desconectar: cancela el watchdog, desconecta
    Flow + NotebookLM, ARCHIVA storage_state.json (.bak-<ts>) y cierra el
    Chrome del perfil global. El siguiente «Continuar con Google» parte
    limpio en el selector de cuentas."""
    try:
        return await _mcpm.manager.google_sso_logout()
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e


# ───────── NotebookLM Studio Bridge (INT-069) · Audio Overview PoC ──
# Flujo: garantizar notebook → fuente de texto (guion) → studio_generate
# (artifact_type="audio") → poll studio_status → studio_download a exports.
# Tools MCP reales de notebooklm-py v0.8.5 (ver nlm_studio.py docstring).
@app.post("/api/nlm/studio/audio-overview")
async def nlm_studio_audio_overview(body: dict):
    """🎬 INT-069: Arranca la generación de un Audio Overview de NotebookLM
    con el texto dado (guion/contenido). NO bloquea: garantiza notebook,
    añade la fuente y devuelve 202 con el job "generating"; el poll y la
    descarga a exports los hace la tarea de fondo (status/download abajo)."""
    from services import nlm_studio
    if not nlm_studio.enabled():
        raise HTTPException(404, "NotebookLM Studio Bridge deshabilitado "
                                 "(NLM_STUDIO_ENABLED=0)")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "campo 'text' requerido (guion/contenido de la fuente)")
    notebook_id = (body.get("notebook_id") or "").strip() or None
    title = (body.get("title") or "").strip() or None
    try:
        job = await nlm_studio.start_audio_overview(
            notebook_id=notebook_id, title=title, text=text)
    except nlm_studio.NLMStudioError as e:
        status = 409 if e.code == "GENERATION_IN_PROGRESS" else 502
        raise HTTPException(status, f"[{e.code}] {e}") from e
    except _mcpm.MCPManagerError as e:
        raise HTTPException(502, f"[{e.code}] {e}") from e
    return JSONResponse(status_code=202, content={"ok": True, **job})


@app.get("/api/nlm/studio/status/{notebook_id}")
async def nlm_studio_status(notebook_id: str):
    """📊 INT-069: Estado del job del Studio Bridge para un notebook
    (idle | generating | ready | error) con task_id/ruta del fichero."""
    from services import nlm_studio
    if not nlm_studio.enabled():
        raise HTTPException(404, "NotebookLM Studio Bridge deshabilitado "
                                 "(NLM_STUDIO_ENABLED=0)")
    return {"ok": True, **nlm_studio.job_status(notebook_id.strip())}


@app.get("/api/nlm/studio/download/{notebook_id}")
async def nlm_studio_download(notebook_id: str):
    """⬇️ INT-069: Devuelve el ÚLTIMO audio exportado del notebook
    (.m4a AAC/MP4 en v0.8.5 — upstream #2034) como FileResponse."""
    from services import nlm_studio
    if not nlm_studio.enabled():
        raise HTTPException(404, "NotebookLM Studio Bridge deshabilitado "
                                 "(NLM_STUDIO_ENABLED=0)")
    try:
        p = nlm_studio.latest_audio(notebook_id.strip())
    except nlm_studio.NLMStudioError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e
    media = "audio/mp4" if p.suffix.lower() == ".m4a" else "audio/mpeg"
    return FileResponse(p, media_type=media, filename=p.name)


# ─────────────────────────── VIRAL CLIPPER (INT-044) ──────────────────────
# Inspirado en OpenShorts (mutonby/openshorts): Detección de momentos virales con
# Virality Score (0-100), recorte 9:16 vertical con FFmpeg y conversión a proyectos.
from services import viral_clipper  # noqa: E402


@app.post("/api/clipper/analyze")
async def clipper_analyze(body: dict):
    """🔍 Analiza un video largo/podcast y detecta los mejores momentos virales con Virality Score."""
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Se requiere una URL válida de video o podcast")
    count = int(body.get("count", 5))
    min_dur = int(body.get("min_duration", 20))
    max_dur = int(body.get("max_duration", 65))
    cookies = (body.get("cookies") or "").strip() or None
    try:
        return await viral_clipper.detect_viral_moments(
            url, count=count, min_duration=min_dur, max_duration=max_dur, cookies=cookies
        )
    except viral_clipper.ViralClipperError as e:
        raise HTTPException(400, f"[{e.code}] {e}") from e
    except Exception as e:
        raise HTTPException(500, f"Error al analizar video: {e}") from e


@app.post("/api/clipper/render")
async def clipper_render(body: dict):
    """🎬 Recorta un fragmento exacto y lo reencuadra con FFmpeg a vertical 9:16 (blur_bg)."""
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "URL requerida")
    start = float(body.get("start", 0))
    end = float(body.get("end", 0))
    if end <= start:
        raise HTTPException(400, "El tiempo de fin debe ser mayor al de inicio")
    title = (body.get("title") or "Short").strip()
    style = (body.get("style") or "blur_bg").strip()
    subtitle_text = (body.get("subtitle_text") or "").strip() or None
    subtitle_style = (body.get("subtitle_style") or "none").strip()
    auto_emojis = bool(body.get("auto_emojis", True))
    progress_bar = bool(body.get("progress_bar", True))
    broll = bool(body.get("broll", False))
    broll_query = (body.get("broll_query") or "").strip() or None
    cookies = (body.get("cookies") or "").strip() or None
    try:
        return await viral_clipper.render_vertical_moment(
            url, start=start, end=end, title=title, style=style,
            subtitle_text=subtitle_text, subtitle_style=subtitle_style,
            broll=broll, broll_query=broll_query,
            cookies=cookies, auto_emojis=auto_emojis,
            progress_bar=progress_bar
        )
    except viral_clipper.ViralClipperError as e:
        raise HTTPException(400, f"[{e.code}] {e}") from e
    except Exception as e:
        raise HTTPException(500, f"Error al renderizar short vertical: {e}") from e



@app.post("/api/product/scrape")
async def product_scrape(body: dict):
    """🛍️ INT-054: Extrae metadatos de producto de una tienda web o texto (v4v.ai Cloned)."""
    target = (body.get("url") or body.get("text") or "").strip()
    if not target:
        raise HTTPException(400, "URL o descripción de producto requerida")
    from services import ugc_ad_generator
    info = ugc_ad_generator.scrape_product_info(target)
    return {"ok": True, "product": info}


@app.post("/api/avatars/{avatar_id}/circle-pip")
async def avatar_circle_pip(avatar_id: str, body: dict | None = None):
    """🔘 INT-058: Genera el recorte circular de presentador flotante estilo HeyGen / Synthesia."""
    av = db.get_avatar(avatar_id)
    if not av:
        raise HTTPException(404, "Avatar no encontrado")
    img_p = av.get("image_path")
    if not img_p or not Path(img_p).is_file():
        raise HTTPException(400, "El avatar no tiene un retrato generado")

    b_color = (body or {}).get("border_color", "cyan")
    from services.avatar_pip import create_circle_avatar
    out_dir = STATIC_DIR / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"avatar_pip_{avatar_id}_{b_color}.png"
    create_circle_avatar(Path(img_p), diameter=340, border_color=b_color, output_path=out_path)
    return {"ok": True, "pip_url": f"/static/assets/{out_path.name}"}


@app.post("/api/avatars/{avatar_id}/animate-liveportrait")
async def avatar_animate_liveportrait(avatar_id: str, body: dict | None = None):
    """🎭 INT-066: Anima la foto del avatar con parpadeo y micro-movimientos LivePortrait."""
    av = db.get_avatar(avatar_id)
    if not av:
        raise HTTPException(404, "Avatar no encontrado")
    img_p = av.get("image_path")
    if not img_p or not Path(img_p).is_file():
        raise HTTPException(400, "El avatar no tiene un retrato generado")

    duration = float((body or {}).get("duration_sec", 4.0))
    from services.avatar_motion import animate_liveportrait_local
    out_dir = STATIC_DIR / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"avatar_lp_{avatar_id}.mp4"

    animate_liveportrait_local(Path(img_p), output_video=out_path, duration_sec=duration)
    db.update_avatar(avatar_id, video_path=str(out_path))

    return {
        "ok": True,
        "engine": "LivePortrait",
        "video_url": f"/static/assets/{out_path.name}",
        "duration_sec": duration
    }


@app.post("/api/avatars/{avatar_id}/lipsync-musetalk")
async def avatar_lipsync_musetalk(avatar_id: str, body: dict):
    """👄 INT-066: Genera sincronización labial fonética con audio/texto MuseTalk."""
    av = db.get_avatar(avatar_id)
    if not av:
        raise HTTPException(404, "Avatar no encontrado")
    img_p = av.get("image_path")
    if not img_p or not Path(img_p).is_file():
        raise HTTPException(400, "El avatar no tiene un retrato generado")

    text = (body.get("text") or "").strip()
    voice = (body.get("voice") or av.get("voice") or "es-ES-AlvaroNeural").strip()

    if not text:
        text = f"Hola, soy tu presentador virtual generado con inteligencia artificial. ¿Qué video fabricamos hoy?"

    out_dir = STATIC_DIR / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    import hashlib
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
    wav_path = out_dir / f"audio_{avatar_id}_{text_hash}.wav"
    mp3_path = wav_path.with_suffix(".mp3")

    # Sintetizar audio con edge-tts
    import edge_tts
    comm = edge_tts.Communicate(text, voice)
    await comm.save(str(mp3_path))

    # Convertir a WAV 16-bit PCM estándar para el análisis fonético
    cmd = ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)]
    subprocess.run(cmd, capture_output=True, check=True)

    from services.avatar_motion import lipsync_musetalk_local
    out_video = out_dir / f"avatar_mt_{avatar_id}_{text_hash}.mp4"
    lipsync_musetalk_local(Path(img_p), wav_path, out_video)

    return {
        "ok": True,
        "engine": "MuseTalk",
        "video_url": f"/static/assets/{out_video.name}",
        "audio_url": f"/static/assets/{mp3_path.name}",
        "spoken_text": text
    }


@app.post("/api/product/badge")
async def product_badge(body: dict):
    """🛍️ INT-055: Genera un badge de conversión e-commerce en PNG transparente."""
    from services import ecommerce_overlays
    badge_type = body.get("type") or "rating"
    text_main = body.get("text")
    tag = body.get("tag")
    out_dir = STATIC_DIR / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"badge_{badge_type}.png"
    p = ecommerce_overlays.generate_ecommerce_badge(
        badge_type=badge_type,
        text_main=text_main,
        tag=tag,
        out_path=out_file
    )
    return {"ok": True, "badge_url": f"/static/assets/{p.name}"}


@app.get("/api/dubbing/languages")
async def dubbing_languages():
    """🌍 INT-068: Catálogo de idiomas y voces neuronales para doblaje multi-idioma (MrBeast Style)."""
    from services import multilang_dubber
    return {"ok": True, "languages": multilang_dubber.DUB_LANGUAGES}


@app.post("/api/dubbing/translate")
async def dubbing_translate(body: dict):
    """🌐 INT-068: Traduce el guion al idioma objetivo manteniendo ganchos y cifras."""
    from services import multilang_dubber
    text = (body.get("text") or "").strip()
    target_lang = (body.get("target_lang") or "en").strip().lower()
    translated = await multilang_dubber.translate_text(text, target_lang)
    return {"ok": True, "target_lang": target_lang, "translated_text": translated}


@app.post("/api/dubbing/dub-video")
async def dubbing_dub_video(body: dict):
    """🎬 INT-068: Genera versión doblada de video sustituyendo la pista de audio con FFmpeg."""
    from services import multilang_dubber
    video_url_or_path = (body.get("video_path") or "").strip()
    script = (body.get("script") or "").strip()
    target_lang = (body.get("target_lang") or "en").strip().lower()

    if not script:
        raise HTTPException(400, "Guion requerido para síntesis doblada")

    # Traducir guion
    translated_text = await multilang_dubber.translate_text(script, target_lang)

    out_dir = STATIC_DIR / "dubbed_videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    h = hashlib.md5(f"{translated_text}_{target_lang}".encode()).hexdigest()[:8]
    dubbed_audio = out_dir / f"dub_audio_{target_lang}_{h}.wav"

    await multilang_dubber.synthesize_dubbed_speech(translated_text, target_lang, dubbed_audio)

    # Si hay video original, sustituir audio con FFmpeg
    output_video_url = None
    if video_url_or_path and Path(video_url_or_path).is_file():
        dubbed_video = out_dir / f"video_{target_lang}_{h}.mp4"
        multilang_dubber.swap_video_audio(Path(video_url_or_path), dubbed_audio, dubbed_video)
        output_video_url = f"/static/dubbed_videos/{dubbed_video.name}"

    return {
        "ok": True,
        "target_lang": target_lang,
        "translated_text": translated_text,
        "dubbed_audio_url": f"/static/dubbed_videos/{dubbed_audio.name}",
        "dubbed_video_url": output_video_url
    }


@app.post("/api/invideo/auto-dress")
async def invideo_auto_dress(body: dict):
    """🎬 INT-064: Planifica e inyecta B-Roll y SFX automáticos de retención (InVideo AI & OpusClip Cloned)."""
    from services import invideo_dress
    scenes = body.get("scenes") or []
    if not scenes:
        # Default mock scenes si viene vacío
        scenes = [
            {"scene_id": "scene_1", "duration_sec": 3.8, "narration": "¡Cuidado! Este error te está costando más de $500 al mes sin saberlo."},
            {"scene_id": "scene_2", "duration_sec": 4.5, "narration": "La mayoría de personas invierte su dinero en cosas que se devalúan de inmediato."},
            {"scene_id": "scene_3", "duration_sec": 3.5, "narration": "El truco está en automatizar tus ahorros en activos con interés compuesto."},
            {"scene_id": "scene_4", "duration_sec": 4.0, "narration": "Haz clic en el enlace para aprender el sistema paso a paso hoy mismo."}
        ]
    total_dur = body.get("total_duration_sec")
    enable_sfx = body.get("enable_sfx", True)
    enable_broll = body.get("enable_broll", True)

    manifest = invideo_dress.auto_dress_timeline(
        scenes=scenes,
        total_duration_sec=total_dur,
        enable_sfx=enable_sfx,
        enable_broll=enable_broll
    )
    return manifest


@app.post("/api/invideo/preview-sfx")
async def invideo_preview_sfx(body: dict):
    """🔊 INT-064: Devuelve la ruta o URL del efecto de sonido para preescucha en navegador."""
    from services import sfx_manager
    sfx_type = (body.get("type") or "whoosh").strip().lower()
    lib = sfx_manager.ensure_sfx_library()
    if sfx_type not in lib or not lib[sfx_type].is_file():
        raise HTTPException(404, f"Efecto de sonido '{sfx_type}' no disponible")
    
    # Copiar a static/assets si no está accesible directamente por web
    sfx_path = lib[sfx_type]
    out_dir = STATIC_DIR / "assets" / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    web_file = out_dir / sfx_path.name
    if not web_file.is_file() or web_file.stat().st_size != sfx_path.stat().st_size:
        import shutil
        shutil.copy2(sfx_path, web_file)

    return {"ok": True, "type": sfx_type, "sfx_url": f"/static/assets/sfx/{web_file.name}"}


@app.post("/api/product/callout-layer")
async def product_callout_layer(body: dict):
    """🏷️ INT-062: Genera capa PNG con pines/callouts flotantes dinámicos del producto (JoggAI/InVideo)."""
    from services import ecommerce_overlays
    import time
    callouts = body.get("callouts") or []
    if not callouts:
        # Default 2 callouts si no se especifican
        callouts = [
            {"preset": "battery", "target_x": 420, "target_y": 850, "direction": "top_right"},
            {"preset": "power", "target_x": 580, "target_y": 1150, "direction": "bottom_left"}
        ]
    out_dir = STATIC_DIR / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"callouts_{int(time.time())}.png"
    p = ecommerce_overlays.generate_product_callout_layer(
        callouts=callouts,
        canvas_size=(1080, 1920),
        output_path=out_file
    )
    return {
        "ok": True,
        "callouts_url": f"/static/assets/{p.name}",
        "callouts_count": len(callouts),
        "presets_available": list(ecommerce_overlays.FEATURE_PRESETS.keys())
    }


@app.post("/api/product/studio-preview")
async def product_studio_preview(body: dict):
    """🛍️ INT-056: Previsualización de recorte AI de producto y set de estudio cinemático."""
    from services import ecommerce_overlays
    image_url = body.get("image_url")
    style = body.get("style") or "luxury_dark"
    if not image_url:
        raise HTTPException(400, "image_url requerida")

    out_dir = STATIC_DIR / "studio_previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    import urllib.request
    import time
    timestamp = int(time.time())
    raw_img = out_dir / f"raw_{timestamp}.png"
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw_img.write_bytes(resp.read())

    cutout = out_dir / f"cutout_{timestamp}.png"
    ecommerce_overlays.remove_product_background(raw_img, cutout)

    studio_final = out_dir / f"studio_{timestamp}.jpg"
    ecommerce_overlays.composite_product_on_studio(
        cutout,
        background_style=style,
        output_path=studio_final,
        width=540,
        height=960
    )
    return {
        "ok": True,
        "studio_preview_url": f"/static/studio_previews/{studio_final.name}",
        "cutout_url": f"/static/studio_previews/{cutout.name}"
    }


@app.post("/api/ugc/multi-angle-hooks")
async def ugc_multi_angle_hooks(body: dict):
    """🎭 INT-061: Genera 5 ganchos psicológicos UGC multi-ángulo (Arcads/CreateUGC Cloned)."""
    from services import ugc_hooks
    name = (body.get("product_name") or body.get("name") or "").strip()
    problem = (body.get("problem") or "").strip()
    benefit = (body.get("benefit") or "").strip()
    action = (body.get("action") or "").strip()
    target_audience = (body.get("target_audience") or "").strip()
    hooks = ugc_hooks.generate_multi_angle_hooks(
        name=name,
        problem=problem,
        benefit=benefit,
        action=action,
        target_audience=target_audience
    )
    return {"ok": True, "product_name": name, "hooks": hooks}


@app.post("/api/ugc/ab-variants")
async def ugc_ab_variants(body: dict):
    """🎭 INT-061: Construye variantes de producción A/B combinando ganchos con cuerpo y CTA."""
    from services import ugc_hooks
    name = (body.get("product_name") or body.get("name") or "").strip()
    base_body = (body.get("base_body") or body.get("body") or "").strip()
    base_cta = (body.get("base_cta") or body.get("cta") or "").strip()
    hooks = body.get("hooks")
    variants = ugc_hooks.build_ab_variants(
        product_name=name,
        base_body=base_body,
        base_cta=base_cta,
        hooks=hooks
    )
    return {"ok": True, "product_name": name, "variants": variants}


@app.post("/api/ugc/preview-tts-hook")
async def ugc_preview_tts_hook(body: dict):
    """🎧 INT-061: Genera audio instantáneo gratuito del gancho para preescucha (Edge-TTS)."""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Texto requerido")
    voice = (body.get("voice") or "es-ES-AlvaroNeural").strip()
    import hashlib
    h = hashlib.md5(f"{text}_{voice}".encode()).hexdigest()[:10]
    out_dir = STATIC_DIR / "hook_previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"hook_{h}.mp3"

    if not out_file.is_file():
        import edge_tts
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(out_file))

    return {"ok": True, "audio_url": f"/static/hook_previews/{out_file.name}"}

@app.post("/api/clipper/suggest-broll")
async def clipper_suggest_broll(body: dict):
    """🎥 Sugiere palabras clave visuales para B-Roll de apoyo a partir del texto."""
    text = (body.get("text") or "").strip()
    try:
        from services import broll_overlay
        kws = await broll_overlay.extract_broll_keywords_ai(text, max_keywords=3)
        return {"ok": True, "keywords": kws}
    except Exception as e:
        return {"ok": False, "keywords": ["modern cinematic", "technology dynamic"], "error": str(e)}


@app.post("/api/clipper/create-project")
async def clipper_create_project(body: dict):
    """🗂️ Convierte un momento viral seleccionado en un proyecto listo para editar."""
    title = (body.get("title") or "Short Viral").strip()[:100]
    hook = (body.get("hook") or "").strip()
    summary = (body.get("summary") or "").strip()
    source_url = (body.get("url") or "").strip()
    video_url = (body.get("video_url") or "").strip()
    start = body.get("start")
    end = body.get("end")

    proj = db.create_project(
        title=title,
        mode="url",
        format="short",
        status="ready" if video_url else "draft",
        source_url=source_url,
        video_url=video_url,
        niche="clips virales",
        meta={
            "hook": hook,
            "summary": summary,
            "clipper_start": start,
            "clipper_end": end,
            "source": "viral_clipper"
        }
    )
    return {"ok": True, "project": proj}


@app.get("/api/renders/{file_name}")
async def get_rendered_file(file_name: str):
    """Reproduce o descarga un video vertical renderizado."""
    safe_name = Path(file_name).name
    path = viral_clipper.RENDERS_DIR / safe_name
    if not path.is_file():
        raise HTTPException(404, "El video renderizado no existe")
    return FileResponse(path, media_type="video/mp4", filename=safe_name)


# ─────────────── Pipeline Orchestrator (INT-023) · NotebookLM → Agent → Flow ──
# Coordina las 3 etapas con mcp_manager sin tocar agent.py ni script_gen
# (regla del mandato: generación de prompts/blueprints INTACTA). Pre-flight
# gatekeeper: si algún MCP no está Connected & Authenticated se aborta antes
# de gastar tokens. Hereda auth_guard/csrf_guard (middlewares de app).
from services import pipeline_orchestrator as _pipe  # noqa: E402


@app.post("/api/pipeline/run")
async def pipeline_run(body: dict):
    """Lanza la corrida completa con el notebookId activo del MCP Manager
    (payload → .env fallback dentro de mcp_manager). Single-flight: Flow
    serializa en el Chrome dedicado, así que una segunda corrida en marcha
    se rechaza con 409."""
    idea = (body.get("idea") or "").strip()
    if not idea:
        raise HTTPException(400, "idea requerida (¿qué video produce el pipeline?)")
    try:
        run = _pipe.orchestrator.create_run(
            idea=idea,
            notebook_id=(body.get("notebook_id") or "").strip() or None,
            fmt=body.get("format") if body.get("format") in ("short", "long") else "short",
            style=(body.get("style") or "auto").strip())
        _pipe.orchestrator.start_run(run["run_id"])
    except _pipe.PipelineError as e:
        status = 409 if e.code == "PIPELINE_BUSY" else 400
        raise HTTPException(status, f"[{e.code}] {e}") from e
    log.info("[pipeline] corrida lanzada %s (idea=%r)", run["run_id"], idea[:60])
    return {"run_id": run["run_id"], "stage": run["stage"],
            "notebook_id": run["notebook_id"]}


@app.get("/api/pipeline/status")
async def pipeline_status(run_id: str = ""):
    """Snapshot de la corrida (la última si no se indica run_id): etapa,
    progreso X/Y de escenas, fallidas y assets generados."""
    try:
        return _pipe.orchestrator.get_status(run_id.strip())
    except _pipe.PipelineError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e


@app.post("/api/pipeline/retry-scenes")
async def pipeline_retry_scenes(body: dict):
    """Re-despacha SOLO las escenas fallidas (o forzadas quirúrgicamente) de Stage 3 usando el blueprint
    persistido — nunca repite Stage 1 (NotebookLM) ni Stage 2 (LLM)."""
    run_id = (body.get("run_id") or "").strip()
    scene_ids = body.get("scene_ids") if isinstance(body.get("scene_ids"), list) else None
    force = bool((body or {}).get("force", False))
    try:
        return await _pipe.orchestrator.retry_scenes(run_id, scene_ids, force=force)
    except _pipe.PipelineError as e:
        status = 409 if e.code == "PIPELINE_BUSY" else 400
        raise HTTPException(status, f"[{e.code}] {e}") from e


# ────── 🎯 Generador A/B de Hooks Virales (3 segundos de impacto) ─────────
@app.post("/api/pipeline/generate-hooks")
async def pipeline_generate_hooks(payload: dict):
    """🎯 Genera 3 variantes psicológicas de hooks para los primeros 3 segundos:
    A: Curiosidad (pregunta provocativa), B: Contradicción (mito común desmentido),
    C: Dato Chocante (impacto inmediato / tensión extrema)."""
    from pipeline import script_gen
    topic = (payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "El campo 'topic' es requerido para generar hooks")
    niche = (payload.get("niche") or "").strip() or None
    count = int(payload.get("count", 3))
    custom_prompt = (payload.get("custom_prompt") or "").strip() or None
    hooks = await script_gen.generate_viral_hooks(topic, niche=niche, count=count, custom_prompt=custom_prompt)
    return {"ok": True, "topic": topic, "niche": niche, "hooks": hooks}





# ────── 🎨 Presets Visuales de Subtítulos de Alta Retención (INT-041) ────
@app.get("/api/subtitles/presets")
async def list_subtitle_presets():
    """Devuelve el catálogo de presets de subtítulos con previsualización CSS."""
    from pipeline import subtitles as subs_mod
    return {
        "ok": True,
        "current_default": getattr(config, "DEFAULT_SUBTITLE_STYLE", "shorts"),
        "presets": subs_mod.SUBTITLE_PRESETS_CATALOG,
    }


@app.post("/api/subtitles/apply")
async def apply_subtitle_style(body: dict):
    """Aplica un estilo de subtítulo a nivel global o a un proyecto específico."""
    from pipeline import subtitles as subs_mod
    style_id = (body.get("style_id") or "").strip().lower()
    if style_id not in subs_mod.SUB_STYLES:
        raise HTTPException(400, f"Estilo de subtítulo inválido: '{style_id}'")

    project_id = (body.get("project_id") or "").strip()
    if project_id:
        pid = _pid(project_id)
        p = db.get_project(pid)
        if not p:
            raise HTTPException(404, "Proyecto no encontrado")
        meta = p.get("meta") or {}
        meta["subtitle_style"] = style_id
        db.update_project(pid, meta=meta)
        return {"ok": True, "scope": "project", "project_id": pid, "style_id": style_id}

    config.DEFAULT_SUBTITLE_STYLE = style_id
    config.save_env({"DEFAULT_SUBTITLE_STYLE": style_id})
    return {"ok": True, "scope": "global", "style_id": style_id}


@app.post("/api/projects/{pid}/select-hook")
async def project_select_hook(pid: str, payload: dict):
    """Aplica la variante de hook seleccionada al guion del proyecto:
    actualiza el hook principal y la narración de la Escena 1 (0-3s)."""
    _pid(pid)
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    hook_text = (payload.get("hook_text") or "").strip()
    hook_id = (payload.get("hook_id") or "A").strip()
    if not hook_text:
        raise HTTPException(400, "El campo 'hook_text' es requerido")

    meta = p.get("meta") or {}
    meta["selected_hook_id"] = hook_id
    meta["hook"] = hook_text
    db.update_project(pid, meta=meta)

    scenes = db.get_scenes(pid)
    if scenes:
        scenes[0]["narration"] = hook_text
        db.replace_scenes(pid, scenes)

    return {"ok": True, "pid": pid, "selected_hook_id": hook_id, "hook": hook_text}


# ────── 🏢 Brand Profiles Persistentes (INT-042) ──────────────────────────
@app.get("/api/brand-profiles")
async def list_brand_profiles():
    """Lista todos los perfiles de marca/canal registrados."""
    from services import brand_profiles as bp_svc
    profiles = bp_svc.list_brand_profiles()
    return {"ok": True, "profiles": profiles, "total": len(profiles)}


@app.post("/api/brand-profiles")
async def create_brand_profile(payload: dict):
    """Crea un nuevo perfil de canal/marca."""
    from services import brand_profiles as bp_svc
    try:
        profile = bp_svc.create_brand_profile(payload)
        return {"ok": True, "profile": profile}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/brand-profiles/default")
async def get_default_brand_profile():
    """Obtiene el perfil por defecto activo."""
    from services import brand_profiles as bp_svc
    profile = bp_svc.get_default_brand_profile()
    if not profile:
        raise HTTPException(404, "No hay ningún perfil de marca configurado")
    return {"ok": True, "profile": profile}


@app.get("/api/brand-profiles/{pid}")
async def get_brand_profile(pid: str):
    """Obtiene el detalle de un perfil de marca por su ID."""
    from services import brand_profiles as bp_svc
    profile = bp_svc.get_brand_profile(pid)
    if not profile:
        raise HTTPException(404, f"Perfil de marca '{pid}' no encontrado")
    return {"ok": True, "profile": profile}


@app.patch("/api/brand-profiles/{pid}")
async def update_brand_profile(pid: str, payload: dict):
    """Actualiza datos de un perfil de marca existente."""
    from services import brand_profiles as bp_svc
    try:
        updated = bp_svc.update_brand_profile(pid, payload)
        if not updated:
            raise HTTPException(404, f"Perfil de marca '{pid}' no encontrado")
        return {"ok": True, "profile": updated}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/brand-profiles/{pid}")
async def delete_brand_profile(pid: str):
    """Elimina un perfil de marca existente."""
    from services import brand_profiles as bp_svc
    ok = bp_svc.delete_brand_profile(pid)
    if not ok:
        raise HTTPException(404, f"Perfil de marca '{pid}' no encontrado")
    return {"ok": True, "deleted": pid}


@app.post("/api/brand-profiles/{pid}/default")
async def set_default_brand_profile(pid: str):
    """Establece un perfil de marca como predeterminado activo."""
    from services import brand_profiles as bp_svc
    profile = bp_svc.set_default_brand_profile(pid)
    if not profile:
        raise HTTPException(404, f"Perfil de marca '{pid}' no encontrado")
    return {"ok": True, "default_profile": profile}


@app.post("/api/brand-profiles/{pid}/apply")
async def apply_brand_profile(pid: str, payload: dict):
    """Aplica la configuración del perfil a un proyecto."""
    from services import brand_profiles as bp_svc
    project_id = (payload.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(400, "El campo 'project_id' es requerido")
    try:
        proj = bp_svc.apply_brand_profile_to_project(pid, project_id)
        return {"ok": True, "project": proj, "applied_profile_id": pid}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/brand-profiles/{pid}/directives")
async def get_brand_profile_directives(pid: str):
    """Devuelve las directivas de guion/prompt formateadas para el LLM."""
    from services import brand_profiles as bp_svc
    profile = bp_svc.get_brand_profile(pid)
    if not profile:
        raise HTTPException(404, f"Perfil de marca '{pid}' no encontrado")
    directives = bp_svc.format_prompt_directives(profile)
    return {"ok": True, "directives": directives, "profile": profile}


# ────── 🎞️ INT-024 · Stage 3.5 (harvest) + Stage 4 (FFmpeg assembler) ──────
# Stage 3.5 consolida los assets de Flow en rutas deterministas
# (scenes/scene_XXX.mp4) y genera el manifest.json estricto. Stage 4 ensambla
# el .mp4 final (duration-sync trim/loop/Ken Burns, música ducked -20dB,
# captions .srt quemadas o soft) SIN bloquear el event loop (asyncio.to_thread).

@app.post("/api/pipeline/harvest")
async def pipeline_harvest(body: dict):
    """Stage 3.5 standalone: re-consolida assets y regenera manifest.json
    sin renderizar. Devuelve el manifest completo (inspección en el panel)."""
    run_id = (body.get("run_id") or "").strip()
    force = bool(body.get("force_placeholder_on_failed"))
    try:
        return _pipe.orchestrator.harvest_only(run_id, placeholders_for_failed=force)
    except _pipe.PipelineError as e:
        status = 409 if e.code == "PIPELINE_BUSY" else 404 if e.code == "RUN_NOT_FOUND" else 400
        raise HTTPException(status, f"[{e.code}] {e}") from e


@app.post("/api/pipeline/render")
async def pipeline_render(body: dict):
    """Dispara Stage 3.5 + Stage 4 en un hilo del backend. Si la corrida tiene
    escenas fallidas, el ensamblaje se BLOQUEA (RENDER_BLOCKED_PARTIAL_FAILURES)
    salvo force_placeholder_on_failed=true — el testeo nunca se deadlocka."""
    run_id = (body.get("run_id") or "").strip()
    force = bool(body.get("force_placeholder_on_failed"))
    dry = bool(body.get("dry_run"))
    try:
        render = _pipe.orchestrator.render_final(
            run_id, force_placeholder_on_failed=force, dry_run=dry)
    except _pipe.PipelineError as e:
        status = 409 if e.code in ("PIPELINE_BUSY", "RENDER_BUSY") else \
                 404 if e.code == "RUN_NOT_FOUND" else 400
        raise HTTPException(status, f"[{e.code}] {e}") from e
    log.info("[pipeline] render lanzado %s (force=%s dry_run=%s)",
             run_id, force, dry)
    return {"run_id": run_id, "render": render}


@app.get("/api/pipeline/render/status")
async def pipeline_render_status(run_id: str = ""):
    """Snapshot del Stage 4: estado, progreso, salida y errores del render."""
    try:
        return _pipe.orchestrator.get_render_status(run_id.strip())
    except _pipe.PipelineError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e


@app.get("/api/pipeline/manifest")
async def pipeline_manifest(run_id: str):
    """manifest.json estricto de la corrida (contrato del ensamblador)."""
    try:
        return _pipe.orchestrator.get_manifest(run_id.strip())
    except _pipe.PipelineError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e
    except _pipe.harv.HarvesterError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e


@app.get("/api/pipeline/render/file")
async def pipeline_render_file(run_id: str):
    """Descarga del MP4 final (video/mp4) — solo si ya existe."""
    try:
        st = _pipe.orchestrator.get_render_status(run_id.strip())
    except _pipe.PipelineError as e:
        raise HTTPException(404, f"[{e.code}] {e}") from e
    out = Path((st.get("render") or {}).get("output") or "")
    if not out.is_file():
        raise HTTPException(404, "[RENDER_NO_OUTPUT] aún no hay final_render.mp4 "
                                 "para esa corrida — lanza Stage 4 primero")
    return FileResponse(out, media_type="video/mp4", filename=out.name)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
