"""v2.11 · Contrato guion_json — la puerta USB entre un guionista externo
(ChatGPT, Custom GPT, Actions) y la fábrica.

UN SOLO CONTRATO de entrada:

    {
      "titulo": str ≤60 (opcional),
      "formato": "short" (9:16) | "long" (16:9)  (default short),
      "estilo": id visual de /api/styles (default "auto"),
      "voz": voz edge-tts opcional (ej. es-ES-AlvaroNeural),
      "avatar_id": personaje opcional,
      "camara": receta de cámara por defecto opcional (GET /api/cameras),
      "nicho": carpeta opcional del árbol de proyectos,
      "plataformas": ["youtube"|"tiktok"|"instagram"|"facebook"],
      "escenas": [ { "titulo"?: str,
                     "narracion": str ≤2000 (OBLIGATORIA),
                     "prompt_imagen"?: str EN INGLÉS,
                     "camara"?: receta (override de la del proyecto),
                     "outfit"?: vestuario de la escena ≤120,
                     "ambiente"?: entorno ≤200 } ]  (2 a 40),
      "cta": str ≤300 (opcional — se añade como escena final),
      "auto_start": bool (true = lanza el pipeline al ingerir)
    }

v2.11 · Rescatado del plan «Avatar DNA Pipeline»: camara/outfit/ambiente
por escena. La receta es texto determinista de services/camera_recipes.py
(cero LLM); el outfit reemplaza la ropa del avatar SOLO en esa escena
(la cara nunca cambia) y ambiente añade el entorno visual.

Reglas del guionista (HOOK 0-3 s · escalada · giro+CTA · 15-30 palabras por
escena · prompt_imagen en inglés sin texto en la imagen) viven en el spec
expuesto en GET /api/guion_json/contrato y en docs/gpt_guionista_instrucciones.md.

Aquí NO hay LLM interno: la fábrica jamás regenera nada — valida, normaliza
(alias ES/EN, fences ```json, fallbacks) y crea el proyecto listo para el
pipeline (PASO 2 imágenes en adelante; el guion ya viene hecho).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import database as db
from services import camera_recipes
from services.originality import keywords as _keywords
from services.themes import get_style

# ── límites del contrato ───────────────────────────────────────────────────
MIN_ESCENAS, MAX_ESCENAS = 2, 40
MAX_TITULO = 60
MAX_NARRACION = 2000
MAX_CTA = 300
MAX_OUTFIT = 120
MAX_AMBIENTE = 200
FORMATOS = ("short", "long")
PLATAFORMAS = ("youtube", "tiktok", "instagram", "facebook")

# alias ES/EN aceptados (el guionista puede hablar cualquiera de las dos)
_ALIASES = {
    "titulo": ("titulo", "title", "título"),
    "formato": ("formato", "format"),
    "estilo": ("estilo", "style"),
    "voz": ("voz", "voice"),
    "avatar_id": ("avatar_id", "avatar", "personaje"),
    "nicho": ("nicho", "niche", "carpeta"),
    "camara": ("camara", "cámara", "camera", "camera_recipe",
               "camera_receta", "receta_camara", "receta"),
    "outfit": ("outfit", "vestuario", "atuendo"),
    "ambiente": ("ambiente", "environment", "escenario", "lugar", "setting"),
    "plataformas": ("plataformas", "platforms"),
    "escenas": ("escenas", "scenes"),
    "cta": ("cta", "call_to_action", "cierre"),
    "auto_start": ("auto_start", "autoStart", "auto"),
    "narracion": ("narracion", "narration", "texto", "voz_off"),
    "prompt_imagen": ("prompt_imagen", "image_prompt", "imageprompt",
                      "prompt", "visual"),
    "titulo_escena": ("titulo", "title"),
}

_ESCENA_ID_RE = re.compile(r"^[a-z0-9-]+$")


def _first(d: dict, canonical: str):
    """Devuelve el primer valor presente del campo (por alias) en d."""
    for k in _ALIASES.get(canonical, (canonical,)):
        if k in d and d[k] is not None:
            return d[k]
    return None


def parse_payload(payload) -> dict:
    """Acepta dict, str JSON o str con fences ```json …``` y devuelve dict."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("payload vacío — envía el JSON del contrato")
    txt = payload.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", txt, re.DOTALL)
    if m:
        txt = m.group(1)
    try:
        data = json.loads(txt)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido: {e} — respeta el contrato "
                         f"(GET /api/guion_json/contrato)")
    if not isinstance(data, dict):
        raise ValueError("el JSON debe ser un objeto con los campos del contrato")
    return data


