"""
Sanitizer — Blindaje anti-filtros + enriquecimiento fotográfico (Inyección 1).

Resuelve 3 carencias del pipeline:
  1. SAFETY FILTERS: Gemini Imagen / Flow / Meta AI bloquean prompts con
     "pistola", "sangre", "explosión", nombres de superhéroes o actores
     (error 400 Safety Policy Violation). Aquí se suavizan con reemplazos
     semánticos que conservan la intención visual.
  2. PROMPTS PLANOS: inyección de física óptica real (cámara, lente,
     iluminación volumétrica, motor de render) solo cuando el estilo es
     fotorrealista — si es cartoon/anime NO se toca.
  3. IDENTIDAD DE MARCA: inyección de ropa fija + logotipo institucional
     en el pecho de cada sujeto, de forma armónica.

Uso en el pipeline:
  - script_gen.build_result() sanitiza todas las escenas recién generadas.
  - flow_export.build_script_json() sanitiza el script.json que consume la
    extensión Flow Script Processor (nunca un filtro bloquea el export).
"""
from __future__ import annotations

import re

# ── 1. Seguridad y limpieza de texto en pantalla ─────────────────────────
# Los generadores de imagen fallan o dibujan letras garbage con texto
# literal en el prompt. También suavizamos armas/violencia (EN + ES).
GENERAL_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    # texto renderizado en la imagen (siempre problemático)
    (re.compile(r"(?i)\bwith\s+the\s+text\s+['\"].*?['\"]"), ""),
    (re.compile(r"(?i)\bwith\s+text\s+['\"].*?['\"]"), ""),
    (re.compile(r"(?i)\bfeaturing\s+text\s+['\"].*?['\"]"), ""),
    (re.compile(r"(?i)\bwords\s+saying\s+['\"].*?['\"]"), ""),
    (re.compile(r"(?i)\bsign\s+that\s+says\s+['\"].*?['\"]"), "sign"),
    (re.compile(r"(?i)\blabel\s+saying\s+['\"].*?['\"]"), "label"),
    (re.compile(r"(?i)\bwritten\s+on\s+it\s+['\"].*?['\"]"), ""),
    (re.compile(r"(?i)\ba\s+banner\s+reading\s+['\"].*?['\"]"), "a banner"),
    (re.compile(r"(?i)\ba\s+logo\s+with\s+['\"].*?['\"]"), "a logo"),
    (re.compile(r"(?i)\btext\s+['\"].*?['\"]"), ""),

    # armas, violencia y seguridad (EN)
    (re.compile(r"(?i)\bguns\b"), "prop devices"),
    (re.compile(r"(?i)\bgun\b"), "prop device"),
    (re.compile(r"(?i)\bpistols\b"), "small devices"),
    (re.compile(r"(?i)\bpistol\b"), "small device"),
    (re.compile(r"(?i)\brifles\b"), "long devices"),
    (re.compile(r"(?i)\brifle\b"), "long device"),
    (re.compile(r"(?i)\bweapons\b"), "gear"),
    (re.compile(r"(?i)\bweapon\b"), "gear"),
    (re.compile(r"(?i)\bbloody\b"), "red-stained"),
    (re.compile(r"(?i)\bblood\b"), "red liquid"),
    (re.compile(r"(?i)\bmurder\b"), "defeat"),
    (re.compile(r"(?i)\bkill\b"), "defeat"),
    (re.compile(r"(?i)\ban\s+explosion\b"), "a burst of light"),
    (re.compile(r"(?i)\bexplosions\b"), "bursts of light"),
    (re.compile(r"(?i)\bexplosion\b"), "burst of light"),
    (re.compile(r"(?i)\bbombs\b"), "devices"),
    (re.compile(r"(?i)\bbomb\b"), "device"),
    (re.compile(r"(?i)\bshooting\b"), "aiming"),
    (re.compile(r"(?i)\bshoot\b"), "aim"),
    (re.compile(r"(?i)\bknife\b"), "blade prop"),
    (re.compile(r"(?i)\bmachine\s+gun\b"), "long device"),

    # armas, violencia y seguridad (ES) — el modo artesano itera en español
    (re.compile(r"(?i)\bpistolas?\b"), "dispositivo de atrezo"),
    (re.compile(r"(?i)\brev[oó]lver(es)?\b"), "dispositivo de atrezo"),
    (re.compile(r"(?i)\brifl?es?\b"), "dispositivo alargado"),
    (re.compile(r"(?i)\barmas?\b"), "equipo de atrezo"),
    (re.compile(r"(?i)\bsangrient[oa]s?\b"), "teñido de rojo"),
    (re.compile(r"(?i)\bsangre\b"), "líquido rojo"),
    (re.compile(r"(?i)\bmatar\b"), "derrotar"),
    (re.compile(r"(?i)\bas[ae]sin(at[oa]s?|ar|io)?\b"), "derrota"),
    (re.compile(r"(?i)\babatidos\b"), "derrotados"),
    (re.compile(r"(?i)\babatidas\b"), "derrotadas"),
    (re.compile(r"(?i)\babatido\b"), "derrotado"),
    (re.compile(r"(?i)\babatida\b"), "derrotada"),
    (re.compile(r"(?i)\bexplosi[oó]n(es)?\b"), "ráfaga de luz"),
    (re.compile(r"(?i)\bbombas?\b"), "dispositivos"),
    (re.compile(r"(?i)\bcuchill[oa]s?\b"), "objeto de atrezo"),
    (re.compile(r"(?i)\ba\s+tiros\b"), "en el enfrentamiento"),
    (re.compile(r"(?i)\btiros\b"), "enfrentamientos"),
    (re.compile(r"(?i)\bdisparos?\b"), "ráfagas de luz"),
    (re.compile(r"(?i)\bbalas?\b"), "proyectiles de atrezo"),
    (re.compile(r"(?i)\bametralladora?s?\b"), "dispositivo alargado"),
]

