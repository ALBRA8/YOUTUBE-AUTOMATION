"""
YOUTUBE AUTOMATION v2.0 — Paso 1: Guion + prompts de imagen (Gemini)
Modos: script (texto dado), idea (semilla), url (transcripción viral originalizada),
audio (transcripción de voz propia ya insertada en meta).
Genera JSON estructurado: título, hook, escenas con narration + image_prompt, cta.
"""
import logging

from services import gemini_client
from services import avatar_schema
from services import originality
from services.themes import get_style, NEUTRAL_STYLE_PROMPT

log = logging.getLogger("script")

# ─────────────────────────── generador local (fallback $0) ────────────────
# Sin API key (o si Gemini falla) producimos un guion estructurado local:
# el pipeline completa de verdad con edge-tts + imágenes locales. Coste $0.

_HOOKS = [
    "¿Crees que ya lo sabes todo sobre {tema}? Espera a escuchar esto.",
    "Esto de {tema} casi nadie lo sabe… y te va a sorprender.",
    "Para de hacer scroll: {tema} es mucho más loco de lo que creías.",
]
_CUERPO = [
    "Empecemos por lo básico: {tema} guarda detalles que la ciencia apenas empieza a entender.",
    "Los expertos llevan años estudiando {tema}, y cada descubrimiento contradice al anterior.",
    "Aquí viene lo increíble: detrás de {tema} hay historias que parecen inventadas.",
    "Y no, no es ciencia ficción: todo esto está documentado sobre {tema}.",
    "Piénsalo: cada detalle de {tema} esconde una pieza que cambia el tablero completo.",
    "Lo mejor de {tema} es que cuanto más profundizas, más preguntas aparecen.",
    "Hay un dato sobre {tema} que dejó a toda la comunidad con la boca abierta.",
    "Y si eso te pareció poco, espera a lo que viene ahora con {tema}.",
    "La pregunta que todos hacen: ¿hasta dónde puede llegar {tema}?",
]
_GIRO = "Y ahora, el dato que lo cambia todo: lo que descubrieron sobre {tema} supera cualquier predicción."
_CTA = "Si quieres más secretos sobre {tema}, sígueme: cada día desvelamos algo nuevo."
_SHOTS = [
    "dramatic close-up shot, volumetric lighting, ultra detailed",
    "epic wide establishing shot, cinematic composition, golden hour",
    "dynamic action shot from below, high contrast, moody atmosphere",
    "macro detail shot, shallow depth of field, cinematic color grading",
    "aerial drone shot, vast landscape, dramatic clouds, cinematic",
    "over-the-shoulder shot, mysterious silhouettes, rim lighting",
]


def _tema(seed: str) -> str:
    t = (seed or "este tema").strip().rstrip(".!?¿¡")
    return t if len(t) <= 60 else t[:57] + "…"


def _split_sentences(text: str) -> list[str]:
    import re
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) >= 25]


def _local_fallback(kind: str, seed: str, style_id: str, fmt: str,
                    custom_prompt: str | None = None,
                    source_text: str = "") -> dict:
    """Guion estructurado sin IA externa: hook → cuerpo → giro → CTA.
    En modo url/script/audio extrae keywords REALES de la transcripción
    para que el guion tenga sustancia y no solo frases plantilla."""
    style = get_style(style_id)
    # "auto" (prompt vacío) → descriptor neutro: coherencia sin estética impuesta
    style_prompt = custom_prompt or style["prompt"] or NEUTRAL_STYLE_PROMPT
    tema = _tema(seed)
    body_src = _split_sentences(seed) if kind in ("script", "audio") else []
    n_body = 4 if fmt == "short" else 10

    # keywords del material de origen (transcripción viral) para dar contexto
    kws = originality.keywords(source_text or seed, k=6)
    ctx = (" sobre " + ", ".join(kws[:3])) if kws else ""

    narrations: list[str] = [_HOOKS[0].format(tema=tema)]
    for i in range(n_body):
        if i < len(body_src):
            narrations.append(body_src[i])
        else:
            base = _CUERPO[i % len(_CUERPO)].format(tema=tema)
            narrations.append(base)
    narrations.append(_GIRO.format(tema=tema + ctx))
    narrations.append(_CTA.format(tema=tema))

    titles = ["El Hook"] + [f"Pista {i}" for i in range(1, len(narrations) - 2)] + [
        "El Giro", "Tu CTA"]
    scenes = []
    for i, nar in enumerate(narrations):
        shot = _SHOTS[i % len(_SHOTS)]
        kw_shot = f", {kws[i % len(kws)]} concept" if kws else ""
        scenes.append({
            "title": titles[i] if i < len(titles) else f"Escena {i + 1}",
            "narration": nar,
            "image_prompt": f"{shot}{kw_shot}, visual concept about {tema}, {style_prompt}, no text",
        })
    return {
        "title": _smart_title(tema),
        "hook": narrations[0],
        "cta": narrations[-1],
        "scenes": scenes,
        "engine": "local-demo",
    }


