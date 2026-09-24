"""Schema PRO de avatares v2.1.1 — fuente única de verdad.

Menús desplegables con la variedad de VÓRTICE PRO (tono de piel, ojos
color+forma, cabello color+largo+textura, cuerpo, arquetipo, acento,
jerga…) y ampliados con campos que VÓRTICE no tiene (género, edad,
maquillaje, accesorios, estilo de ropa en dropdown, extras).

A diferencia de VÓRTICE (cuyo veoPrompt es una plantilla estática que ni
siquiera inyecta las características), aquí CADA característica se
traduce a inglés y se inyecta en tres sitios del motor real:
  1. portrait_prompt()  → retrato del avatar (Gemini o placeholder)
  2. scene_suffix()     → TODAS las escenas del video (consistencia)
  3. persona_text()     → guion (arquetipo, personalidad, acento, jerga)
"""

from __future__ import annotations

# ── Opciones en español (value = lo que se guarda en BD) ───────────────────
AVATAR_OPTIONS: dict[str, list[str]] = {
    "genero": ["Femenino", "Masculino", "Andrógino"],
    "edad": ["18-24", "25-34", "35-44", "45-54", "55+"],
    "piel": ["Clara", "Media", "Morena", "Oscura"],
    "ojos_color": ["Azules", "Verdes", "Marrones", "Negros", "Grises", "Avellana"],
    "ojos_forma": ["Almendrados", "Redondos", "Rasgados", "Caídos"],
    "cabello_color": ["Rubio", "Castaño", "Negro", "Pelirrojo",
                      "Gris plateado", "Degradado", "Azul eléctrico", "Rosa pastel"],
    "cabello_largo": ["Corto", "Mediano", "Largo", "Extra largo"],
    "cabello_textura": ["Liso", "Ondulado", "Rizado", "Afro"],
    "cuerpo": ["Delgado", "Atlético", "Curvilíneo", "Voluptuoso", "Robusto"],
    "ropa": ["Casual elegante", "Streetwear", "Formal", "Deportivo",
             "Bohemio", "Aventurero", "Vintage", "Urbano oscuro"],
    "maquillaje": ["Natural", "Glam", "Dramático", "Artístico", "Ninguno"],
    "arquetipo": ["🔥 Rebelde", "💋 Seductora", "✨ Carismática", "💥 Explosiva",
                  "🌙 Misteriosa", "🧠 Calculadora", "🎪 Playful", "👑 Empoderada",
                  "🧭 Exploradora", "🔬 Científica", "🧙 Sabio Mentor", "🦸 Heroica"],
    "personalidad": ["Irreverente", "Misteriosa", "Carismática", "Explosiva",
                     "Cálida", "Intelectual", "Optimista", "Sarcástica",
                     "Inspiradora", "Extrovertida"],
    "acento": ["Costeño", "Bogotano", "Paisa", "Mexicano", "Argentino",
               "Neutro latino", "España", "Otro"],
    "jerga": ["Regional", "Neutro", "Mixto"],
}

# Etiquetas bonitas para el formulario (grupo → label)
FIELD_LABELS: dict[str, str] = {
    "genero": "Género",
    "edad": "Edad aparente",
    "piel": "Tono de piel",
    "ojos_color": "Color de ojos",
    "ojos_forma": "Forma de ojos",
    "cabello_color": "Color de cabello",
    "cabello_largo": "Largo de cabello",
    "cabello_textura": "Textura de cabello",
    "cuerpo": "Tipo de cuerpo",
    "ropa": "Estilo de ropa",
    "maquillaje": "Estilo de maquillaje",
    "arquetipo": "Arquetipo",
    "personalidad": "Personalidad predominante",
    "acento": "Acento al hablar",
    "jerga": "Tipo de jerga regional",
}