def _limpia(s) -> str:
    return str(s or "").strip()


def validate(data: dict, estilos_validos: set[str]) -> tuple[dict, list[str]]:
    """Valida y normaliza → (guion_normalizado, avisos). ValueError si grave."""
    av: list[str] = []
    g: dict = {}

    # ── campos simples ──
    titulo = _limpia(_first(data, "titulo"))
    g["titulo"] = titulo[:MAX_TITULO] or None

    formato = _limpia(_first(data, "formato")).lower() or "short"
    if formato in ("vertical", "9:16", "reel"):
        formato = "short"
    elif formato in ("horizontal", "16:9", "largo"):
        formato = "long"
    if formato not in FORMATOS:
        av.append(f"formato «{formato}» desconocido — uso short (9:16)")
        formato = "short"
    g["formato"] = formato

    estilo = _limpia(_first(data, "estilo")).lower() or "auto"
    if estilo not in estilos_validos:
        av.append(f"estilo «{estilo}» no existe — uso auto")
        estilo = "auto"
    g["estilo"] = estilo

    g["voz"] = _limpia(_first(data, "voz")) or None
    g["avatar_id"] = _limpia(_first(data, "avatar_id")) or None
    # nicho/carpeta del árbol de proyectos (texto libre — p.ej. «Primitive Viral»)
    nicho = _limpia(_first(data, "nicho"))
    g["nicho"] = nicho[:60] or None

    # v2.11 · receta de cámara por defecto del proyecto (cada escena puede
    # sobreescribirla con su propio «camara»)
    cam = _limpia(_first(data, "camara")).lower()
    if cam and cam not in camera_recipes.ids():
        av.append(f"receta de cámara «{cam}» no existe — ignorada "
                  "(válido: GET /api/cameras)")
        cam = ""
    g["camara"] = cam or None

    plats = _first(data, "plataformas")
    if not isinstance(plats, list):
        plats = ["youtube"]
    plats = [str(p).strip().lower() for p in plats]
    buenas = [p for p in plats if p in PLATAFORMAS]
    if len(buenas) < len(plats):
        av.append("plataformas ignoradas: "
                  + ", ".join(p for p in plats if p not in PLATAFORMAS))
    g["plataformas"] = buenas or ["youtube"]

    # ── escenas (el corazón del contrato) ──
    escenas_raw = _first(data, "escenas")
    if not isinstance(escenas_raw, list) or not escenas_raw:
        raise ValueError("falta «escenas»: lista de 2 a 40 objetos "
                         "{narracion (obligatoria), prompt_imagen? (inglés)}")
    escenas: list[dict] = []
    for i, e in enumerate(escenas_raw, 1):
        if not isinstance(e, dict):
            raise ValueError(f"escena {i}: debe ser un objeto, no {type(e).__name__}")
        narr = _limpia(_first(e, "narracion"))
        if not narr:
            raise ValueError(f"escena {i}: falta «narracion» (obligatoria)")
        if len(narr) > MAX_NARRACION:
            raise ValueError(f"escena {i}: narracion de {len(narr)} caracteres "
                             f"excede el máximo ({MAX_NARRACION})")
        esc = {"title": (_limpia(_first(e, "titulo_escena")) or f"Escena {i}"),
               "narration": narr,
               "image_prompt": _limpia(_first(e, "prompt_imagen"))}
        # v2.11 · dirección de cámara y escena por escena (opcional) —
        # se guardan en meta de la escena y images.py las compone al vuelo
        mesc: dict = {}
        rec = _limpia(_first(e, "camara")).lower()
        if rec:
            if rec in camera_recipes.ids():
                mesc["camara"] = rec
            else:
                av.append(f"escena {i}: receta de cámara «{rec}» no existe "
                          "— ignorada (GET /api/cameras)")
        outfit = _limpia(_first(e, "outfit"))
        if outfit:
            if len(outfit) > MAX_OUTFIT:
                outfit = outfit[:MAX_OUTFIT]
                av.append(f"escena {i}: outfit recortado a {MAX_OUTFIT} caracteres")
            mesc["outfit"] = outfit
        amb = _limpia(_first(e, "ambiente"))
        if amb:
            if len(amb) > MAX_AMBIENTE:
                amb = amb[:MAX_AMBIENTE]
                av.append(f"escena {i}: ambiente recortado a {MAX_AMBIENTE} caracteres")
            mesc["ambiente"] = amb
        if mesc:
            esc["meta"] = mesc
        escenas.append(esc)

    # ── CTA → escena final ──
    cta = _limpia(_first(data, "cta"))
    if cta:
        if len(cta) > MAX_CTA:
            cta = cta[:MAX_CTA]
            av.append(f"cta recortado a {MAX_CTA} caracteres")
        escenas.append({"title": "CTA", "narration": cta, "image_prompt": ""})

    if not (MIN_ESCENAS <= len(escenas) <= MAX_ESCENAS):
        raise ValueError(f"el guion debe tener entre {MIN_ESCENAS} y {MAX_ESCENAS} "
                         f"escenas (llegaron {len(escenas)})")

    # ── fallback de prompt_imagen (silencioso, como la fábrica lo espera) ──
    st = get_style(g["estilo"])
    for i, esc in enumerate(escenas, 1):
        p = esc["image_prompt"]
        if p and re.search(r"\b(texto|text|letras|words?)\b", p, re.IGNORECASE) \
                and "no text" not in p.lower():
            p = re.sub(r",?\s*\b(texto|text|letras|words?)\b.*$", "", p,
                       flags=re.IGNORECASE).strip(", ") or p
            p += ", no text"
            esc["image_prompt"] = p
            av.append(f"escena {i}: el prompt pedía texto en la imagen — "
                      "sanitizado (la fábrica no escribe texto)")
        if not esc["image_prompt"]:
            # fallback silencioso: se compone desde la narración + estilo visual
            kw = ", ".join(_keywords(esc["narration"], 4)) or esc["title"]
            esc["image_prompt"] = (f"{kw}, {st['name']} style, cinematic, "
                                   "high detail, no text")

    g["escenas"] = escenas
    g["cta"] = cta or None
    auto = _first(data, "auto_start")
    g["auto_start"] = bool(auto) if auto is not None else False
    return g, av