def _smart_title(tema: str) -> str:
    """Capitaliza el título del proyecto respetando mayúsculas propias del usuario.

    Reglas: si el usuario escribió todo en minúsculas, capitaliza la 1ª letra.
    Si ya incluye mayúsculas (Imperio, Romano, Marvel…), las respeta tal cual.
    """
    t = (tema or "").strip()[:60]
    if not t:
        return "Sin título"
    has_upper = any(c.isupper() for c in t[1:])
    return t if has_upper else t[:1].upper() + t[1:]

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
                       custom_prompt: str | None = None,
                       avatar: dict | None = None) -> str:
    dur = "30-50 segundos" if fmt == "short" else "2-4 minutos"
    effective = (custom_prompt or style_prompt or "").strip()
    if effective:
        style_line = (f"Estilo visual de las imágenes: {effective}. "
                      "Aplica esta MISMA estética en todos los image_prompt.")
    else:
        # estilo "auto": el usuario no elige nada — la IA decide UNA estética
        # coherente apropiada al tema y la mantiene en TODAS las escenas.
        style_line = ("Estética visual: elige tú UNA estética coherente y apropiada "
                      "para el tema del video, y aplícala de forma CONSISTENTE en TODOS "
                      "los image_prompt (misma técnica, paleta de color e iluminación "
                      "en todas las escenas).")
    avatar_line = avatar_schema.persona_text(avatar) if avatar else ""
    return (
        f"Genera un guion de video de {dur} dividido en EXACTAMENTE {n_scenes} escenas. "
        f"{style_line} {avatar_line} "
        "Cada escena: título corto (3-5 palabras), narration (1-3 frases potentes "
        "para locución, máximo 40 palabras) e image_prompt EN INGLÉS describiendo la "
        "imagen cinematográfica de esa escena (sin texto/letras en la imagen). "
        "Mantén coherencia visual entre escenas."
    )


async def from_script(script_text: str, style_id: str, fmt: str,
                      custom_prompt: str | None = None,
                      avatar: dict | None = None) -> dict:
    if not gemini_client.available():
        return _local_fallback("script", script_text, style_id, fmt, custom_prompt)
    try:
        style = get_style(style_id)
        n = 6 if fmt == "short" else 12
        prompt = (
            "Convierte el siguiente guion en un guion escena por escena para video viral. "
            + _base_instructions(style["prompt"], n, fmt, custom_prompt, avatar)
            + f"\n\nGUION:\n{script_text[:8000]}"
        )
        return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                                 system=SYSTEM)
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini falló (%s) — uso generador local", str(e)[:120])
        return _local_fallback("script", script_text, style_id, fmt, custom_prompt)


async def from_idea(idea: str, style_id: str, fmt: str,
                    custom_prompt: str | None = None,
                    avatar: dict | None = None) -> dict:
    if not gemini_client.available():
        return _local_fallback("idea", idea, style_id, fmt, custom_prompt)
    try:
        style = get_style(style_id)
        n = 6 if fmt == "short" else 12
        prompt = (
            f"Crea desde cero un guion viral a partir de esta idea: «{idea}». "
            + _base_instructions(style["prompt"], n, fmt, custom_prompt, avatar)
        )
        return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                                 system=SYSTEM)
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini falló (%s) — uso generador local", str(e)[:120])
        return _local_fallback("idea", idea, style_id, fmt, custom_prompt)


def _narration_text(result: dict) -> str:
    """Todo el texto hablado del guion generado (para medir originalidad)."""
    parts = [result.get("title", ""), result.get("hook", ""),
             result.get("cta", "")]
    parts += [sc.get("narration", "") for sc in result.get("scenes", [])]
    return " ".join(p for p in parts if p)


