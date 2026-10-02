"""
YOUTUBE AUTOMATION v2.0 — Agente VÓRTICE v3 (v2.12.0)
Un agente que ENTIENDE el proyecto: recibe una descripción profunda de la
fábrica + un contexto vivo (proyectos, nichos, avatares, estados) y puede
responder preguntas técnicas Y ejecutar tareas repetitivas contra el motor.

Cadena de inteligencia (siempre degrada con gracia, nunca rompe el chat):
1. NVIDIA NIM (kimi-k3 → deepseek-v4.1-flash → kimi-k2.6) con failover
2. Gemini 2.5-flash (si hay GEMINI_API_KEY)
3. Regex local $0 (última línea de defensa)

Acciones destructivas (delete_niche, delete_project, cleanup_failed) NO se
ejecutan directo: plan() las devuelve y el dashboard pide confirmación al
usuario antes de reenviar {confirm: {...}}.
"""
import json
import logging
import re

from services import gemini_client, niches as niches_svc, nvidia_client

log = logging.getLogger("agent")

VALID_ACTIONS = ("create_video", "create_niche", "delete_niche", "delete_project",
                 "cleanup_failed", "list_projects", "list_niches",
                 "project_status", "help", "none")
DESTRUCTIVE_ACTIONS = ("delete_niche", "delete_project", "cleanup_failed")
VALID_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook"}

# ─────────────────────────── el cerebro: qué ES esta fábrica ──────────────
SYSTEM_BRAIN = (
    "Eres VÓRTICE, el agente de YT AUTOMATION v2 — una fábrica REAL de videos "
    "para YouTube/TikTok que corre en la máquina del usuario con coste $0.\n"
    "Cómo funciona la fábrica (estäla siempre presente al responder):\n"
    "• Proyectos: cada video es un proyecto con estados draft → processing "
    "(guion → imágenes → locución TTS → subtítulos → montaje MP4) → ready → "
    "published. `failed` = paso roto; `step_label` dice el paso exacto.\n"
    "• Nichos: carpetas temáticas. Un nicho-plantilla trae emoji, descripción "
    "y prompt predeterminado (el motor compone idea = plantilla + ángulo "
    "anti-repetición). También existen nichos libres (solo el texto del campo "
    "niche de proyectos creados sin plantilla). «Sin nicho» = sin carpeta.\n"
    "• Formatos: short (9:16) y long (16:9). Estilos visuales: auto + catálogo "
    "(graphic-novel, neo-anime, pixar-3d, terror-cartoon, etc.). Avatares: "
    "personajes DNA con look + voz propios.\n"
    "• TTS: edge (gratuito ilimitado) o gemini (premium). Subtítulos estilo "
    "hormozi. Publicación a YouTube opcional (token aparte).\n"
    "• La UI tiene: Proyectos (carpetas por nicho → tarjetas de video), Crear "
    "(asistente), Biblioteca, Avatares, Ajustes (claves en .env) y este chat.\n"
    "Tu trabajo: entender al usuario y DEVOLVER SOLO UN JSON VÁLIDO (sin "
    "markdown, sin texto fuera del JSON) con este esquema exacto:\n"
    '{"reply": "respuesta breve y útil (español, cercano, máx 80 palabras, '
    "1-2 emojis), SIEMPRE responde algo concreto usando el contexto si lo hay\", "
    '"action": "create_video|create_niche|delete_niche|delete_project|'
    'cleanup_failed|list_projects|list_niches|project_status|help|none", '
    '"params": {…}}\n'
    "Acciones (params):\n"
    '- create_video: {"idea": "tema condensado", "format": "short|long", '
    '"style": "auto|id-de-estilo", "nicho": "nombre exacto de nicho si aplica", '
    '"platforms": ["youtube","tiktok"]}\n'
    '- create_niche: {"name": "nombre", "emoji": "📁", "description": "corta", '
    '"prompt": "plantilla de prompt para el motor"}\n'
    "- delete_niche: {\"name\": \"nombre EXACTO del nicho a borrar\"}  [destructiva]\n"
    '- delete_project: {"project_name": "palabras del título"}  [destructiva]\n'
    "- cleanup_failed: {} — borra TODOS los proyectos failed  [destructiva]\n"
    "- list_projects / list_niches / project_status: {}\n"
    "- help / none: {} — none para charla o peticiones fuera de tu alcance "
    "(explica en reply qué SÍ puedes hacer)\n"
    "Reglas:\n"
    "- Si piden borrar/limpiar usa la acción destructiva exacta; NUNCA digas "
    "que ya lo hiciste — el sistema pedirá confirmación al usuario.\n"
    "- Nombres de nicho: cópialos TAL CUAL del contexto (respetando tildes).\n"
    "- Si no hay datos en el contexto, dilo con honestidad; no inventes "
    "proyectos ni nichos.\n"
    "- Nunca inventes estilos fuera del catálogo; si el usuario no pide "
    "estilo usa 'auto'.\n"
)

