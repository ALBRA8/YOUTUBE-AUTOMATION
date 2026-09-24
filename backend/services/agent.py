"""
YOUTUBE AUTOMATION v2.0 — Agente conversacional (módulo nuevo en v2.1)
Convierte lenguaje natural en acciones reales del motor: crear videos,
consultar proyectos, estado, ayuda. Diseño híbrido como todo el sistema:

- Con GEMINI_API_KEY: Gemini decide la intención (JSON estructurado) y
  redacta la respuesta con personalidad de productor.
- Sin clave: fallback local $0 con detección de intención por regex en
  español. El chat NUNCA se rompe sin claves (misma filosofía del motor).
"""
import json
import logging
import re

from services import gemini_client

log = logging.getLogger("agent")

VALID_ACTIONS = ("create_video", "list_projects", "project_status", "help", "none")
VALID_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook"}

SYSTEM = (
    "Eres VÓRTICE, el agente de producción de YT AUTOMATION v2.0 — una fábrica "
    "real de videos para YouTube/TikTok que funciona con coste $0. "
    "Tu trabajo: entender qué quiere el usuario y DEVOLVER UN JSON VÁLIDO "
    "(sin markdown, sin texto fuera del JSON) con este esquema exacto:\n"
    '{"reply": "texto breve y útil para el usuario (máx 60 palabras, español, '
    'cercano, 1-2 emojis como máximo)", '
    '"action": "create_video|list_projects|project_status|help|none", '
    '"params": {"idea": "...", "style": "id-de-estilo", "format": "short|long", '
    '"avatar": "nombre de avatar si el usuario lo menciona", '
    '"platforms": ["youtube","tiktok"], "project_name": "..."}}\n'
    "Reglas de decisión:\n"
    "- Si el usuario pide un video / narrar / hablar de un tema → action=create_video "
    "con params.idea = el tema condensado en una frase viral.\n"
    "- Si pregunta por sus proyectos / qué ha hecho → action=list_projects.\n"
    "- Si pregunta por el estado/avance de un video concreto → action=project_status "
    "con params.project_name (palabras clave del título).\n"
    "- Si pregunta qué puedes hacer / cómo funciona → action=help.\n"
    "- Si es charla pequeña o algo que no puedes hacer → action=none y explica "
    "en reply lo que SÍ puedes hacer (máx 40 palabras).\n"
    "Estilos válidos para params.style: auto (RECOMENDADO y default cuando el "
    "usuario no menciona estilo — el sistema elige una estética coherente según "
    "el tema), graphic-novel, neo-anime, raw-reality, pixar-3d, cine-blockbuster, "
    "epica-biblica, terror-cartoon, pizarra-educativa, vector-flat, retro-anime-90s, "
    "unreal-engine-5, analog-horror, renaissance-oil, retro-americana, crude-stickman, "
    "cyber-glitch, acuarela-magica, dark-fantasy, grand-theft, custom-studio, "
    "mri-brainrot, claymation, barroqueremax, holo-ghost, papercraft. "
    "Si el usuario no indica estilo, usa params.style = 'auto'. Si pide un estilo "
    "concreto de la lista, úsalo y explica en reply qué look dará (máx 20 palabras). "
    "Nunca inventes estilos fuera de la lista."
)

_HELP_TEXT = (
    "Soy VÓRTICE 🤖 — tu agente de producción. Puedo:\n"
    "🎬 **Crear un video**: «crea un video sobre el imperio romano»\n"
    "🗂️ **Ver tus proyectos**: «muéstrame mis proyectos»\n"
    "📊 **Estado**: «¿cómo va el video del imperio?»\n"
    "🎭 Todo se produce en tu motor real: guion → imágenes → locución → "
    "subtítulos → MP4. Coste $0. Prueba: «crea un video de 45s sobre misterios "
    "del océano con estilo terror cartoon»"
)


