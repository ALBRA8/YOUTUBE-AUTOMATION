"""
YOUTUBE AUTOMATION v2.0 — Paso 1: Guion + prompts de imagen (Gemini)
Modos: script (texto dado), idea (semilla), url (transcripción viral originalizada),
audio (transcripción de voz propia ya insertada en meta).
Genera JSON estructurado: título, hook, escenas con narration + image_prompt, cta.
"""
import logging

from services import gemini_client
from services.themes import get_style

log = logging.getLogger("script")

SYSTEM = (
    "Eres un guionista viral de YouTube Shorts/TikTok con millones de vistas. "
    "Escribes en español neutro, ritmo trepidante, frases cortas que enganchan. "
    "Estructura: HOOK brutal en los primeros 3 segundos, cuerpo con tensión "
    "creciente, giro inesperado y CTA final. Nunca copias contenido de terceros: "
    "si te dan una transcripción de referencia, creas una versión ORIGINAL y mejorada "
    "con nuevo ángulo. Los prompts de imagen los escribes EN INGLÉS, muy descriptivos, "
    "consistentes entre escenas (mismos personajes/ambiente), sin texto en la imagen."
)


def _base_instructions(style_prompt: str, n_scenes: int, fmt: str,
                       custom_prompt: str | None = None) -> str:
    dur = "30-50 segundos" if fmt == "short" else "2-4 minutos"
    style_line = (f"Estilo visual de las imágenes: {custom_prompt or style_prompt}.")
    return (
        f"Genera un guion de video de {dur} dividido en EXACTAMENTE {n_scenes} escenas. "
        f"{style_line} "
        "Cada escena: título corto (3-5 palabras), narration (1-3 frases potentes "
        "para locución, máximo 40 palabras) e image_prompt EN INGLÉS describiendo la "
        "imagen cinematográfica de esa escena (sin texto/letras en la imagen). "
        "Mantén coherencia visual entre escenas."
    )


async def from_script(script_text: str, style_id: str, fmt: str,
                      custom_prompt: str | None = None) -> dict:
    style = get_style(style_id)
    n = 6 if fmt == "short" else 12
    prompt = (
        "Convierte el siguiente guion en un guion escena por escena para video viral. "
        + _base_instructions(style["prompt"], n, fmt, custom_prompt)
        + f"\n\nGUION:\n{script_text[:8000]}"
    )
    return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                             system=SYSTEM)


async def from_idea(idea: str, style_id: str, fmt: str,
                    custom_prompt: str | None = None) -> dict:
    style = get_style(style_id)
    n = 6 if fmt == "short" else 12
    prompt = (
        f"Crea desde cero un guion viral a partir de esta idea: «{idea}». "
        + _base_instructions(style["prompt"], n, fmt, custom_prompt)
    )
    return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                             system=SYSTEM)


async def from_url_transcript(viral_meta: dict, transcript: str, style_id: str,
                              fmt: str, custom_prompt: str | None = None) -> dict:
    """Killer feature: recrear la ESTRUCTURA ganadora del viral con contenido original."""
    style = get_style(style_id)
    n = 6 if fmt == "short" else 12
    prompt = (
        "El siguiente texto es la transcripción de un video viral. Analiza su "
        "estructura ganadora (hook, desarrollo, giro, CTA) y crea un guion 100% ORIGINAL "
        "sobre el mismo tema con nuevo ángulo y nuevas frases. No reutilices frases del "
        "original. Título del video viral: "
        f"«{viral_meta.get('title', '')}» (canal {viral_meta.get('channel', '')}). "
        + _base_instructions(style["prompt"], n, fmt, custom_prompt)
        + f"\n\nTRANSCRIPCIÓN (solo referencia de estructura):\n{transcript[:9000]}"
    )
    return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                             system=SYSTEM)


async def from_audio_transcript(transcript: str, style_id: str, fmt: str,
                                custom_prompt: str | None = None) -> dict:
    """El usuario grabó su voz (modo Audio): pulimos y estructuramos su narración."""
    style = get_style(style_id)
    n = 6 if fmt == "short" else 12
    prompt = (
        "La siguiente transcripción es la narración hablada por el propio creador. "
        "Respeta su contenido y estilo personal: solo divídela en escenas y genera los "
        "prompts visuales. NO cambies sus frases salvo errores evidentes. "
        + _base_instructions(style["prompt"], n, fmt, custom_prompt)
        + f"\n\nTRANSCRIPCIÓN:\n{transcript[:8000]}"
    )
    return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                             system=SYSTEM)


def build_result(raw: dict) -> dict:
    """Normaliza la salida del LLM a nuestro modelo de escenas."""
    scenes = []
    for i, sc in enumerate(raw.get("scenes", [])):
        scenes.append({
            "title": (sc.get("title") or f"Escena {i + 1}").strip()[:80],
            "narration": (sc.get("narration") or "").strip(),
            "image_prompt": (sc.get("image_prompt") or "").strip(),
        })
    return {
        "title": (raw.get("title") or "Sin título").strip()[:60],
        "hook": (raw.get("hook") or "").strip(),
        "cta": (raw.get("cta") or "").strip(),
        "scenes": scenes,
    }