_HELP_TEXT = (
    "Soy VÓRTICE 🤖 — entiendo toda la fábrica y ejecuto por ti:\n"
    "🎬 **Crear video**: «crea un video sobre el imperio romano»\n"
    "🗂️ **Nichos**: «crea un nicho de finanzas», «¿qué nichos tengo?», "
    "«borra el nicho Tecnología»\n"
    "📊 **Estado**: «¿cómo van mis proyectos?», «resume el estado»\n"
    "🧹 **Limpieza**: «borra los proyectos fallidos» (siempre pido confirmación "
    "antes de destruir algo)\n"
    "❓ **Técnico**: «¿por qué falló X?», «¿cómo funciona la fábrica?»"
)


# ─────────────────────────── contexto vivo del sistema ────────────────────
def build_context(db) -> str:
    """Snapshot real de la fábrica para inyectar en el system prompt."""
    try:
        projects = db.list_projects(limit=40)
    except Exception:  # noqa: BLE001
        projects = []
    try:
        tpl = niches_svc.list_templates()
    except Exception:  # noqa: BLE001
        tpl = []
    by_niche: dict[str, int] = {}
    rows = []
    for p in projects[:40]:
        n = (p.get("niche") or "").strip() or "Sin nicho"
        by_niche[n] = by_niche.get(n, 0) + 1
        rows.append(f"  - [{p.get('status', '?')}] «{p.get('title', '?')[:60]}» "
                    f"nicho={n} fmt={p.get('format', '?')} "
                    f"paso={p.get('step_label') or '-'} ({p.get('progress', 0)}%)")
    niches_lines = []
    for t in tpl:
        cnt = by_niche.get(t.get("name", ""), 0)
        d = (t.get("description") or "").strip()
        niches_lines.append(f"  - {t.get('emoji', '📁')} {t.get('name')} "
                            f"({cnt} videos){' — ' + d[:70] if d else ''}")
    free = [n for n in by_niche if n != "Sin nicho"
            and not any(t.get("name") == n for t in tpl)]
    for n in free:
        niches_lines.append(f"  - 📁 {n} ({by_niche[n]} videos) [nicho libre, sin plantilla]")
    if by_niche.get("Sin nicho"):
        niches_lines.append(f"  - 🗃️ Sin nicho ({by_niche['Sin nicho']} videos)")
    counts: dict[str, int] = {}
    for p in projects:
        counts[p.get("status", "?")] = counts.get(p.get("status", "?"), 0) + 1
    try:
        avs = db.list_avatars()
        av_line = ", ".join(a["name"] for a in avs[:8]) or "ninguno"
    except Exception:  # noqa: BLE001
        av_line = "ninguno"
    ctx = ["# ESTADO ACTUAL DE LA FÁBRICA (datos reales, ahora mismo)",
           f"Proyectos: {len(projects)} totales — "
           + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "vacío")]
    if rows:
        ctx.append("Últimos proyectos:\n" + "\n".join(rows))
    else:
        ctx.append("No hay proyectos todavía (DB limpia).")
    ctx.append("Nichos:\n" + ("\n".join(niches_lines) or "  (ninguno)"))
    ctx.append(f"Avatares: {av_line}")
    return "\n".join(ctx)


