"""v2.11.0 · Servidor MCP (Model Context Protocol) de la fábrica — reconstruido.

Montado en /mcp desde main.py. Implementación JSON-RPC 2.0 a mano (el venv no
tiene el paquete `mcp`): soporta initialize, tools/list y tools/call, suficiente
para clientes MCP (Claude Desktop vía proxy, Antigravity, agentes locales).

14 tools — la puerta del contrato guion_json es `crear_video_guion_json`.
v2.11 · nuevas: crear_avatar (personajes con ADN consistente) y
listar_recetas_camara (catálogo para el campo «camara» del contrato).

NOTA: solo para uso LOCAL (sin auth). Para exponerlo a ChatGPT cloud hacen
falta túnel + API key; ChatGPT habla mejor con Actions/OpenAPI usando el spec
de GET /api/guion_json/contrato.
"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import database as db
from pipeline import orchestrator
from services import (avatar_schema, camera_recipes,
                      gemini_client, guion_json as guion_svc,
                      library as library_svc, niches as niches_svc,
                      whisper_service, youtube_publish)
from services.themes import STYLES

log = logging.getLogger("mcp")

app = FastAPI(title="YT Automation MCP", version="2.11.0")

SERVER_INFO = {"name": "yt-automation-v2", "version": "2.11.0"}
PROTOCOL_VERSION = "2024-11-05"

# ───────────────────────────────────────────────────────────── tools ──
def _t_ayuda() -> dict:
    return {
        "servidor": "Fábrica de videos IA (yt_automation_v2)",
        "puertas": [
            "MCP (esta): tools crear_video / crear_video_guion_json",
            "API: POST /api/projects con {\"mode\": \"guion_json\", ...}",
            "Spec para ChatGPT Actions: GET /api/guion_json/contrato",
        ],
        "contrato_guion_json": guion_svc.spec([s["id"] for s in STYLES]),
    }


def _t_crear_video(idea: str, titulo: str = "", formato: str = "short",
                   estilo: str = "auto", lanzar: bool = True) -> dict:
    idea = (idea or "").strip()
    if not idea:
        raise ValueError("falta la idea del video")
    p = db.create_project(title=(titulo or idea)[:60] or "Video desde MCP",
                          mode="idea", style=estilo, format=formato,
                          meta={"idea": idea})
    out = {"ok": True, "project_id": p["id"], "titulo": p["title"]}
    if lanzar:
        # start_pipeline es async: se registra la coroutine en el loop del server
        import asyncio
        loop = asyncio.get_event_loop()
        job = loop.create_task(orchestrator.start_pipeline(p["id"]))
        out["job"] = "lanzado"
        out["job_id"] = getattr(job, "id", None) or "en curso"
    return out


async def _t_crear_video_guion_json(guion: str, lanzar: bool = False) -> dict:
    """La puerta del contrato: `guion` llega como TEXTO JSON (dict también vale)."""
    data = guion_svc.parse_payload(guion)
    data.setdefault("auto_start", bool(lanzar))
    estilos = {s["id"] for s in STYLES}

    def _crear(g: dict):
        av = g.get("avatar_id")
        if av and not db.get_avatar(av):
            av = None
        pmeta = {"camara": g["camara"]} if g.get("camara") else {}
        return db.create_project(
            title=(g.get("titulo") or "Video desde guion JSON"),
            mode="guion_json", style=g.get("estilo") or "auto",
            format=g.get("formato") or "short", voice=g.get("voz"),
            meta=pmeta, avatar_id=av,
            platforms=g.get("plataformas") or ["youtube"],
            niche=g.get("nicho"))

    return await guion_svc.ingest(data, estilos, _crear)


def _t_estado_proyecto(project_id: str) -> dict:
    p = db.get_project(project_id)
    if not p:
        raise ValueError(f"no existe el proyecto {project_id}")
    scenes = db.get_scenes(project_id)
    job = db.active_job_for_project(project_id)
    return {"id": p["id"], "titulo": p["title"], "estado": p["status"],
            "modo": p.get("mode"), "progreso": p.get("progress"),
            "paso": p.get("step_label"), "error": p.get("error"),
            "escenas": len(scenes), "job_activo": job}


def _t_guion_de_proyecto(project_id: str) -> dict:
    p = db.get_project(project_id)
    if not p:
        raise ValueError(f"no existe el proyecto {project_id}")
    scenes = db.get_scenes(project_id)
    return {"titulo": p["title"], "formato": p.get("format"),
            "estilo": p.get("style"),
            "escenas": [{"titulo": s.get("title"), "narracion": s.get("narration"),
                         "prompt_imagen": s.get("image_prompt")} for s in scenes]}


def _t_listar_proyectos(limite: int = 20) -> list[dict]:
    out = []
    for p in db.list_projects(limit=max(1, min(int(limite), 100))):
        out.append({"id": p["id"], "titulo": p["title"], "estado": p["status"],
                    "modo": p.get("mode"), "nicho": p.get("niche"),
                    "formato": p.get("format"), "actualizado": p.get("updated_at")})
    return out


def _t_listar_avatares() -> list[dict]:
    return db.list_avatars()


def _t_crear_avatar(nombre: str, descripcion: str = "",
                    apariencia=None, voz: str = "",
                    tts_provider: str = "edge", estilo: str = "") -> dict:
    """v2.11 · Crea un personaje con ADN biométrico consistente.
    `apariencia` llega como dict o TEXTO JSON con campos del schema
    (genero, edad, piel, rostro, ojos_color, ojos_forma, cabello_color,
    cabello_largo, cabello_textura, mechas, cuerpo, ropa, maquillaje,
    arquetipo, personalidad, acento, jerga) — claves desconocidas se
    descartan con aviso; opcionalmente accesorios/referencia/extras."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("falta el nombre del avatar")
    if isinstance(apariencia, str):
        try:
            apariencia = json.loads(apariencia or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"apariencia no es JSON válido: {e}")
    if not isinstance(apariencia, dict):
        apariencia = {}
    validos = set(avatar_schema.AVATAR_OPTIONS) | {"accesorios", "referencia", "extras"}
    notas = []
    limpio = {}
    for k, v in apariencia.items():
        if k in validos and str(v or "").strip():
            limpio[k] = str(v).strip()
        elif k not in validos:
            notas.append(f"campo «{k}» descartado (no está en el schema)")
    voz = (voz or "").strip()
    if not voz and limpio.get("acento") and limpio.get("genero"):
        voz = avatar_schema.suggest_voice(limpio["acento"], limpio["genero"])
        if voz:
            notas.append(f"voz sugerida por acento: {voz}")
    av = db.create_avatar(name=nombre, description=(descripcion or "").strip(),
                          appearance=limpio, voice=voz or None,
                          tts_provider=(tts_provider or "edge").strip() or "edge",
                          style=(estilo or "").strip() or None)
    av["notas"] = notas
    av["uso"] = "usa este id como avatar_id en crear_video_guion_json"
    return av


