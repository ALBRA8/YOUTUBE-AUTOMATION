"""
Flow Export — Puente entre YOUTUBE AUTOMATION v2 y la extensión "Flow Script Processor".

Genera el paquete exacto que la extensión del usuario consume:
  <SLUG>/out/ideas/idea_NNNNNN/script.json   → ScriptData (ImagePrompt + VideoPrompt por escena)
  <SLUG>/out/ideas/idea_NNNNNN/prompts_maestro.txt → documento de pasos estilo "PRIMITIVE VIRAL"
  <SLUG>/out/ideas/idea_NNNNNN/guion.txt     → narración completa (referencia / TTS externo)
  README.txt                                 → instrucciones de uso

El JSON respeta el contrato definido en el manual de la extensión (utils/types.ts):
  - ImagePrompt:  subjects[], environment, lighting, composition, style
  - VideoPrompt:  motion, camera_movement
  - parser.ts lo convierte en texto plano para Imagen 3 / Veo dentro de Google Flow.

La estructura de carpetas replica el formato del buscador recursivo findScriptJson()
de la extensión: out/ideas/idea_(\\d+)/ → toma el número MÁS ALTO automáticamente.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from services.themes import get_style

# --------------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convierte un título en slug tipo carpeta de proyecto: 'Retos Acuaticos' -> RETOS_ACUATICOS."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper()
    return t[:48] or "PROYECTO"


_LIGHT_KEYS = ("light", "luz", "ilumin", "golden hour", "chiaroscuro", "sombra", "shadow",
               "backlight", "volumetric", "neon", "sunset", "sunrise", "daylight", "glow")
_SHOT_KEYS = ("shot", "close-up", "closeup", "wide", "portrait", "angle", "zoom", "plano",
              "macro", "aerial", "establishing", "pov", "drone", "tracking", "overhead")
_ENV_KEYS = ("environment", "entorno", "concept about", "background", "fondo", "escenario",
             "setting", "escena de", "interior", "exterior")


def _split_prompt(flat: str) -> dict:
    """Descompone el image_prompt plano (texto con comas) en campos estructurados heurísticos."""
    segs = [s.strip() for s in (flat or "").split(",") if s.strip()]
    lighting, environment, composition, rest = [], [], [], []
    for i, s in enumerate(segs):
        low = s.lower()
        if any(k in low for k in _LIGHT_KEYS):
            lighting.append(s)
        elif any(k in low for k in _ENV_KEYS):
            environment.append(s)
        elif i == 0 or any(k in low for k in _SHOT_KEYS):
            composition.append(s)
        else:
            rest.append(s)
    return {
        "composition": composition or ["cinematic shot"],
        "lighting": lighting or ["natural cinematic lighting"],
        "environment": environment or [],
        "style": rest,
    }


_CAM_MOVE_MAP = [
    (("close-up", "closeup", "macro", "primer plano"), "slow cinematic push-in"),
    (("wide", "establishing", "aerial", "drone"), "slow aerial pull-back revealing the scene"),
    (("overhead", "top"), "smooth overhead descent"),
    (("tracking", "pov", "seguimiento"), "dynamic tracking shot following the subject"),
]
_DEFAULT_CAM = "slow cinematic pan with subtle depth"


def _cam_move(composition: str) -> str:
    low = (composition or "").lower()
    for keys, move in _CAM_MOVE_MAP:
        if any(k in low for k in keys):
            return move
    return _DEFAULT_CAM


def _first_sentence(text: str, maxlen: int = 160) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    m = re.match(r"(.+?[.!?¡¿])(\s|$)", t)
    s = (m.group(1) if m else t).strip()
    return s[:maxlen].rsplit(" ", 1)[0] + "…" if len(s) > maxlen else s


_NEGATIVE_BASE = ("cartoon, anime, illustration, CGI, 3D render, plastic, foam armor, fabric suit, "
                  "metal, paint, glossy varnish, fantasy art, neon glow, magical effects, text overlay, "
                  "watermark, blur, low detail, distorted anatomy, extra limbs, bad hands")

# --------------------------------------------------------------------------------------
# Construcción de ScriptData (contrato de la extensión)
# --------------------------------------------------------------------------------------

def build_script_json(project: dict, scenes: list[dict]) -> dict:
    """Arma el ScriptData exacto que parser.ts de la extensión espera encontrar en script.json."""
    style_id = project.get("style") or "graphic-novel"
    st = get_style(style_id)

    scenes_out = []
    for i, sc in enumerate(scenes, start=1):
        parts = _split_prompt(sc.get("image_prompt") or "")
        narration = sc.get("narration") or ""
        title = sc.get("title") or f"Escena {i}"
        comp = ". ".join(parts["composition"])
        style_txt = ", ".join(parts["style"]) or st.get("prompt", "")
        env_txt = ", ".join(parts["environment"]) or f"cinematic environment inspired by: {project.get('title', '')}"
        light_txt = ", ".join(parts["lighting"])

        scenes_out.append({
            "scene_number": i,
            "title": title,
            "narration": narration,
            "duration": sc.get("duration") or 5,
            "image_prompt": {
                "subjects": [
                    f"{title} — {_first_sentence(narration) or 'main subject of the scene'}",
                ],
                "environment": env_txt,
                "lighting": light_txt,
                "composition": f"{comp}, vertical 9:16 framing",
                "style": f"{style_txt}, hyper-realistic cinematic quality, 8K",
            },
            "video_prompt": {
                "motion": _first_sentence(narration, 120) or f"{title}: main visual action",
                "camera_movement": _cam_move(comp),
            },
        })

    return {
        "project_name": slugify(project.get("title") or "PROYECTO"),
        "title": project.get("title") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": project.get("format") or "short",
        "style": {"id": st.get("id"), "name": st.get("name"), "prompt": st.get("prompt")},
        "scenes": scenes_out,
    }


# --------------------------------------------------------------------------------------
# Documento de prompts maestro (formato humano estilo PRIMITIVE VIRAL)
# --------------------------------------------------------------------------------------

def build_prompts_maestro(project: dict, scenes: list[dict]) -> str:
    st = get_style(project.get("style") or "graphic-novel")
    slug = slugify(project.get("title") or "PROYECTO")
    sep = "-" * 100
    lines = [
        f"{project.get('title') or slug} — {st.get('name', '').upper()} (FORMATO VERTICAL 9:16)",
        "",
        "REGLA ABSOLUTA DE ESTILO (NO NEGOCIABLE)",
        f"- {st.get('prompt', '')}",
        f"- {st.get('desc', '')}",
        "",
        "NOTA DE USO",
        "- Cada PASO es un prompt listo para pegar en Google Flow (ImageFX / Veo).",
        "- Mantén la coherencia del personaje usando siempre la primera imagen generada como referencia.",
        "",
        sep,
    ]
    for sc in build_script_json(project, scenes)["scenes"]:
        ip, vp = sc["image_prompt"], sc["video_prompt"]
        lines += [
            f"PASO {sc['scene_number']} — {sc['title'].upper()}",
            "",
            " ".join(ip["subjects"]),
            f"Environment: {ip['environment']}",
            f"Lighting: {ip['lighting']}",
            f"Composition: {ip['composition']}",
            f"Style: {ip['style']}",
            f"Motion: {vp['motion']} Camera: {vp['camera_movement']}.",
            "",
            "🎥 CAMERA",
            ip["composition"],
            "",
            "🚫 NEGATIVE PROMPT",
            _NEGATIVE_BASE,
            "",
            sep,
        ]
    return "\n".join(lines)


def build_guion(project: dict, scenes: list[dict]) -> str:
    lines = [f"GUION — {project.get('title', '')}", ""]
    for sc in scenes:
        lines += [f"[Escena {sc['idx'] + 1}] {sc.get('title', '')}", sc.get("narration", ""), ""]
    return "\n".join(lines)


def build_readme() -> str:
    return """FLOW EXPORT — YOUTUBE AUTOMATION v2