# ── Traducción ES→EN para los prompts de imagen ────────────────────────────
_ES_EN: dict[str, dict[str, str]] = {
    "genero": {"Femenino": "woman", "Masculino": "man",
               "Andrógino": "androgynous person"},
    "edad": {"18-24": "in her early twenties", "25-34": "in her late twenties",
             "35-44": "in her late thirties", "45-54": "in her late forties",
             "55+": "senior aged 55+"},
    "piel": {"Clara": "fair skin", "Media": "medium tan skin",
             "Morena": "olive brown skin", "Oscura": "deep dark skin"},
    "ojos_color": {"Azules": "blue", "Verdes": "green", "Marrones": "brown",
                   "Negros": "black", "Grises": "gray", "Avellana": "hazel"},
    "ojos_forma": {"Almendrados": "almond-shaped", "Redondos": "round",
                   "Rasgados": "narrow upturned", "Caídos": "downturned"},
    "cabello_color": {"Rubio": "blonde", "Castaño": "brown", "Negro": "black",
                      "Pelirrojo": "red ginger", "Gris plateado": "silver gray",
                      "Degradado": "ombre gradient", "Azul eléctrico": "electric blue",
                      "Rosa pastel": "pastel pink"},
    "cabello_largo": {"Corto": "short", "Mediano": "medium-length",
                      "Largo": "long", "Extra largo": "very long"},
    "cabello_textura": {"Liso": "straight", "Ondulado": "wavy",
                        "Rizado": "curly", "Afro": "afro-textured"},
    "cuerpo": {"Delgado": "slim", "Atlético": "athletic", "Curvilíneo": "curvy",
               "Voluptuoso": "voluptuous", "Robusto": "stocky"},
    "ropa": {"Casual elegante": "smart casual outfit", "Streetwear": "streetwear outfit",
             "Formal": "formal tailored outfit", "Deportivo": "sporty athletic wear",
             "Bohemio": "bohemian outfit", "Aventurero": "rugged adventure gear",
             "Vintage": "vintage style outfit", "Urbano oscuro": "dark urban outfit"},
    "maquillaje": {"Natural": "natural makeup", "Glam": "glam makeup",
                   "Dramático": "dramatic makeup", "Artístico": "artistic makeup"},
    "arquetipo": {"Rebelde": "rebellious attitude", "Seductora": "seductive charm",
                  "Carismática": "charismatic presence", "Explosiva": "explosive high energy",
                  "Misteriosa": "mysterious aura", "Calculadora": "strategic mastermind mind",
                  "Playful": "playful vibe", "Empoderada": "empowered confident stance",
                  "Exploradora": "adventurous explorer spirit",
                  "Científica": "brilliant scientist vibe",
                  "Sabio Mentor": "wise mentor presence", "Heroica": "heroic stance"},
    "jerga": {"Regional": "regional slang", "Neutro": "neutral speech",
              "Mixto": "mixed slang"},
}

# Orden estable al componer frases de apariencia
_LOOK_ORDER = ["piel", "ojos_color", "ojos_forma", "cabello_color",
               "cabello_largo", "cabello_textura", "cuerpo", "ropa",
               "maquillaje", "arquetipo"]

# ── Voz edge-tts sugerida según acento + género ────────────────────────────
VOICE_BY_ACCENT: dict[str, dict[str, str]] = {
    "Costeño":    {"Femenino": "es-CO-SalomeNeural", "Masculino": "es-CO-GonzaloNeural"},
    "Bogotano":   {"Femenino": "es-CO-SalomeNeural", "Masculino": "es-CO-GonzaloNeural"},
    "Paisa":      {"Femenino": "es-CO-SalomeNeural", "Masculino": "es-CO-GonzaloNeural"},
    "Mexicano":   {"Femenino": "es-MX-DaliaNeural", "Masculino": "es-MX-JorgeNeural"},
    "Argentino":  {"Femenino": "es-AR-ElenaNeural", "Masculino": "es-AR-TomasNeural"},
    "Neutro latino": {"Femenino": "es-US-IsabellaNeural", "Masculino": "es-US-AlonsoNeural"},
    "España":     {"Femenino": "es-ES-ElviraNeural", "Masculino": "es-ES-AlvaroNeural"},
}


def _clean(v) -> str:
    return str(v or "").strip()


def _en(field: str, value: str) -> str:
    """Traduce un valor ES→EN; si no conoce el valor, lo pasa tal cual
    (compatibilidad con avatares antiguos de texto libre)."""
    v = _clean(value)
    if not v:
        return ""
    key = v.replace("🔥", "").replace("💋", "").replace("✨", "").replace(
        "💥", "").replace("🌙", "").replace("🧠", "").replace("🎪", "").replace(
        "👑", "").replace("🧭", "").replace("🔬", "").replace("🧙", "").replace(
        "🦸", "").strip()
    return _ES_EN.get(field, {}).get(key) or _ES_EN.get(field, {}).get(v) or v


def _gender(ap: dict) -> str:
    g = _en("genero", ap.get("genero", "")) or "person"
    return g