def _t_listar_recetas_camara() -> list[dict]:
    """v2.11 · Catálogo de recetas para el campo «camara» del contrato."""
    return camera_recipes.list()


def _t_estado_sistema() -> dict:
    activos = [j for j in db.list_projects(limit=100) if j.get("status") not in
               ("ready", "published", "failed", "draft")]
    return {"version": "2.11.0", "gemini": gemini_client.available(),
            "whisper": whisper_service.available(),
            "youtube": youtube_publish.configured(),
            "canales": False,  # puente WhatsApp/Telegram pendiente de re-cosecha
            "proyectos_en_curso": len(activos)}


TOOLS = [
    {"name": "ayuda", "description": "Cómo usar la fábrica: puertas de entrada y "
     "contrato guion_json completo (spec + reglas + ejemplo).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "crear_video", "description": "Crea un video desde una IDEA (la "
     "fábrica escribe el guion con Gemini interno). Para traer el guion YA "
     "escrito usa crear_video_guion_json.",
     "inputSchema": {"type": "object", "required": ["idea"], "properties": {
         "idea": {"type": "string", "description": "idea/consigna del video"},
         "titulo": {"type": "string"}, "formato": {"type": "string",
         "enum": ["short", "long"]}, "estilo": {"type": "string"},
         "lanzar": {"type": "boolean", "default": True}}}},
    {"name": "crear_video_guion_json", "description": "PUERTA PRINCIPAL: ingiere "
     "un guion TERMINADO en el contrato guion_json {titulo, formato, escenas:"
     "[{narracion, prompt_imagen, camara?, outfit?, ambiente?}], cta} y lo manda "
     "a producción SIN regenerar nada. 'guion' va como TEXTO JSON. "
     "Ver también listar_recetas_camara y crear_avatar.",
     "inputSchema": {"type": "object", "required": ["guion"], "properties": {
         "guion": {"type": "string", "description": "JSON del contrato como texto"},
         "lanzar": {"type": "boolean", "default": False,
                    "description": "true = arranca el pipeline completo"}}}},
    {"name": "estado_proyecto", "description": "Estado detallado de un proyecto "
     "(paso actual, progreso, escenas, job activo, error si lo hay).",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"}}}},
    {"name": "guion_de_proyecto", "description": "Devuelve el guion completo de "
     "un proyecto (escenas con narración y prompt visual).",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"}}}},
    {"name": "listar_proyectos", "description": "Lista los proyectos recientes.",
     "inputSchema": {"type": "object", "properties": {
         "limite": {"type": "integer", "default": 20}}}},
    {"name": "listar_biblioteca", "description": "Videos TERMINADOS en disco, "
     "agrupados por nicho (carpeta data/biblioteca/<nicho>/).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "listar_estilos", "description": "Catálogo de estilos visuales "
     "disponibles para los videos.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "listar_nichos", "description": "Plantillas de nicho disponibles "
     "(con su prompt base para crear videos).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "listar_avatares", "description": "Personajes (avatares) con "
     "apariencia consistente disponibles.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "crear_avatar", "description": "Crea un personaje (avatar) con "
     "ADN biométrico consistente: piel, rostro, ojos, cabello, cuerpo, "
     "arquetipo, acento… Devuelve su id para usarlo como avatar_id en "
     "crear_video_guion_json. La ropa puede variar por escena (outfit); la "
     "cara nunca.",
     "inputSchema": {"type": "object", "required": ["nombre"], "properties": {
         "nombre": {"type": "string"},
         "descripcion": {"type": "string", "description": "rol/personalidad"},
         "apariencia": {"type": "string", "description": "JSON con campos del "
             "schema: genero, edad, piel, rostro, ojos_color, ojos_forma, "
             "cabello_color, cabello_largo, cabello_textura, mechas, cuerpo, "
             "ropa, maquillaje, arquetipo, personalidad, acento, jerga"},
         "voz": {"type": "string", "description": "voz edge-tts (si se omite, "
                 "se sugiere por acento+género)"},
         "estilo": {"type": "string"}}}},
    {"name": "listar_recetas_camara", "description": "Catálogo de 20 recetas "
     "de cámara (11 cine + 9 UGC/selfie) para el campo «camara» de cada "
     "escena del contrato guion_json. Cada una define shot, lens, lighting, "
     "mood, angle y render.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "estado_sistema", "description": "Salud de la fábrica: version, "
     "proveedores disponibles (gemini/whisper/youtube), trabajos en curso.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "cancelar_trabajo", "description": "Cancela el pipeline de un "
     "proyecto en curso.",
     "inputSchema": {"type": "object", "required": ["job_id"], "properties": {
         "job_id": {"type": "string"}}}},
]


async def _dispatch(name: str, args: dict):
    if name == "ayuda":
        return _t_ayuda()
    if name == "crear_video":
        return _t_crear_video(**args)
    if name == "crear_video_guion_json":
        return await _t_crear_video_guion_json(**args)
    if name == "estado_proyecto":
        return _t_estado_proyecto(**args)
    if name == "guion_de_proyecto":
        return _t_guion_de_proyecto(**args)
    if name == "listar_proyectos":
        return _t_listar_proyectos(**args)
    if name == "listar_biblioteca":
        return library_svc.tree()
    if name == "listar_estilos":
        return [{"id": s["id"], "nombre": s["name"], "emoji": s.get("emoji", ""),
                 "descripcion": s.get("desc", "")} for s in STYLES]
    if name == "listar_nichos":
        return [{"id": t["id"], "nombre": t.get("name"), "emoji": t.get("emoji", ""),
                 "descripcion": t.get("description", "")}
                for t in niches_svc.list_templates()]
    if name == "listar_avatares":
        return _t_listar_avatares()
    if name == "crear_avatar":
        return _t_crear_avatar(**args)
    if name == "listar_recetas_camara":
        return _t_listar_recetas_camara()
    if name == "estado_sistema":
        return _t_estado_sistema()
    if name == "cancelar_trabajo":
        orchestrator.cancel_job(args["job_id"])
        return {"ok": True}
    raise ValueError(f"tool desconocida: {name}")


# ─────────────────────────────────────────────────── JSON-RPC / MCP ──
@app.get("/")
async def info():
    return {"server": SERVER_INFO, "protocol": "mcp/jsonrpc-2.0",
            "tools": len(TOOLS),
            "nota": "POST JSON-RPC: initialize · tools/list · tools/call"}


async def entry(req: Request):
    """Manejador JSON-RPC — reutilizado por la sub-app Y por el proxy /mcp
    de main.py (evita el redirect 307 que estorba a algunos clientes MCP)."""
    try:
        msg = await req.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "parse error"}},
                            status_code=400)
    mid, method = msg.get("id"), msg.get("method", "")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO}}
    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0"}, status_code=202)
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (msg.get("params") or {}).get("name", "")
        args = (msg.get("params") or {}).get("arguments") or {}
        try:
            out = await _dispatch(name, args)
            text = json.dumps(out, ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:  # noqa: BLE001
            log.warning("tool %s falló: %s", name, e)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"ERROR: {e}"}],
                "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {
        "code": -32601, "message": f"método no soportado: {method}"}}


@app.post("/")
async def rpc(req: Request):
    return await entry(req)
