"""
YOUTUBE AUTOMATION v2.0 — Catálogo de estilos visuales
"Auto" (default) + los 20 estilos de Labsia + 5 exclusivos v2.0.

El estilo SOLO afecta a los prompts de imagen (nunca a la narración,
subtítulos ni TTS). Con "auto" no se fija ningún preset: script_gen
instruye a la IA para que elija UNA estética coherente apropiada al tema,
y el fallback local $0 usa NEUTRAL_STYLE_PROMPT.
"""

# Descriptor neutro para el modo auto cuando no hay IA externa disponible:
# da coherencia cinematográfica sin imponer una estética específica.
NEUTRAL_STYLE_PROMPT = (
    "cinematic photography, dramatic lighting, rich color grading, "
    "consistent visual identity across the series, high detail")

# (id, nombre, emoji, descripción, sufijo de prompt de imagen, gradiente preview)
_AUTO: dict = {"id": "auto", "name": "Auto", "emoji": "✨",
               "desc": "La IA elige la estética según el tema (recomendado)",
               "prompt": "", "grad": "linear-gradient(135deg,#8e2de2,#4a00e0)"}

STYLES: list[dict] = [_AUTO, 
    {"id": "graphic-novel", "name": "Graphic Novel", "emoji": "🖋️",
     "desc": "Cómic negro con tinta dramática",
     "prompt": "graphic novel illustration, bold ink lines, dramatic chiaroscuro shading, halftone textures, cinematic comic book panel, high contrast black and white with selective color accents",
     "grad": "linear-gradient(135deg,#1a1a2e,#e94560)"},
    {"id": "neo-anime", "name": "Neo-Anime", "emoji": "🌸",
     "desc": "Anime moderno de alta calidad",
     "prompt": "modern anime key visual, vibrant cel shading, expressive eyes, detailed background art, Studio-grade Japanese animation style, dynamic composition",
     "grad": "linear-gradient(135deg,#ff9a9e,#fad0c4)"},
    {"id": "raw-reality", "name": "Raw Reality", "emoji": "📷",
     "desc": "Fotorealismo crudo documental",
     "prompt": "raw documentary photography, photorealistic, natural imperfect lighting, candid moment, 35mm film grain, unfiltered realism, photojournalism",
     "grad": "linear-gradient(135deg,#485563,#29323c)"},
    {"id": "pixar-3d", "name": "Pixar 3D", "emoji": "🎈",
     "desc": "Animación 3D tierna y pulida",
     "prompt": "Pixar-style 3D animation, soft global illumination, appealing stylized characters, subsurface scattering skin, vibrant colors, heartwarming cinematic render",
     "grad": "linear-gradient(135deg,#4facfe,#00f2fe)"},
    {"id": "cine-blockbuster", "name": "Cine Blockbuster", "emoji": "🎬",
     "desc": "Look de superproducción Hollywood",
     "prompt": "epic blockbuster film still, anamorphic lens, teal and orange color grading, dramatic volumetric lighting, IMAX scale, Denis Villeneuve cinematography",
     "grad": "linear-gradient(135deg,#0f2027,#2c5364)"},
    {"id": "epica-biblica", "name": "Épica Bíblica", "emoji": "📜",
     "desc": "Historias sagradas con grandeza",
     "prompt": "biblical epic painting, majestic divine light rays, ancient robes and landscapes, classical grand manner composition, golden hour aura, Prince of Egypt cinematic style",
     "grad": "linear-gradient(135deg,#c79081,#dfa579)"},
    {"id": "terror-cartoon", "name": "Terror Cartoon", "emoji": "👻",
     "desc": "Terror estilizado tipo Cartoon Network",
     "prompt": "spooky cartoon horror, Tim Burton inspired, whimsical macabre, moody purple and green palette, stylized creepy characters, dark fairy tale illustration",
     "grad": "linear-gradient(135deg,#42275a,#734b6d)"},
    {"id": "pizarra-educativa", "name": "Pizarra Educativa", "emoji": "🏫",
     "desc": "Explicaciones claras en pizarra",
     "prompt": "clean whiteboard explainer illustration, simple flat educational diagrams, friendly hand-drawn style, minimal color palette with blue marker accents, Kurzgesagt clarity",
     "grad": "linear-gradient(135deg,#f5f7fa,#c3cfe2)"},
    {"id": "vector-flat", "name": "Vector Flat Design", "emoji": "🔷",
     "desc": "Moderno, corporativo, limpio",
     "prompt": "modern flat vector illustration, bold geometric shapes, limited harmonious palette, clean negative space, corporate explainer art, crisp edges",
     "grad": "linear-gradient(135deg,#36d1dc,#5b86e5)"},
    {"id": "retro-anime-90s", "name": "Retro Anime 90s", "emoji": "📺",
     "desc": "Nostalgia VHS y celda animada",
     "prompt": "1990s retro anime screenshot, vintage cel animation, VHS scanlines and chromatic aberration, muted retro palette, Sailor Moon era aesthetic, CRT glow",
     "grad": "linear-gradient(135deg,#ee9ca7,#ffdde1)"},
    {"id": "unreal-engine-5", "name": "Unreal Engine 5", "emoji": "🎮",
     "desc": "Render hiperrealista de motor de juego",
     "prompt": "Unreal Engine 5 cinematic render, lumen global illumination, nanite hyperdetail, ray traced reflections, photorealistic game cinematic, depth of field",
     "grad": "linear-gradient(135deg,#141e30,#243b55)"},
    {"id": "analog-horror", "name": "Analog Horror", "emoji": "📼",
     "desc": "Terror de cintas VHS encontradas",
     "prompt": "analog horror aesthetic, degraded VHS footage, timestamp overlay, eerie empty spaces, found footage grain, unsettling liminal atmosphere, 1980s broadcast distortion",
     "grad": "linear-gradient(135deg,#000000,#434343)"},
    {"id": "renaissance-oil", "name": "Renaissance Oil", "emoji": "🖼️",
     "desc": "Óleo clásico con luz de museo",
     "prompt": "renaissance oil painting, Caravaggio chiaroscuro, rich varnished colors, classical composition, old master brushwork, museum masterpiece quality",
     "grad": "linear-gradient(135deg,#3e2723,#a1887f)"},
    {"id": "retro-americana", "name": "Retro Americana", "emoji": "🛻",
     "desc": "Pósters vintage años 50-70",
     "prompt": "vintage americana poster art, 1950s screen print texture, warm faded colors, retro advertising illustration, halftone dots, nostalgic mid-century charm",
     "grad": "linear-gradient(135deg,#e96443,#904e95)"},
    {"id": "crude-stickman", "name": "Crude Stickman", "emoji": "✏️",
     "desc": "Minimalismo viral de palitos",
     "prompt": "minimalist stick figure comic, crude hand-drawn marker style, white background, expressive simple characters, viral stickman storytelling aesthetic, bold black lines",
     "grad": "linear-gradient(135deg,#ffffff,#bdc3c7)"},
    {"id": "cyber-glitch", "name": "Cyber-Glitch", "emoji": "💾",
     "desc": "Cyberpunk con distorsión digital",
     "prompt": "cyberpunk digital glitch art, neon magenta and cyan, datamosh distortion, holographic UI overlays, dystopian megacity, vaporwave corruption artifacts",
     "grad": "linear-gradient(135deg,#fc466b,#3f5efb)"},
    {"id": "acuarela-magica", "name": "Acuarela Mágica", "emoji": "🎨",
     "desc": "Fantasía pintada a mano",
     "prompt": "magical watercolor illustration, soft bleeding pigments, dreamy fantasy atmosphere, delicate ink outlines, ethereal light, Studio Ghibli watercolor concept art",
     "grad": "linear-gradient(135deg,#a1c4fd,#c2e9fb)"},
    {"id": "dark-fantasy", "name": "Dark Fantasy", "emoji": "🗡️",
     "desc": "Grimdark épico y sombrío",
     "prompt": "dark fantasy concept art, grimdark atmosphere, intricate armor and monsters, dramatic rim lighting, Berserk and Dark Souls inspired, painterly detail",
     "grad": "linear-gradient(135deg,#232526,#414345)"},
    {"id": "grand-theft", "name": "Grand Theft", "emoji": "🌴",
     "desc": "Arte de portada estilo GTA",
     "prompt": "Grand Theft Auto loading screen art, bold comic ink with flat vibrant colors, satirical urban scenes, dynamic character poses, signature Rockstar illustration style",
     "grad": "linear-gradient(135deg,#f7971e,#ffd200)"},
    {"id": "custom-studio", "name": "Custom Studio", "emoji": "🎛️",
     "desc": "Tu propio descriptor de estilo",
     "prompt": "",
     "grad": "linear-gradient(135deg,#8e2de2,#4a00e0)"},

    # ── Exclusivos v2.0 (no están en Labsia) ─────────────────────────────
    {"id": "mri-brainrot", "name": "MRI Brainrot", "emoji": "🧠",
     "desc": "Escaneos 3D absurdos virales",
     "prompt": "3D MRI scan aesthetic, translucent anatomical render, medical volumetric data, eerie clinical blue lighting, viral brainrot meme style, floating holographic body parts",
     "grad": "linear-gradient(135deg,#00c6ff,#0072ff)"},
    {"id": "claymation", "name": "Claymation", "emoji": "🧸",
     "desc": "Plastilina stop-motion artesanal",
     "prompt": "claymation stop-motion style, handmade plasticine textures, visible fingerprints, Aardman-inspired characters, miniature set lighting, charming imperfection",
     "grad": "linear-gradient(135deg,#ffecd2,#fcb69f)"},
    {"id": "bhangra-boo", "name": "Barroqueremax", "emoji": "👑",
     "desc": "Lujo barroco maximalista",
     "prompt": "baroque maximalist digital painting, ornate golden details, dramatic opulent scenes, chiaroscuro with gold leaf accents, Versailles excess, hyper-decorative",
     "grad": "linear-gradient(135deg,#f6d365,#fda085)"},
    {"id": "holo-ghost", "name": "Holo-Ghost", "emoji": "🛸",
     "desc": "Hologramas espectrales futuristas",
     "prompt": "holographic spectral projection, translucent ghost-like figure with scan lines, iridescent prismatic light, dark void background, futuristic séance aesthetic",
     "grad": "linear-gradient(135deg,#654ea3,#eaafc8)"},
    {"id": "papercraft", "name": "Papercraft", "emoji": "📄",
     "desc": "Dioramas de papel en capas",
     "prompt": "layered paper craft diorama, papercut art with soft shadows, tactile construction paper textures, whimsical layered depth, papercraft stop-motion look",
     "grad": "linear-gradient(135deg,#fbc2eb,#a6c1ee)"},
]


def get_style(style_id: str) -> dict:
    for s in STYLES:
        if s["id"] == style_id:
            return s
    return STYLES[0]


def style_ids() -> list[str]:
    return [s["id"] for s in STYLES]