def spec(estilos_ids: list[str]) -> dict:
    """Spec machine-readable del contrato (para Actions de ChatGPT y humanos)."""
    camaras = ", ".join(r["id"] for r in camera_recipes.compact())
    return {
        "version": "2.11",
        "uso": 'Devuelve este JSON a POST /api/projects con {"mode": "guion_json", '
               "...guion} o a la tool MCP crear_video_guion_json (ahí va como "
               "TEXTO JSON en 'guion').",
        "campos": {
            "titulo": "str opcional ≤60 — título del proyecto",
            "formato": "'short' (9:16) | 'long' (16:9) — default short",
            "estilo": f"id visual (GET /api/styles) — default 'auto'. Válidos: {', '.join(estilos_ids)}",
            "voz": "voz edge-tts opcional (ej. es-ES-AlvaroNeural)",
            "avatar_id": "personaje opcional (GET /api/avatars)",
            "camara": f"receta de cámara opcional por defecto para TODAS las escenas. "
                      f"Ids válidos: {camaras} (detalle: GET /api/cameras)",
            "nicho": "carpeta opcional del árbol de proyectos (texto libre, ≤60; "
                     "ej. 'Primitive Viral') — sin él va a «Sin nicho»",
            "plataformas": "lista: youtube|tiktok|instagram|facebook — default [youtube]",
            "escenas": "lista OBLIGATORIA de 2 a 40 objetos: {titulo?, narracion "
                       "(obligatoria ≤2000), prompt_imagen? (inglés), camara? "
                       "(receta, override del proyecto), outfit? (vestuario de la "
                       "escena ≤120 — sustituye la ropa del avatar SOLO aquí), "
                       "ambiente? (entorno visual ≤200)}",
            "cta": "str opcional ≤300 — se añade como escena final",
            "auto_start": "bool — true lanza el pipeline completo al ingerir",
        },
        "reglas": [
            "HOOK (escena 1): 0-3 s, rompe el patrón; prohibido saludar o presentarse",
            "ESCALADA: cada escena revela un micro-dato nuevo con tensión creciente",
            "GIRO + CTA: clímax al final y llamada natural a debate/seguir",
            "narracion: 15-30 palabras por escena (se escucha, no se lee)",
            "prompt_imagen: EN INGLÉS, una sola idea visual por escena, sin texto "
            "en la imagen (la fábrica lo rechaza/sanitiza si lleva)",
            "camara/outfit/ambiente son OPCIONALES por escena: úsalos para variar "
            "el plano y el vestuario sin tocar la identidad del personaje",
        ],
        "ejemplo": {
            "titulo": "El faro que gritaba",
            "formato": "short",
            "estilo": "auto",
            "nicho": "Misterio",
            "escenas": [
                {"titulo": "Hook",
                 "narracion": "En 1900, tres fareros vieron algo en la noche "
                              "que jamás pudieron explicar.",
                 "prompt_imagen": "remote lighthouse on a stormy cliff at night, "
                                  "massive waves, dramatic moonlight, cinematic, no text"},
                {"narracion": "Cuando llegó el relevo, la puerta estaba abierta… "
                              "y la comida seguía caliente sobre la mesa.",
                 "prompt_imagen": "abandoned lighthouse kitchen with steaming hot meal, "
                                  "open door, eerie green light, cinematic, no text"},
                {"narracion": "El diario del farero terminaba con una sola frase: "
                              "«él vuelve cuando la niebla canta».",
                 "prompt_imagen": "old handwritten diary open on desk, fog outside "
                                  "window, unsettling atmosphere, cinematic, no text"},
            ],
            "cta": "¿Te atreverías a pasar una noche ahí? Dímelo en los comentarios.",
            "auto_start": False,
        },
    }