# ── 2. Personajes con copyright / actores protegidos ─────────────────────
COPYRIGHT_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\ban\s+Iron\s+Man\b"), "a red and gold high-tech armored superhero"),
    (re.compile(r"(?i)\bIron\s+Man\b"), "red and gold high-tech armored superhero"),
    (re.compile(r"(?i)\bCaptain\s+America\b"), "patriotic superhero in red-white-and-blue suit"),
    (re.compile(r"(?i)\bSpider-?Man\b"), "red and blue web-slinging superhero"),
    (re.compile(r"(?i)\bThor\b"), "powerful hammer-wielding thunder hero"),
    (re.compile(r"(?i)\bHulk\b"), "giant green muscular hero"),
    (re.compile(r"(?i)\bMarvel\b"), "comic book superhero"),
    (re.compile(r"(?i)\bDisney\b"), "animated"),
    (re.compile(r"(?i)\bChris\s+Evans\b"), "a handsome heroic man"),
    (re.compile(r"(?i)\bRobert\s+Downey\b(\s+Jr\.?)?"), "a charismatic smart man"),
]

_SKETCH_KWS = ("cartoon", "anime", "illustration", "sketch", "comic", "draw",
               "vector", "flat", "painting", "pencil", "lineart", "watercolor",
               "acuarela", "stickman", "claymation")
_REALISM_KWS = ("real", "realistic", "cinematic", "photography", "documentary",
                "photorealistic", "raw", "hyper-real", "hyper-realistic",
                "cine-blockbuster", "raw-reality")


def sanitize_text(text: str, brand_name: str | None = None,
                  allow_brand_text: bool = False,
                  bypass_copyright: bool = False) -> str:
    """Suaviza términos bloqueables y copyright preservando la intención visual.

    brand_name + allow_brand_text: si la marca del proyecto aparece entre
    comillas en el prompt (ej. letrero de madera del export Flow), se protege
    del borrado de "text '...'" y se restaura al final intacta.
    """
    if not text:
        return text
    preserved: list[tuple[str, str]] = []
    if allow_brand_text and brand_name:
        esc_b = re.escape(brand_name)

        def hold(m: re.Match) -> str:
            tok = f"__BRAND_{len(preserved)}__"
            preserved.append((tok, m.group(0)))
            return tok

        text = re.sub(rf"['\"]{esc_b}['\"]|\b{esc_b}\b", hold, text, flags=re.I)

    cleaned = text
    for pat, rep in GENERAL_REPLACEMENTS:
        cleaned = pat.sub(rep, cleaned)
    if not bypass_copyright:
        for pat, rep in COPYRIGHT_REPLACEMENTS:
            cleaned = pat.sub(rep, cleaned)
    for tok, orig in reversed(preserved):
        cleaned = cleaned.replace(tok, orig)
    return re.sub(r"\s+", " ", cleaned).strip()