# ─────────────────────────── planificación de intención ───────────────────
async def plan(message: str, history: list[dict] | None = None,
               avatars: list[dict] | None = None, db=None) -> dict:
    """Devuelve {reply, action, params, engine}. Nunca lanza excepción."""
    message = (message or "").strip()[:2000]
    if not message:
        return {"reply": _HELP_TEXT, "action": "help", "params": {}, "engine": "local"}

    context = build_context(db) if db is not None else ""
    system = SYSTEM_BRAIN + ("\n\n" + context if context else "")

    if nvidia_client.available():
        try:
            return await _plan_nvidia(message, history or [], system)
        except Exception as e:  # noqa: BLE001
            log.warning("Agente NVIDIA falló (%s) — pruebo Gemini/local", str(e)[:120])
    if gemini_client.available():
        try:
            out = await _plan_gemini(message, history or [], system)
        except Exception as e:  # noqa: BLE001
            log.warning("Agent Gemini falló (%s) — uso fallback local", str(e)[:120])
            out = _plan_local(message)
    else:
        out = _plan_local(message)
    # Detección de avatar por nombre (funciona en cualquier motor)
    if out.get("action") == "create_video" and not out["params"].get("avatar"):
        low = message.lower()
        for a in (avatars or []):
            if a["name"] and a["name"].lower() in low:
                out["params"]["avatar"] = a["name"]
                break
    return out


async def _plan_nvidia(message: str, history: list[dict], system: str) -> dict:
    msgs = [{"role": "system", "content": system}]
    for h in history[-6:]:
        if h.get("text"):
            msgs.append({"role": "user" if h.get("role") == "user" else "assistant",
                         "content": str(h["text"])[:400]})
    msgs.append({"role": "user", "content": message})
    raw = await nvidia_client.complete(msgs, temperature=0.2, max_tokens=4096)
    out = _parse_plan(raw, message, model=nvidia_client.last_model())
    return out


async def _plan_gemini(message: str, history: list[dict], system: str) -> dict:
    convo = "\n".join(f"{'Usuario' if h.get('role') == 'user' else 'VÓRTICE'}: "
                      f"{h.get('text', '')[:300]}" for h in history[-6:])
    prompt = (f"Conversación previa:\n{convo}\n\n" if convo else "") + \
             f"Mensaje nuevo del usuario: «{message}»\n\nDevuelve SOLO el JSON."
    raw = await gemini_client.generate_text(prompt, system=system)
    return _parse_plan(raw, message, model="gemini")


