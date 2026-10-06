"""v2.16.0 · Servidor MCP (Model Context Protocol) de la fábrica — reconstruido.

Montado en /mcp desde main.py. Implementación JSON-RPC 2.0 a mano (el venv no
tiene el paquete `mcp`): soporta initialize, tools/list y tools/call, suficiente
para clientes MCP (Claude Desktop vía proxy, Antigravity, agentes locales).

16 tools — las puertas de producción son `crear_video_guion_json` y `submit_production_json`.
v2.16 · nueva puerta Creative Production JSON; v2.11 · nuevas: crear_avatar (personajes con ADN consistente) y
listar_recetas_camara (catálogo para el campo «camara» del contrato).

NOTA: solo para uso LOCAL (sin auth). Para exponerlo a ChatGPT cloud hacen
falta túnel + API key; ChatGPT habla mejor con Actions/OpenAPI usando el spec
de GET /api/guion_json/contrato.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import database as db
from pipeline import orchestrator
from services import (avatar_schema, camera_recipes,
                      gemini_client, guion_json as guion_svc, production_json as production_svc,
                      library as library_svc, niches as niches_svc,
                      whisper_service, youtube_publish)
from services.themes import STYLES

log = logging.getLogger("mcp")

app = FastAPI(title="YT Automation MCP", version="2.18.0")

SERVER_INFO = {"name": "yt-automation-v2", "version": "2.18.0"}
PROTOCOL_VERSION = "2024-11-05"

# ───────────────────────────────────────────────────────────── tools ──
def _t_ayuda() -> dict:
    return {
        "servidor": "Fábrica de videos IA (yt_automation_v2)",
        "puertas": [
            "MCP (esta): tools crear_video / crear_video_guion_json / submit_production_json / lanzar_proyecto",
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



async def _t_submit_production_json(production_json, lanzar: bool = False) -> dict:
    """Ingesta el Creative Production JSON sin regenerar creatividad.

    Esta es la puerta MCP entre ChatGPT/Creative Engine y YOUTUBE-AUTOMATION.
    El Adapter valida, normaliza, conserva el JSON original y crea las escenas.
    """
    if production_json is None:
        raise ValueError("falta production_json")
    try:
        data = production_svc.parse_payload(production_json)
    except ValueError:
        raise

    def _crear_pj(g: dict):
        av = g.get("avatar_id")
        if av and not db.get_avatar(av):
            av = None
        pmeta = {}
        if g.get("camara"):
            pmeta["camara"] = g["camara"]
        if g.get("project_extra"):
            pmeta["production_project_extra"] = g["project_extra"]
        if g.get("root_extra"):
            pmeta["production_root_extra"] = g["root_extra"]
        return db.create_project(
            title=(g.get("titulo") or "Video desde Production JSON"),
            mode="production_json",
            style=g.get("estilo") or "auto",
            format=g.get("formato") or "short",
            voice=g.get("voz"),
            meta=pmeta,
            avatar_id=av,
            platforms=g.get("plataformas") or ["youtube"],
            niche=g.get("nicho"),
        )

    return await production_svc.ingest(
        data,
        {s["id"] for s in STYLES},
        _crear_pj,
        auto_start_override=bool(lanzar),
    )


async def _t_lanzar_proyecto(project_id: str) -> dict:
    """Lanza un proyecto ya creado sin volver a ingerir su Production JSON.

    Esta puerta permite separar creación/ingesta de ejecución y evita duplicar
    proyectos cuando ChatGPT ya creó un draft mediante submit_production_json.
    """
    project_id = (project_id or "").strip()
    if not project_id:
        raise ValueError("falta project_id")
    p = db.get_project(project_id)
    if not p:
        raise ValueError(f"no existe el proyecto {project_id}")
    if p.get("status") in ("processing", "queued", "running"):
        active = db.active_job_for_project(project_id)
        return {"ok": True, "project_id": project_id, "lanzado": False,
                "motivo": "ya hay un pipeline activo", "job_id": active.get("id") if active else None}
    job_id = await orchestrator.start_pipeline(project_id)
    return {"ok": True, "project_id": project_id, "lanzado": True,
            "job_id": job_id, "estado": db.get_project(project_id).get("status")}


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
    {"name": "submit_production_json",
     "description": "PUERTA PRINCIPAL DEL CREATIVE ENGINE: recibe un Creative Production JSON TERMINADO, lo valida mediante production_json.py, crea el proyecto y opcionalmente lanza el pipeline. NO genera ni modifica la creatividad. Acepta el JSON como objeto o texto JSON. Esta acción crea/ejecuta un proyecto en la fábrica.",
     "inputSchema": {"type": "object", "required": ["production_json"], "properties": {
         "production_json": {
             "description": "Creative Production JSON completo, como objeto JSON o como texto JSON.",
             "oneOf": [
                 {"type": "object"},
                 {"type": "string"}
             ]
         },
         "lanzar": {"type": "boolean", "default": False,
                    "description": "true = arranca el pipeline inmediatamente; false = crea el proyecto sin lanzarlo."}}}},
    {"name": "estado_proyecto", "description": "Estado detallado de un proyecto "
     "(paso actual, progreso, escenas, job activo, error si lo hay).",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"}}}},
    {"name": "lanzar_proyecto", "description": "Lanza un proyecto ya creado por su ID, sin volver a ingerir ni duplicar su Production JSON. Ideal para pasar un draft validado a producción.",
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
    {"name": "flow_encolar", "description": "FLOW BRIDGE: (re)genera la cola de "
     "jobs de Google Flow del proyecto desde su script.json (fuente única de "
     "prompts, contrato P1). Idempotente: conserva los assets ya subidos.",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"},
         "format": {"type": "string", "enum": ["transformacion", "generic", "artesano"],
                    "default": "transformacion"}}}},
    {"name": "flow_estado", "description": "FLOW BRIDGE: estado de la cola de "
     "jobs de Flow del proyecto (queued/claimed/done/dead por job, worker, "
     "asset_path, errores).",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"}}}},
    {"name": "video_qa", "description": "QA REAL con ffprobe/PIL del proyecto: "
     "imágenes y clips de Flow por escena + render final. Devuelve flags "
     "error/warn/ok y resumen (no revienta por assets malos).",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
         "project_id": {"type": "string"}}}},
    {"name": "metricas", "description": "Snapshot de observabilidad de la fábrica: "
     "proyectos por estado, cola Flow (incl. dead por tipo), jobs de pipeline, "
     "escenas sin imagen y disco ocupado por data/output.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "production_doctor", "description": "PRODUCTION DOCTOR V1.0: "
     "diagnóstico por capas del pipeline completo (Production JSON → Adapter "
     "→ Flow Export → Jobs → Extensión → Google Flow → Assets → QA → Render). "
     "Modos: audit (solo lee), fix (solo reparaciones seguras deterministas + "
     "verify), verify (re-ejecuta checks y baterías afectadas), report "
     "(último informe). Nunca modifica contenido creativo.",
     "inputSchema": {"type": "object", "properties": {
         "modo": {"type": "string", "enum": ["audit", "fix", "verify", "report"],
                  "default": "audit"},
         "deep": {"type": "boolean", "default": False,
                  "description": "incluir QA forense pesado (ffprobe por asset)"},
         "ejecutar_tests": {"type": "boolean", "default": True,
                            "description": "re-ejecutar baterías afectadas en fix/verify"}}}},
    {"name": "real_flow_preflight", "description": "REAL FLOW PREFLIGHT: barrera "
     "antes de una prueba real con Google Flow. Comprueba backend, extensión, "
     "bridge, Production JSON (image_prompt/video_prompt/duration_target), "
     "cola limpia y herramientas. Devuelve REAL FLOW PREFLIGHT PASS o REAL "
     "FLOW BLOCKED con los motivos exactos. NUNCA ejecuta Flow.",
     "inputSchema": {"type": "object", "properties": {
         "project_id": {"type": "string",
                        "description": "proyecto a comprobar (opcional)"},
         "backend_url": {"type": "string",
                         "description": "URL del backend (default 127.0.0.1:PORT)"}}}},
]


async def _dispatch(name: str, args: dict):
    if name == "ayuda":
        return _t_ayuda()
    if name == "crear_video":
        return _t_crear_video(**args)
    if name == "crear_video_guion_json":
        return await _t_crear_video_guion_json(**args)
    if name == "submit_production_json":
        return await _t_submit_production_json(**args)
    if name == "lanzar_proyecto":
        return await _t_lanzar_proyecto(**args)
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
    if name == "flow_encolar":
        from services import flow_jobs as _fj
        try:
            return _fj.enqueue_project(
                args["project_id"],
                fmt=args.get("format") or "transformacion")
        except LookupError as e:
            raise ValueError(str(e)) from e
        except ValueError as e:
            raise ValueError(str(e)) from e
    if name == "flow_estado":
        from services import flow_jobs as _fj
        try:
            return _fj.status_for_project(args["project_id"])
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"estado no disponible: {e}") from e
    if name == "video_qa":
        from services import video_qa as _vqa
        try:
            return _vqa.qa_project(args["project_id"])
        except LookupError as e:
            raise ValueError(str(e)) from e
    if name == "metricas":
        from services import metrics as _mx
        return _mx.snapshot()
    if name == "production_doctor":
        from services.production_doctor import run_mode as _pdoc
        try:
            return await asyncio.to_thread(
                _pdoc, args.get("modo") or "audit",
                deep=bool(args.get("deep")), in_process=True,
                ejecutar_tests=bool(args.get("ejecutar_tests", True)))
        except ValueError as e:
            raise ValueError(str(e)) from e
    if name == "real_flow_preflight":
        from services.production_doctor import preflight as _pf
        return await asyncio.to_thread(
            _pf, project_id=args.get("project_id"),
            backend_url=args.get("backend_url"))
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