====================================
Cómo usar este paquete con la extensión Flow Script Processor:

1. Descomprime este ZIP en tu disco (ej: d:\\PROYECTOS\\YOUTUBE AUTOMATION\\projects\\).
   Obtendrás la carpeta <PROYECTO>/out/ideas/idea_000001/script.json
2. Abre Google Labs (Flow / ImageFX) en Chrome.
3. Extension "Flow Script Processor" → "Vincular Proyecto" → selecciona la carpeta <PROYECTO>.
   La extensión autodetecta el script.json más reciente (idea_000001) y lista las escenas.
4. Elige Imágenes (PNG) o Videos (MP4/WebM) y presiona "Iniciar Generación".
5. Los archivos quedan en <PROYECTO>/Escena_XX/imagen_1.png | video_1.mp4

Contenido:
- script.json          → escenas estructuradas (contrato ImagePrompt/VideoPrompt)
- prompts_maestro.txt  → documento de pasos para uso manual en Flow o re-edición con ChatGPT
- guion.txt            → narración completa (voz en off / referencia)

Nota: si ya habías exportado antes y no quieres sobrescribir, renombra idea_000001
por el siguiente número libre (idea_000002, ...) — la extensión siempre toma el mayor.
"""


# --------------------------------------------------------------------------------------
# Empaquetado ZIP
# --------------------------------------------------------------------------------------

def export_zip_bytes(project: dict, scenes: list[dict], idea_number: int = 1) -> tuple[bytes, str]:
    """Devuelve (zip_bytes, slug). Estructura: <SLUG>/out/ideas/idea_NNNNNN/..."""
    slug = slugify(project.get("title") or "PROYECTO")
    script = build_script_json(project, scenes)
    idea_dir = f"{slug}/out/ideas/idea_{idea_number:06d}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{idea_dir}/script.json",
                   json.dumps(script, ensure_ascii=False, indent=2))
        z.writestr(f"{idea_dir}/prompts_maestro.txt",
                   build_prompts_maestro(project, scenes))
        z.writestr(f"{idea_dir}/guion.txt",
                   build_guion(project, scenes))
        z.writestr("README.txt", build_readme())
    return buf.getvalue(), slug
