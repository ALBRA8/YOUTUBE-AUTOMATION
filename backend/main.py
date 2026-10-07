"""
YOUTUBE AUTOMATION v2.0 — Servidor principal (FastAPI)
Dashboard en http://127.0.0.1:8000  ·  progreso por SSE  ·  coste $0/video
"""
import asyncio
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
from services import (agent as agent_svc, backup as backup_svc, camera_recipes,
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

app = FastAPI(title="YT Automation v2.0", version="2.19.0")

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
    if security.enabled() and (_p.startswith("/api/") or _p.startswith("/mcp")) \
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


# ──────────────────────────────────────────────────────── básicos ──
@app.get("/api/health")
async def health():
    return {"ok": True, "version": "2.19.0", "gemini": gemini_client.available(),
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


# ────────────────────────────── chat-agente (v2.12 · VÓRTICE v3) ──
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
    """Elige el cerebro de VÓRTICE (persistente en .env, aplica al instante)."""
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
    """Agente VÓRTICE: entiende la fábrica (contexto vivo) y ejecuta acciones
    reales. Acciones destructivas exigen confirmación del usuario: la primera
    llamada devuelve needs_confirm+pending; la ejecución real llega en la
    segunda llamada con {confirm: {action, params}}."""
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
        cover = next((f"/api/scenes/{s['id']}/image" for s in scenes
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
                    "production_json"):
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
            sub = (body.get("subtitle_style") or "hormozi").lower()
            if sub in ("hormozi", "tiktok", "karaoke"):
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
            body["subtitle_style"] = tpl.get("subtitles") or "hormozi"
    if body.get("custom_style_prompt"):
        meta["custom_style_prompt"] = body["custom_style_prompt"].strip()
    # v2.4 — toggles de producción expuestos en el dashboard
    meta["transitions"] = bool(body.get("transitions", True))
    meta["style_reference"] = bool(body.get("style_reference", True))
    sub_style = (body.get("subtitle_style") or "hormozi").lower()
    if sub_style in ("hormozi", "tiktok", "karaoke"):
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
    if mode == "nicho" and body.get("auto_start"):
        # flujo de un clic: crea el proyecto Y lanza el pipeline completo
        job_id = await orchestrator.start_pipeline(project["id"], autopublish=False)
        project["job_id"] = job_id
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


@app.post("/api/projects/{pid}/cleanup")
async def cleanup_project(pid: str):
    """Libera el disco: borra clips intermedios del proyecto (el MP4 final,
    imágenes, Flow y audio TTS se conservan). Útil si KEEP_INTERMEDIATES=1."""
    if not db.get_project(pid):
        raise HTTPException(404, "no existe")
    freed = video_pipeline.cleanup_intermediates(pid)
    return {"ok": True, "freed_bytes": freed,
            "freed_mb": round(freed / 1e6, 1)}


@app.post("/api/projects/{pid}/generate")
async def generate(pid: str, body: dict | None = None):
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


# ── exportación a Google Flow (extensión Flow Script Processor) ────────────
_FMTS_FLOW = ("transformacion", "generic", "artesano")


@app.get("/api/projects/{pid}/export/flow.json")
async def export_flow_json(pid: str, format: str = "transformacion",
                           brand: str | None = None, character: str | None = None):
    """ScriptData con el contrato exacto de la extensión.
    format=transformacion|generic|artesano (fabricación de personaje)."""
    from pipeline.flow_export import DEFAULT_BRAND, build_script_json
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
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "no existe")
    scenes = db.get_scenes(pid)
    if not scenes:
        raise HTTPException(400, "el proyecto no tiene escenas aún")
    data = await file.read()
    try:
        result = flow_import.import_flow_zip(pid, data, OUTPUT_DIR / pid,
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
    ok = youtube_publish.exchange_code(code)
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
    eid = db.add_ext_image(url, body.get("project_id"), body.get("source", "imagefx"))
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
    job = flow_jobs.claim_next(worker.strip(),
                               pid=project_id.strip() or None)
    if not job:
        from fastapi import Response
        return Response(status_code=204)
    return {"ok": True, "job": job}


@app.post("/api/extension/flow/jobs/{job_id}/heartbeat")
async def flow_jobs_heartbeat(job_id: str, token: str = ""):
    """Renueva el lease del job reclamado (worker vivo)."""
    from services import flow_jobs
    res = flow_jobs.heartbeat(job_id, token)
    if not res:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    return res


@app.post("/api/extension/flow/jobs/{job_id}/complete")
async def flow_jobs_complete(job_id: str, request: Request, token: str = ""):
    """Sube el asset generado en Flow (binario crudo en el body). Valida
    PNG/JPEG/WEBP con PIL · MP4 con ffprobe. Si es el último job del proyecto
    mapea los assets a las escenas y, si están completas, lanza el render
    automáticamente (orchestrator.start_flow_render)."""
    from services import flow_jobs
    data = await request.body()
    try:
        res = flow_jobs.complete(job_id, token, data)
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
async def flow_jobs_fail(job_id: str, token: str = "", body: dict | None = None):
    """Marca error y reintenta (queued) o deja dead al agotar max_attempts
    (imagen 3 · video 2)."""
    from services import flow_jobs
    res = flow_jobs.fail(job_id, token,
                         ((body or {}).get("error") or "")[:500])
    if not res:
        raise HTTPException(409, "job no reclamado por este worker "
                                 "(token/lease inválido)")
    return res


@app.get("/api/extension/flow/jobs/status/{pid}")
async def flow_jobs_status(pid: str):
    """Estado de la cola del proyecto: counts por status + detalle de jobs."""
    from services import flow_jobs
    return flow_jobs.status_for_project(pid)


# ─────────────────────────────── [qa v1] control de calidad de assets ──
@app.get("/api/video_qa/{pid}")
async def video_qa_endpoint(pid: str):
    """QA REAL del proyecto con ffprobe/PIL: imágenes y clips de Flow por
    escena + render final (si existe). Reporta flags error/warn/ok; nunca
    lanza por assets malos (404 solo si el proyecto no existe)."""
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


@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp_sin_barra(req: _Req):
    """Proxy de /mcp exacto → evita el 307 a /mcp/ para clientes MCP."""
    if req.method == "GET":
        return await mcp_server.info()
    return await mcp_server.entry(req)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