async def from_url_transcript(viral_meta: dict, transcript: str, style_id: str,
                              fmt: str, custom_prompt: str | None = None,
                              avatar: dict | None = None) -> dict:
    """Killer feature: recrear la ESTRUCTURA ganadora del viral con contenido
    original — "similar pero NO igual", y AHORA VERIFICABLE: se mide el
    solape de 5-gramas del guion contra la transcripción y, si supera el
    umbral (18%), se relanza UNA vez con instrucción anti-copia dura."""
    seed = viral_meta.get("title") or transcript[:120]
    if not gemini_client.available():
        return _local_fallback("url", seed, style_id, fmt, custom_prompt,
                               source_text=transcript)

    def _prompt(hard: bool) -> str:
        anti = (
            "\nPROHIBIDO COPIAR: no uses NINGUNA secuencia de 4+ palabras "
            "consecutivas del original. Cambia el áNGULO, no solo las palabras: "
            "otro protagonista o perspectiva, otro orden de los datos, otra "
            "anécdota o ejemplo distinto, tu propio giro. Puedes conservar el "
            "TEMA y el esquema hook→tensión→giro→CTA, nada más."
            if hard else
            "No reutilices frases del original."
        )
        return (
            "El siguiente texto es la transcripción de un video viral. Analiza su "
            "estructura ganadora (hook, desarrollo, giro, CTA) y crea un guion 100% ORIGINAL "
            "sobre el mismo tema con nuevo ángulo y nuevas frases. " + anti +
            f" Título del video viral: «{viral_meta.get('title', '')}» "
            f"(canal {viral_meta.get('channel', '')}). "
            + _base_instructions(get_style(style_id)["prompt"], n, fmt,
                                 custom_prompt, avatar)
            + f"\n\nTRANSCRIPCIÓN (solo referencia de estructura):\n{transcript[:9000]}"
        )

    style = get_style(style_id)
    n = 6 if fmt == "short" else 12
    try:
        raw = await gemini_client.generate_json(_prompt(False),
                                                gemini_client.schema_scenes(),
                                                system=SYSTEM)
        result = build_result(raw)
        report = originality.originality_report(transcript, _narration_text(result))
        if report["too_similar"]:
            log.warning("guion demasiado similar (overlap=%.0f%%, run=%d) — "
                        "relanzando con anti-copia dura",
                        report["overlap"] * 100, report["longest_run"])
            raw2 = await gemini_client.generate_json(_prompt(True),
                                                     gemini_client.schema_scenes(),
                                                     system=SYSTEM)
            result2 = build_result(raw2)
            report2 = originality.originality_report(
                transcript, _narration_text(result2))
            if report2["overlap"] <= report["overlap"]:
                result, report = result2, {**report2, "retried": True}
            else:
                report["retried"] = True  # el 2º intento no mejoró: se conserva el 1º
        result["originality"] = report
        return result
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini falló (%s) — uso generador local", str(e)[:120])
        return _local_fallback("url", seed, style_id, fmt, custom_prompt,
                               source_text=transcript)


async def from_audio_transcript(transcript: str, style_id: str, fmt: str,
                                custom_prompt: str | None = None,
                                avatar: dict | None = None) -> dict:
    """El usuario grabó su voz (modo Audio): pulimos y estructuramos su narración."""
    if not gemini_client.available():
        return _local_fallback("audio", transcript, style_id, fmt, custom_prompt)
    try:
        style = get_style(style_id)
        n = 6 if fmt == "short" else 12
        prompt = (
            "La siguiente transcripción es la narración hablada por el propio creador. "
            "Respeta su contenido y estilo personal: solo divídela en escenas y genera los "
            "prompts visuales. NO cambies sus frases salvo errores evidentes. "
            + _base_instructions(style["prompt"], n, fmt, custom_prompt, avatar)
            + f"\n\nTRANSCRIPCIÓN:\n{transcript[:8000]}"
        )
        return await gemini_client.generate_json(prompt, gemini_client.schema_scenes(),
                                                 system=SYSTEM)
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini falló (%s) — uso generador local", str(e)[:120])
        return _local_fallback("audio", transcript, style_id, fmt, custom_prompt)


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
        "engine": raw.get("engine") or "gemini",
    }