# ─────────────────────────── planificación de intención ───────────────────
async def plan(message: str, history: list[dict] | None = None,
               avatars: list[dict] | None = None) -> dict:
    """Devuelve {reply, action, params}. Nunca lanza excepción."""
    message = (message or "").strip()[:2000]
    if not message:
        return {"reply": _HELP_TEXT, "action": "help", "params": {}}

    if gemini_client.available():
        try:
            out = await _plan_gemini(message, history or [])
        except Exception as e:  # noqa: BLE001
            log.warning("Agent Gemini falló (%s) — uso fallback local", str(e)[:120])
            out = _plan_local(message)
    else:
        out = _plan_local(message)
    # Detección de avatar por nombre (funciona con y sin Gemini): si el usuario
    # menciona un personaje existente, se vincula al video que se va a crear.
    if out.get("action") == "create_video" and not out["params"].get("avatar"):
        low = message.lower()
        for a in (avatars or []):
            if a["name"] and a["name"].lower() in low:
                out["params"]["avatar"] = a["name"]
                break
    return out


async def _plan_gemini(message: str, history: list[dict]) -> dict:
    convo = "\n".join(f"{'Usuario' if h.get('role') == 'user' else 'VÓRTICE'}: "
                      f"{h.get('text', '')[:300]}" for h in history[-6:])
    prompt = (f"Conversación previa:\n{convo}\n\n" if convo else "") + \
             f"Mensaje nuevo del usuario: «{message}»\n\nDevuelve SOLO el JSON."
    raw = await gemini_client.generate_text(prompt, system=SYSTEM)
    data = json.loads(_extract_json(raw))
    reply = str(data.get("reply") or "").strip() or "Hecho ✅"
    action = data.get("action") if data.get("action") in VALID_ACTIONS else "none"
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    params = _sanitize_params(params)
    if action == "create_video" and not params.get("idea"):
        params["idea"] = message  # el propio mensaje sirve de semilla
    return {"reply": reply, "action": action, "params": params, "engine": "gemini"}