def look_en(appearance: dict) -> str:
    """Frase compacta en inglés con la apariencia (para escenas)."""
    ap = appearance or {}
    bits: list[str] = []
    if ap.get("piel"):
        bits.append(_en("piel", ap["piel"]))
    ojos = " ".join(x for x in [_en("ojos_color", ap.get("ojos_color", "")),
                                _en("ojos_forma", ap.get("ojos_forma", "")),
                                "eyes"] if x.strip())
    if _clean(ap.get("ojos_color")) or _clean(ap.get("ojos_forma")):
        bits.append(ojos)
    cabello = " ".join(x for x in [_en("cabello_largo", ap.get("cabello_largo", "")),
                                   _en("cabello_textura", ap.get("cabello_textura", "")),
                                   _en("cabello_color", ap.get("cabello_color", "")),
                                   "hair"] if x.strip())
    if any(_clean(ap.get(k)) for k in ("cabello_color", "cabello_largo", "cabello_textura")):
        bits.append(cabello)
    if ap.get("cuerpo"):
        bits.append(_en("cuerpo", ap["cuerpo"]) + " build")
    if ap.get("ropa") and ap.get("ropa") != "Ninguno":
        bits.append(_en("ropa", ap["ropa"]))
    if ap.get("maquillaje") and ap.get("maquillaje") not in ("", "Ninguno"):
        bits.append(_en("maquillaje", ap["maquillaje"]))
    if ap.get("accesorios"):
        bits.append(_clean(ap["accesorios"]))
    if ap.get("extras"):
        bits.append(_clean(ap["extras"]))
    return ", ".join(b for b in bits if b)


def portrait_prompt(avatar: dict) -> str:
    """Prompt RICO del retrato — usa TODAS las características."""
    ap = avatar.get("appearance") or {}
    name = avatar.get("name") or "avatar"
    parts: list[str] = ["professional cinematic portrait photograph"]
    subject = _gender(ap)
    if ap.get("edad"):
        subject += f" aged {ap['edad']}"
    parts.append(f'of a digital avatar named "{name}", a {subject}')
    look = look_en(ap)
    if look:
        parts.append(look)
    if ap.get("arquetipo"):
        parts.append(_en("arquetipo", ap["arquetipo"]))
    if avatar.get("description"):
        parts.append(f"character vibe: {_clean(avatar['description'])[:120]}")
    if ap.get("referencia"):
        parts.append(f"style inspiration: {_clean(ap['referencia'])[:60]}")
    parts.append("front-facing headshot, cinematic lighting, soft bokeh background, "
                 "shallow depth of field, ultra detailed, photorealistic, 4k, "
                 "no text, no watermark")
    return ", ".join(parts)


def scene_suffix(avatar: dict) -> str:
    """Frase de consistencia para TODAS las escenas del video."""
    name = avatar.get("name") or "the character"
    look = look_en(avatar.get("appearance") or {})
    out = f"consistent recurring character named {name}"
    if look:
        out += f" ({look})"
    out += ", same face, hairstyle and outfit in every scene"
    return out


def persona_text(avatar: dict) -> str:
    """Bloque PERSONAJE para el guion (español) con los campos nuevos."""
    ap = avatar.get("appearance") or {}
    desc = _clean(avatar.get("description")) or "narrador carismático"
    line = (f"\nPERSONAJE RECURRENTE (consistencia obligatoria en TODAS las escenas): "
            f"se llama {avatar.get('name')}. ")
    bits = []
    if ap.get("arquetipo"):
        bits.append(f"Arquetipo: {_clean(ap['arquetipo'])}")
    if ap.get("personalidad"):
        bits.append(f"Personalidad: {_clean(ap['personalidad'])}")
    bits.append(f"Rol: {desc}")
    if ap.get("acento"):
        bits.append(f"Acento al hablar: {_clean(ap['acento'])}")
    if ap.get("jerga"):
        bits.append(f"Jerga: {_clean(ap['jerga'])} (usa expresiones naturales de esa región cuando aporte, sin exagerar)")
    if ap.get("edad"):
        bits.append(f"Edad aparente: {_clean(ap['edad'])}")
    look = look_en(ap)
    if look:
        bits.append(f"Apariencia física (usa estas palabras EN INGLÉS en cada image_prompt): {look}")
    line += ". ".join(bits) + ". "
    line += ("La locución y el tono reflejan su personalidad; si el personaje aparece "
             "visualmente, conserva EXACTAMENTE su apariencia en todas las escenas.")
    return line


def suggest_voice(acento: str, genero: str) -> str:
    """Voz edge-tts sugerida según acento + género (o '' si no hay mapa)."""
    gen = _clean(genero) or "Femenino"
    table = VOICE_BY_ACCENT.get(_clean(acento)) or {}
    return table.get(gen, "")


def schema() -> dict:
    """Payload para GET /api/avatars/schema (el frontend pinta los selects)."""
    return {"options": AVATAR_OPTIONS, "labels": FIELD_LABELS}
