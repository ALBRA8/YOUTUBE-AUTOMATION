"""v2.11 · Recetas de cámara — catálogo determinista de planos, óptica,
luz, ángulo y mood para las escenas.

Rescatado del plan externo «Avatar DNA Pipeline» (Nodo 2) y adaptado a
nuestro estilo:
  - ids cortos en inglés (van DENTRO del prompt de imagen)
  - dos familias: «cine» (look profesional) y «ugc» (selfie/amateur,
    el look creíble de cámara de móvil que dispara retención)
  - descripciones en español para humanos; los 6 campos técnicos van en
    inglés listos para inyectar en el motor de imágenes
  - SIN LLM: una receta es texto fijo que images.full_prompt() compone

Las escenas del contrato guion_json pueden elegir receta con el campo
«camara» (o heredar la del proyecto); sin receta, el prompt queda como
siempre. Catálogo navegable en GET /api/cameras y tool MCP
listar_recetas_camara.
"""
from __future__ import annotations

FAMILIAS = ("cine", "ugc")

# ── 11 recetas cinematográficas ────────────────────────────────────────────
# Vocabulario que SÍ steering a los modelos de imagen: óptica real, grade,
# film stock, luz. Marcas solo como «sello» final (shot on X), que es la
# forma en que los modelos las entienden mejor.
_RECIPES: dict[str, dict] = {
    # ── CINE ──
    "cine_anamorfico": {
        "nombre": "Cine · Anamórfico teal & orange", "familia": "cine",
        "desc": "Look blockbuster: flare horizontal, piel cálida contra fondos fríos.",
        "shot": "cinematic medium shot",
        "lens": "anamorphic lens, shallow depth of field, horizontal lens flare",
        "lighting": "dramatic cinematic lighting, teal and orange color grade",
        "mood": "epic, high production value",
        "angle": "eye level",
        "render": "shot on ARRI Alexa, subtle 35mm film grain, 4k",
    },
    "cine_macro_belleza": {
        "nombre": "Cine · Macro beauty", "familia": "cine",
        "desc": "Primerísimo plano con textura de piel real; ideal para el hook.",
        "shot": "extreme close-up beauty shot",
        "lens": "100mm macro lens, razor-thin depth of field, detailed skin texture",
        "lighting": "soft diffused beauty light with gentle falloff",
        "mood": "intimate, luxurious",
        "angle": "straight on",
        "render": "high-end cosmetics commercial style, 8k detail",
    },
    "cine_hora_dorada": {
        "nombre": "Cine · Golden hour vintage", "familia": "cine",
        "desc": "Contraluz cálido de atardecer con halo retro años 70.",
        "shot": "cinematic wide-medium shot at sunset",
        "lens": "vintage 70mm lens, halation glow, warm bloom",
        "lighting": "golden hour backlight, sun flare rim light",
        "mood": "nostalgic, dreamy warmth",
        "angle": "slightly low angle",
        "render": "shot on Kodak Portra 400 film, faded vintage grade",
    },
    "cine_editorial": {
        "nombre": "Cine · Editorial de moda", "familia": "cine",
        "desc": "Estudio de moda formato medio; pose y vestuario protagonista.",
        "shot": "full body fashion editorial shot",
        "lens": "medium format camera look, crisp optics",
        "lighting": "clean studio strobe light, seamless backdrop",
        "mood": "confident, high fashion",
        "angle": "eye level",
        "render": "Hasselblad editorial photography, magazine cover quality",
    },
    "cine_perfil_zeiss": {
        "nombre": "Cine · Perfil Zeiss 85mm", "familia": "cine",
        "desc": "Retrato de perfil con claroscuro; carácter y misterio.",
        "shot": "side profile portrait",
        "lens": "85mm f1.4 lens, creamy bokeh, sharp eye focus",
        "lighting": "chiaroscuro single side light, deep shadows",
        "mood": "mysterious, intense",
        "angle": "profile angle",
        "render": "shot on Zeiss Otus, dark cinematic grade",
    },
    "cine_noir_bn": {
        "nombre": "Cine · Noir blanco y negro", "familia": "cine",
        "desc": "Monocromo de alto contraste con sombras duras; drama puro.",
        "shot": "dramatic noir shot",
        "lens": "50mm prime lens, deep contrast",
        "lighting": "hard key light, venetian blind shadows, black background",
        "mood": "tense, film noir mystery",
        "angle": "dutch tilt angle",
        "render": "black and white monochrome, shot on RED monochrome, heavy film grain",
    },
    "cine_nocturna_neon": {
        "nombre": "Cine · Nocturna neón", "familia": "cine",
        "desc": "Ciudad de noche, bokeh de neón y calles mojadas.",
        "shot": "night city medium shot",
        "lens": "50mm f0.95 lens, neon bokeh orbs, reflections on wet street",
        "lighting": "neon signage glow, magenta and cyan ambient light",
        "mood": "electric, urban nocturne",
        "angle": "eye level",
        "render": "shot on Leica Noctilux, cyberpunk cinematic grade",
    },
    "cine_epica_granangular": {
        "nombre": "Cine · Épica gran angular", "familia": "cine",
        "desc": "Escena monumental con escala IMAX y rayos volumétricos.",
        "shot": "epic establishing wide shot",
        "lens": "ultra wide 18mm lens, grand scale perspective",
        "lighting": "volumetric god rays, atmospheric haze",
        "mood": "awe-inspiring, monumental",
        "angle": "low hero angle",
        "render": "IMAX scale cinematography, epic fantasy film still",
    },
    "cine_drama_cenital": {
        "nombre": "Cine · Drama con luz cenital", "familia": "cine",
        "desc": "Un solo haz de luz superior sobre fondo negro; tensión máxima.",
        "shot": "isolated medium shot",
        "lens": "85mm lens, surrounding darkness",
        "lighting": "single hard toplight beam, pitch black void background",
        "mood": "ominous, suspenseful",
        "angle": "slightly high angle looking down",
        "render": "psychological thriller cinematography, high contrast",
    },
    "cine_sueno_suave": {
        "nombre": "Cine · Sueño difuso", "familia": "cine",
        "desc": "Filtro difusor pastel, bruma romántica onírica.",
        "shot": "soft dreamy portrait shot",
        "lens": "vintage portrait lens with diffusion filter, glowing highlights",
        "lighting": "pastel haze backlight, soft pink and lavender tones",
        "mood": "romantic, ethereal",
        "angle": "eye level",
        "render": "dreamy music video aesthetic, soft focus glow",
    },
    "cine_documental": {
        "nombre": "Cine · Documental crudo", "familia": "cine",
        "desc": "Luz natural, cámara en mano, realismo sin pulir.",
        "shot": "handheld documentary shot",
        "lens": "35mm reportage lens, natural perspective",
        "lighting": "available natural light, unpolished realism",
        "mood": "authentic, urgent, raw",
        "angle": "slightly off-balance handheld angle",
        "render": "photojournalism style, slight motion blur, muted colors",
    },

    # ── UGC / SELFIE ──
    "ugc_selfie_dorada": {
        "nombre": "UGC · Selfie a contraluz dorado", "familia": "ugc",
        "desc": "Selfie con cámara frontal al atardecer; confianza y calor.",
        "shot": "front-facing phone selfie, arm's length framing",
        "lens": "smartphone front camera, slight wide angle distortion",
        "lighting": "warm golden hour sunlight on face, soft shadows",
        "mood": "candid, glowing, relatable",
        "angle": "slightly high selfie angle",
        "render": "casual iphone photo, natural skin, no edit look",
    },
    "ugc_gimnasio_espejo": {
        "nombre": "UGC · Espejo de gimnasio", "familia": "ugc",
        "desc": "Selfie al espejo del gym con el móvil tapando la cara parcialmente.",
        "shot": "mirror selfie with phone visible",
        "lens": "smartphone rear camera through mirror",
        "lighting": "bright overhead gym lighting, slight glare",
        "mood": "energetic, fitness lifestyle",
        "angle": "chest height angle",
        "render": "casual gym selfie photo, authentic amateur look",
    },
    "ugc_manana_cama": {
        "nombre": "UGC · Mañanero en la cama", "familia": "ugc",
        "desc": "Selfie de cama con luz de ventana; espontaneidad total.",
        "shot": "selfie lying in bed, morning hair",
        "lens": "smartphone front camera, close framing",
        "lighting": "soft diffused morning window light",
        "mood": "cozy, intimate, just woke up",
        "angle": "high selfie angle looking down",
        "render": "casual bedroom phone photo, warm tones",
    },
    "ugc_cafeteria": {
        "nombre": "UGC · Mesa de cafetería", "familia": "ugc",
        "desc": "Plano de mesa con café en mano y luz de ventana.",
        "shot": "seated table shot with coffee cup in hand",
        "lens": "smartphone main camera, natural framing",
        "lighting": "cozy cafe window backlight, warm interior tones",
        "mood": "relaxed, conversational",
        "angle": "eye level across the table",
        "render": "casual lifestyle photo, instagram natural look",
    },
    "ugc_playa_accion": {
        "nombre": "UGC · Playa con cámara de acción", "familia": "ugc",
        "desc": "Gran angular tipo GoPro en la playa; energía y sol.",
        "shot": "wide angle action cam shot at arm's length",
        "lens": "action camera ultra wide lens, fisheye edge distortion",
        "lighting": "bright direct sunlight, sparkling water reflections",
        "mood": "adventurous, high energy summer",
        "angle": "selfie stick angle",
        "render": "gopro style photo, vibrant saturated colors",
    },
    "ugc_fiesta_flash": {
        "nombre": "UGC · Flash directo de fiesta", "familia": "ugc",
        "desc": "Flash de cámara en fiesta nocturna; look candid inmediato.",
        "shot": "night party candid shot",
        "lens": "smartphone camera with direct on-camera flash",
        "lighting": "harsh direct flash, bright subject against dark background",
        "mood": "chaotic fun, party night energy",
        "angle": "eye level close",
        "render": "flash photography look, slight overexposure, authentic party photo",
    },
    "ugc_ascensor": {
        "nombre": "UGC · Espejo de ascensor", "familia": "ugc",
        "desc": "Selfie en el espejo del ascensor; estética urbana nocturna.",
        "shot": "elevator mirror selfie",
        "lens": "smartphone rear camera through elevator mirror",
        "lighting": "dim warm elevator lighting, ceiling spot glow",
        "mood": "urban night out, effortless",
        "angle": "chest height angle",
        "render": "casual night selfie photo, grainy low light look",
    },
    "ugc_vlog_caminando": {
        "nombre": "UGC · Vlog caminando", "familia": "ugc",
        "desc": "Plano de seguimiento gimbal callejeara; narrador en movimiento.",
        "shot": "walking vlog follow shot, subject talking to camera",
        "lens": "smartphone wide camera with gimbal smoothness",
        "lighting": "natural daylight street ambience",
        "mood": "dynamic, storytelling on the move",
        "angle": "front follow angle at walking pace",
        "render": "youtube vlog screenshot style, motion energy",
    },
    "ugc_ring_light": {
        "nombre": "UGC · Ring light de creador", "familia": "ugc",
        "desc": "Setup de creador: catchlight circular en los ojos, fondo dormitorio.",
        "shot": "creator setup talking head shot",
        "lens": "smartphone camera on tripod, centered framing",
        "lighting": "ring light with circular catchlights in the eyes, soft even glow",
        "mood": "direct to camera, influencer confident",
        "angle": "eye level centered",
        "render": "content creator video still, clean bedroom studio background",
    },
}


def get(recipe_id) -> dict | None:
    """Devuelve la receta por id (o None si el id no existe)."""
    if not recipe_id:
        return None
    return _RECIPES.get(str(recipe_id).strip().lower())


def ids() -> set[str]:
    return set(_RECIPES)


def list() -> list[dict]:  # noqa: A003 — API en español deliberada
    """Catálogo completo (id + campos) — para /api/cameras y la tool MCP."""
    return [{"id": rid, **r} for rid, r in _RECIPES.items()]


def compact() -> list[dict]:
    """Versión compacta para el spec del contrato y listados rápidos."""
    return [{"id": rid, "nombre": r["nombre"], "familia": r["familia"],
             "desc": r["desc"]} for rid, r in _RECIPES.items()]


def block(rec: dict) -> str:
    """Bloque de prompt EN INGLÉS de la receta (plano → ángulo → luz →
    óptica → mood → sello de render). Lo compone images.full_prompt()."""
    return (f"{rec['shot']}, {rec['angle']} angle, {rec['lighting']}, "
            f"{rec['lens']}, {rec['mood']}, {rec['render']}")