def inject_clothing_brand(desc: str, brand_desc: str,
                          placement: str = "chest_center") -> str:
    """Inyecta ropa fija + logotipo institucional en el sujeto del prompt.

    Si el sujeto ya lleva una prenda ("wearing a jacket"), el logo se ancla a
    esa prenda; si no, se añade una frase de vestuario completa. Coherencia de
    vestuario entre escenas = identidad de marca sin romper el prompt.
    """
    if not desc or not brand_desc or brand_desc.lower() in desc.lower():
        return desc
    placement_map = {
        "chest_center": f"featuring a design of {brand_desc} on the center of the chest",
        "chest_left": (f"featuring a small institutional logo of {brand_desc} "
                       "on the left side of the chest"),
    }
    phrase = placement_map.get(placement, placement_map["chest_center"])
    pat = re.compile(
        r"(?i)\b(wearing|in)\s+([^,.;]+?\b(?:shirt|t-shirt|tee|jacket|suit|coat|"
        r"hoodie|jersey|polo|sweater|vest|clothing)\b)", re.I)
    m = pat.search(desc)
    if m:
        end = m.end(2)
        return desc[:end] + f" {phrase}" + desc[end:]
    return f"{desc.rstrip(' .')}, wearing clothing {phrase}."


def enrich_realistic_prompt(image_prompt: dict, video_prompt: dict | None = None) -> None:
    """Física óptica + motor de render en prompts FOTORREALISTAS (in-place).

    - Estilo sketch/cartoon/anime → NO se toca (la cámara solo pertenece al realismo).
    - Sin estilo declarado → se asume realista (comportamiento del modo Auto).
    - Idempotente: no duplica si ya menciona la cámara/luz/motor.
    """
    if not isinstance(image_prompt, dict):
        return
    style_text = (image_prompt.get("style") or "").lower()
    if any(k in style_text for k in _SKETCH_KWS):
        return
    is_realistic = any(k in style_text for k in _REALISM_KWS) or not style_text
    if not is_realistic:
        return

    current_light = image_prompt.get("lighting", "")
    if current_light and not any(k in current_light.lower() for k in
                                 ("studio", "volumetric", "ray tracing")):
        image_prompt["lighting"] = (current_light.rstrip(" .") +
                                    ", volumetric lighting, professional studio "
                                    "light setup, ray tracing shadows")

    current_comp = image_prompt.get("composition", "")
    if current_comp and not any(k in current_comp.lower() for k in
                                ("sony", "lens", "f/1.8")):
        image_prompt["composition"] = (current_comp.rstrip(" .") +
                                       ", shot on Sony A7R IV, 85mm f/1.8 lens, "
                                       "cinematic depth of field, RAW look")

    if style_text and not any(k in style_text for k in ("unreal", "octane")):
        image_prompt["style"] = (image_prompt["style"].rstrip(" .") +
                                 ", 8k resolution, ultra-detailed, "
                                 "Unreal Engine 5 renders, Octane Render style, "
                                 "sharp textures")

    if video_prompt and isinstance(video_prompt, dict):
        cam = video_prompt.get("camera_movement", "")
        if cam and not any(k in cam.lower() for k in ("slow", "cinematic")):
            video_prompt["camera_movement"] = f"Slow cinematic {cam.lower()}"


def sanitize_script_scenes(scenes: list[dict], brand_name: str | None = None,
                           allow_brand_text: bool = False,
                           clothing_brand: str | None = None) -> list[dict]:
    """Sanitiza las escenas de un guion recién generado (in-place + retorno).

    - image_prompt STRING (nuestro modelo de escenas): se limpia y, si el
      resultado es realista, se enriquece con física óptica en línea.
    - image_prompt DICT (formato estructurado del export Flow): se limpia
      campo a campo y se enriquece con enrich_realistic_prompt().
    - clothing_brand: identidad de vestuario inyectada en cada sujeto.
    """
    for sc in scenes:
        ip = sc.get("image_prompt")
        if isinstance(ip, str):
            cleaned = sanitize_text(ip, brand_name, allow_brand_text)
            low = cleaned.lower()
            if not any(k in low for k in _SKETCH_KWS):
                if "sony" not in low:
                    extra = ", shot on Sony A7R IV, 85mm f/1.8 lens"
                    if "volumetric" not in low:
                        extra += ", volumetric lighting"
                    cleaned += extra + ", Unreal Engine 5 render, 8k"
            if clothing_brand:
                cleaned = inject_clothing_brand(cleaned, clothing_brand)
            sc["image_prompt"] = cleaned
        elif isinstance(ip, dict):
            enrich_realistic_prompt(ip, sc.get("video_prompt"))
            for field in ("composition", "lighting", "environment", "style"):
                if field in ip and isinstance(ip[field], str):
                    ip[field] = sanitize_text(ip[field], brand_name,
                                              allow_brand_text)
            if clothing_brand:
                subj = ip.get("subjects")
                if isinstance(subj, list) and subj and isinstance(subj[0], str):
                    subj[0] = inject_clothing_brand(subj[0], clothing_brand)
    return scenes