async def ingest(payload, estilos_validos: set[str],
                 crear_proyecto) -> dict:
    """Ingesta completa: parse → validate → crear proyecto → escenas → arrancar.

    `crear_proyecto(guion)` es un callback (lo pasa main.py) que crea la fila
    en SQLite con los campos heredados del contrato y devuelve el dict proyecto.
    Lanza ValueError con mensajes listos para el guionista externo.
    """
    data = parse_payload(payload)
    g, avisos = validate(data, estilos_validos)
    project = crear_proyecto(g)
    pid = project["id"]
    db.replace_scenes(pid, g["escenas"])
    meta = project.get("meta") or {}
    meta["guion_json"] = {
        "fuente": "chatgpt",
        "avisos": avisos,
        "escenas_originales": len(g["escenas"]),
        "ingestado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    db.update_project(pid, meta=meta)

    job_id = None
    if g["auto_start"]:
        # import diferido: evita círculo main → guion_json → main
        from pipeline import orchestrator
        job_id = await orchestrator.start_pipeline(pid, autopublish=False)

    return {
        "ok": True,
        "project_id": pid,
        "titulo": project.get("title"),
        "modo": "guion_json",
        "estilo": g["estilo"],
        "formato": g["formato"],
        "escenas": len(g["escenas"]),
        "avisos": avisos,
        "job_id": job_id,
        "siguiente": (f"pipeline lanzado (job {job_id})" if job_id
                      else f"consulta el estado del proyecto {pid} o ábrelo en el dashboard"),
    }