def _extract_json(text: str) -> str:
    """Toma el primer objeto JSON balanceado del texto del modelo."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    start = text.find("{")
    if start < 0:
        raise ValueError("sin JSON en la respuesta")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("JSON sin cerrar")


_RE_CREATE = re.compile(
    r"^(?:oye\s+)?(?:v[oó]rtice[,:]\s*)?(?:crea|créame|creame|haz|has|genera|genérame|"
    r"quiero|dame|fabrica|produce)\s+(?:un|una|el|un\s+nuevo)?\s*(?:video|vídeo|short|"
    r"reel|clip)\s*(?:de|sobre|acerca\s+de|del|para|que\s+hable\s+de)?\s*(.+)$",
    re.IGNORECASE)
_RE_LIST = re.compile(
    r"\b(lista|listar|mu[eé]strame|muestrame|ens[eé][ñn]ame|ver|mira|dame)\s+"
    r"(los\s+|las\s+|mis\s+|tus\s+|todos\s+los\s+)?(proyectos|videos|v[íi]deos)\b"
    r"|\b(mis\s+)?(proyectos|videos|v[íi]deos)\b[^.]{0,30}\b"
    r"(lista|listar|muestr|tengo|hay|creados|hechos|existe)\b", re.IGNORECASE)
_RE_STATUS = re.compile(r"\b(estado|avance|c[oó]mo\s+va|que\s+paso\s+con|ready|listo\??)\b",
                        re.IGNORECASE)


def _plan_local(message: str) -> dict:
    m = _RE_CREATE.match(message.strip())
    if m:
        idea = m.group(1).strip().rstrip(".!?")[:180]
        fmt = "short"
        if re.search(r"\b(largo|larga|16:9|horizontal|documental)\b", idea, re.I):
            fmt = "long"
        return {"reply": f"¡Marchando! 🎬 Produzco «{idea[:60]}» ahora mismo: guion, "
                         f"imágenes, locución y subtítulos. Te muestro el avance.",
                "action": "create_video", "params": {"idea": idea, "format": fmt},
                "engine": "local"}
    if _RE_LIST.search(message):
        return {"reply": "Aquí tienes tus proyectos 🗂️", "action": "list_projects",
                "params": {}, "engine": "local"}
    if _RE_STATUS.search(message):
        name = re.sub(r"\b(estado|avance|de|del|video|vídeo|el|la|los|c[oó]mo\s+va)\b",
                      "", message, flags=re.I).strip()
        return {"reply": "Consultando el estado… 📊", "action": "project_status",
                "params": {"project_name": name[:80]}, "engine": "local"}
    return {"reply": _HELP_TEXT, "action": "help", "params": {}, "engine": "local"}


def _sanitize_params(params: dict) -> dict:
    p = {}
    if params.get("idea"):
        p["idea"] = str(params["idea"])[:180]
    if params.get("format") in ("short", "long"):
        p["format"] = params["format"]
    if params.get("style"):
        p["style"] = str(params["style"])[:40]
    if params.get("avatar"):
        p["avatar"] = str(params["avatar"])[:60]
    plats = params.get("platforms")
    if isinstance(plats, list):
        p["platforms"] = [x for x in plats if x in VALID_PLATFORMS][:4]
    if params.get("project_name"):
        p["project_name"] = str(params["project_name"])[:80]
    return p


# ─────────────────────────── ejecución de acciones ────────────────────────
def _style_name(style_id: str) -> str:
    try:
        from services.themes import get_style
        return get_style(style_id)["name"]
    except Exception:  # noqa: BLE001
        return ""


async def execute(plan_out: dict, db, orchestrator, avatars: list[dict]) -> dict:
    """Ejecuta la acción del plan contra el motor real. Devuelve payload final
    {reply, action, project?, projects?, job_id?}."""
    action = plan_out.get("action", "none")
    params = plan_out.get("params", {})
    reply = plan_out.get("reply", "")

    if action == "create_video":
        avatar = _match_avatar(params.get("avatar"), avatars)
        style = params.get("style") or (avatar or {}).get("style") or "auto"
        meta = {"idea": params.get("idea") or "un video viral",
                "via": "chat-agente"}
        voice = (avatar or {}).get("voice")
        tts_provider = (avatar or {}).get("tts_provider")
        platforms = params.get("platforms") or ["youtube", "tiktok"]
        project = db.create_project(
            title=(params.get("idea") or "Video del chat")[:60],
            mode="idea", style=style, format=params.get("format", "short"),
            voice=voice, tts_provider=tts_provider, meta=meta,
            avatar_id=(avatar or {}).get("id"),
            platforms=[p for p in platforms if p in VALID_PLATFORMS] or ["youtube"])
        job_id = await orchestrator.start_pipeline(project["id"])
        sname = _style_name(style)
        extra = f" Estilo: {sname}." if sname else ""
        if avatar:
            extra += f" Personaje: {avatar['name']}."
        return {"reply": (reply or f"Producción lanzada 🚀{extra}"),
                "action": "create_video", "project": project, "job_id": job_id}

    if action == "list_projects":
        projects = db.list_projects(limit=6)
        if not projects:
            return {"reply": "Todavía no tienes proyectos. Pídeme: «crea un video "
                             "sobre [tu tema]» y lo produzco en ~30s 🎬",
                    "action": "list_projects", "projects": []}
        return {"reply": reply or "Tus últimos proyectos 🗂️",
                "action": "list_projects", "projects": projects}

    if action == "project_status":
        name = (params.get("project_name") or "").lower().strip()
        projects = db.list_projects(limit=30)
        target = None
        if name:
            for p in projects:
                words = [w for w in re.split(r"\W+", name) if len(w) > 3]
                if words and any(w in p["title"].lower() for w in words[:3]):
                    target = p
                    break
        target = target or (projects[0] if projects else None)
        if not target:
            return {"reply": "No encontré proyectos aún. Crea el primero por chat: "
                             "«crea un video sobre…» 🎬", "action": "project_status"}
        label = target.get("step_label") or target.get("status", "?")
        pct = target.get("progress", 0)
        plats = ", ".join(target.get("platforms") or []) or "youtube"
        return {"reply": f"«{target['title']}» — {label} ({pct}%). "
                         f"Plataformas: {plats}.",
                "action": "project_status", "project": target}

    # help / none
    return {"reply": reply or _HELP_TEXT, "action": "help"}


def _match_avatar(name: str | None, avatars: list[dict]) -> dict | None:
    if not name or not avatars:
        return None
    low = name.lower().strip()
    for a in avatars:
        if a["name"].lower() == low:
            return a
    for a in avatars:
        if low in a["name"].lower() or a["name"].lower() in low:
            return a
    return None