def _parse_plan(raw: str, message: str, model: str) -> dict:
    data = json.loads(_extract_json(raw))
    reply = str(data.get("reply") or "").strip() or "Hecho ✅"
    action = data.get("action") if data.get("action") in VALID_ACTIONS else "none"
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    params = _sanitize_params(params)
    if action == "create_video" and not params.get("idea"):
        params["idea"] = message  # el propio mensaje sirve de semilla
    return {"reply": reply, "action": action, "params": params, "engine": model}


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
    if params.get("nicho"):
        p["nicho"] = str(params["nicho"])[:60]
    if params.get("name"):
        p["name"] = str(params["name"])[:60]
    if params.get("emoji"):
        p["emoji"] = str(params["emoji"])[:8]
    if params.get("description"):
        p["description"] = str(params["description"])[:200]
    if params.get("prompt"):
        p["prompt"] = str(params["prompt"])[:800]
    if params.get("project_name"):
        p["project_name"] = str(params["project_name"])[:80]
    plats = params.get("platforms")
    if isinstance(plats, list):
        p["platforms"] = [x for x in plats if x in VALID_PLATFORMS][:4]
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
        nicho = (params.get("nicho") or "").strip()
        tpl = niches_svc.get_template(nicho) if nicho else None
        if tpl:  # nicho predefinido → replica la herencia del endpoint POST
            project = db.create_project(
                title=(params.get("idea") or f"{tpl['name']}: video nuevo")[:60],
                mode="nicho", niche=tpl.get("name"),
                style=tpl.get("style") or "auto",
                format=tpl.get("format") or "short",
                voice=tpl.get("voice") or None,
                tts_provider=(avatar or {}).get("tts_provider"),
                avatar_id=(avatar or {}).get("id"),
                meta={"idea": niches_svc.compose_idea(tpl, params.get("idea")),
                      "niche_template": tpl["id"], "via": "chat-agente",
                      "transitions": True, "style_reference": True,
                      "subtitle_style": tpl.get("subtitles") or "hormozi"},
                platforms=params.get("platforms") or ["youtube"])
        else:
            style = params.get("style") or (avatar or {}).get("style") or "auto"
            project = db.create_project(
                title=(params.get("idea") or "Video del chat")[:60],
                mode="idea", style=style, format=params.get("format", "short"),
                meta={"idea": params.get("idea") or "un video viral", "via": "chat-agente",
                      "transitions": True, "style_reference": True},
                voice=(avatar or {}).get("voice"),
                tts_provider=(avatar or {}).get("tts_provider"),
                avatar_id=(avatar or {}).get("id"),
                platforms=params.get("platforms") or ["youtube", "tiktok"])
        job_id = await orchestrator.start_pipeline(project["id"])
        extra = f" Nicho: {tpl['name']}." if tpl else ""
        if not tpl:
            sname = _style_name(params.get("style") or "auto")
            extra += f" Estilo: {sname}." if sname else ""
        if avatar:
            extra += f" Personaje: {avatar['name']}."
        return {"reply": (reply or f"Producción lanzada 🚀{extra}"),
                "action": "create_video", "project": project, "job_id": job_id}

    if action == "create_niche":
        name = (params.get("name") or "").strip()
        if not name:
            return {"reply": "Dime el nombre del nicho y lo creo 🗂️", "action": "none"}
        existing = niches_svc.get_template(name)
        entry = niches_svc.upsert_template({
            "name": name, "emoji": params.get("emoji") or "📁",
            "description": params.get("description") or "",
            "prompt": params.get("prompt") or "",
            "style": params.get("style") or "auto",
            "format": params.get("format") or "short"})
        verb = "actualizado" if existing else "creado"
        return {"reply": reply or f"Nicho «{entry['name']}» {verb} {entry['emoji']} — "
                                  f"ya aparece en Proyectos. ¿Creamos el primer video?",
                "action": "create_niche", "niche": entry}

    if action == "delete_niche":
        name = (params.get("name") or "").strip()
        if not name:
            return {"reply": "¿Qué nicho borro? Dime su nombre.", "action": "none"}
        tpl = niches_svc.get_template(name)
        if tpl:
            niches_svc.delete_template(tpl["id"])
            return {"reply": reply or f"Plantilla «{tpl['name']}» {tpl.get('emoji', '')} "
                                      f"eliminada. Los videos siguen en «Sin nicho» "
                                      f"si ya no tienen plantilla.",
                    "action": "delete_niche", "deleted": tpl["name"]}
        # nicho libre: quitar el campo niche a sus proyectos
        proys = [p for p in db.list_projects(limit=100)
                 if (p.get("niche") or "").strip().lower() == name.lower()]
        for p in proys:
            db.update_project(p["id"], niche="")
        if not proys:
            return {"reply": f"No encontré ningún nicho «{name}».", "action": "none"}
        return {"reply": reply or f"Nicho libre «{name}» eliminado: "
                                  f"{len(proys)} video(s) pasaron a «Sin nicho».",
                "action": "delete_niche", "deleted": name}

    if action == "delete_project":
        name = (params.get("project_name") or "").lower().strip()
        projects = db.list_projects(limit=100)
        target = None
        if name:
            words = [w for w in re.split(r"\W+", name) if len(w) > 3][:3]
            for p in projects:
                if all(w in p["title"].lower() for w in words) and words:
                    target = p
                    break
            target = target or next(
                (p for p in projects
                 if any(w in p["title"].lower() for w in words)), None)
        if not target:
            return {"reply": f"No encontré ningún proyecto «{name or '?'}».",
                    "action": "none"}
        db.delete_project(target["id"])
        return {"reply": reply or f"Proyecto «{target['title']}» eliminado 🗑️",
                "action": "delete_project", "deleted": target["title"]}

    if action == "cleanup_failed":
        failed = [p for p in db.list_projects(limit=100) if p.get("status") == "failed"]
        for p in failed:
            db.delete_project(p["id"])
        if not failed:
            return {"reply": "No había proyectos fallidos — todo limpio ✨",
                    "action": "cleanup_failed", "deleted_count": 0}
        return {"reply": reply or f"Listo 🧹 eliminé {len(failed)} proyecto(s) "
                                  f"fallido(s). La fábrica queda limpia.",
                "action": "cleanup_failed", "deleted_count": len(failed)}

    if action == "list_niches":
        tpl = niches_svc.list_templates()
        if not tpl:
            return {"reply": "No hay nichos todavía — créame uno: «crea un nicho "
                             "de deportes extremos» 🗂️", "action": "list_niches"}
        lines = [f"{t.get('emoji', '📁')} **{t.get('name')}**" for t in tpl]
        return {"reply": reply or "Tus nichos 🗂️:\n" + "\n".join(lines),
                "action": "list_niches", "niches": tpl}

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
