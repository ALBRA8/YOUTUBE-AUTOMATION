"""
YOUTUBE AUTOMATION v2.0 — Cliente Gemini unificado
Texto (gemini-2.5-flash), Imagen (gemini-2.5-flash-image) y TTS.
Todas las llamadas con reintento exponencial y degradación graceful:
si no hay API key, el resto del sistema sigue funcionando en modo demo.
"""
import asyncio
import base64
import io
import json
import logging
import wave
from typing import Any

import config

log = logging.getLogger("gemini")

_client = None
_client_key = None
_remembered_text_model: str | None = None


def get_active_text_model() -> str:
    """Devuelve el modelo de texto activo o recordado en el proceso."""
    global _remembered_text_model
    if _remembered_text_model:
        return _remembered_text_model
    return getattr(config, "GEMINI_TEXT_MODEL", "gemini-3.8-flash")


def set_remembered_text_model(model: str | None) -> None:
    """Fija manualmente el modelo recordado (útil para tests)."""
    global _remembered_text_model
    _remembered_text_model = model


def _get_text_model_candidates(model: str | None = None) -> list[str]:
    """Genera la lista ordenada y desduplicada de candidatos de modelo de texto."""
    if model:
        return [model]
    candidates: list[str] = []
    primary = _remembered_text_model or getattr(config, "GEMINI_TEXT_MODEL", "gemini-3.8-flash")
    if primary:
        candidates.append(primary)
    fallbacks = getattr(config, "GEMINI_TEXT_MODEL_FALLBACKS", [])
    for fb in fallbacks:
        if fb and fb not in candidates:
            candidates.append(fb)
    return candidates or ["gemini-3.8-flash"]


def available() -> bool:
    return bool(config.GEMINI_API_KEY)


def client():
    global _client, _client_key
    key = config.GEMINI_API_KEY
    # Reconstruye el cliente si la clave cambió (p. ej. guardada desde el dashboard)
    if _client is None or _client_key != key:
        from google import genai  # import perezoso
        _client = genai.Client(api_key=key)
        _client_key = key
    return _client


async def _retry(coro_factory, tries: int = 3, base: float = 2.0,
                 timeout: float = 90.0):
    """Reintentos con backoff exponencial + TIMEOUT por intento (§reintentos:
    timeout explícito). Antes una llamada colgada de Gemini estancaba el paso
    del pipeline indefinidamente; ahora cada intento vence a `timeout` s y
    cuenta como fallo reintentable."""
    for attempt in range(tries):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            err_str = str(e).lower()
            is_not_found = (
                getattr(e, "code", None) == 404
                or getattr(e, "status_code", None) == 404
                or "404" in err_str
                or "not_found" in err_str
                or "no longer available" in err_str
            )
            if is_not_found or attempt == tries - 1:
                raise
            wait = base ** attempt
            log.warning("Gemini intento %d falló (%s). Reintento en %.0fs", attempt + 1, e, wait)
            await asyncio.sleep(wait)


# ─────────────────────────────────────────────────────────────── TEXTO ──
async def generate_json(prompt: str, schema: dict | None = None,
                        system: str | None = None, model: str | None = None) -> Any:
    """Genera contenido estructurado JSON. Lanza si no hay key.
    `model` sobreescribe GEMINI_TEXT_MODEL. Si falla con 404 NOT_FOUND,
    prueba la cadena de GEMINI_TEXT_MODEL_FALLBACKS y recuerda el primero que funcione."""
    global _remembered_text_model
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    candidates = _get_text_model_candidates(model)
    last_exc = None

    for cand in candidates:
        def _call():
            from google.genai import types
            cfg: dict[str, Any] = {
                "response_mime_type": "application/json",
                "temperature": 0.9,
            }
            if schema:
                cfg["response_schema"] = schema
            if system:
                cfg["system_instruction"] = system
            return client().models.generate_content(
                model=cand,
                contents=prompt,
                config=types.GenerateContentConfig(**cfg),
            )

        def _parse():
            txt = resp.text
            return json.loads(txt)

        try:
            resp = await _retry(lambda: asyncio.to_thread(_call))
            parsed = await asyncio.to_thread(_parse)
            if cand != _remembered_text_model:
                _remembered_text_model = cand
                log.info("[gemini_client] modelo de texto fijado a: %s", cand)
            return parsed
        except (Exception,) as e:  # noqa: BLE001
            last_exc = e
            err_str = str(e).lower()
            is_not_found = (
                getattr(e, "code", None) == 404
                or getattr(e, "status_code", None) == 404
                or "404" in err_str
                or "not_found" in err_str
                or "no longer available" in err_str
            )
            if is_not_found and cand != candidates[-1]:
                log.warning(
                    "[gemini_client] modelo '%s' no disponible (404/NOT_FOUND) — probando siguiente candidato...",
                    cand
                )
                continue
            raise

    if last_exc:
        raise last_exc


async def generate_text(prompt: str, system: str | None = None,
                        model: str | None = None) -> str:
    global _remembered_text_model
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    candidates = _get_text_model_candidates(model)
    last_exc = None

    for cand in candidates:
        def _call():
            from google.genai import types
            cfg = {"temperature": 0.9}
            if system:
                cfg["system_instruction"] = system
            return client().models.generate_content(
                model=cand, contents=prompt,
                config=types.GenerateContentConfig(**cfg))

        try:
            resp = await _retry(lambda: asyncio.to_thread(_call))
            if cand != _remembered_text_model:
                _remembered_text_model = cand
                log.info("[gemini_client] modelo de texto fijado a: %s", cand)
            return resp.text
        except (Exception,) as e:  # noqa: BLE001
            last_exc = e
            err_str = str(e).lower()
            is_not_found = (
                getattr(e, "code", None) == 404
                or getattr(e, "status_code", None) == 404
                or "404" in err_str
                or "not_found" in err_str
                or "no longer available" in err_str
            )
            if is_not_found and cand != candidates[-1]:
                log.warning(
                    "[gemini_client] modelo '%s' no disponible (404/NOT_FOUND) — probando siguiente candidato...",
                    cand
                )
                continue
            raise

    if last_exc:
        raise last_exc


# ────────────────────────────────────────────────────────────── IMAGEN ──
async def generate_image(prompt: str, ref_image: bytes | None = None) -> bytes:
    """Genera una imagen con Gemini 2.5 Flash Image (nano-banana).
    Devuelve los bytes PNG/JPG de la imagen.
    Con `ref_image` (bytes PNG/JPG) hace img2img: el modelo recibe la imagen
    de referencia + el prompt → hereda paleta, iluminación y técnica
    (consistencia visual entre escenas, patrón AI-Content-Automation-Engine)."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    def _call():
        from google.genai import types
        if ref_image:
            contents: Any = [
                types.Part.from_bytes(data=ref_image, mime_type="image/png"),
                prompt,
            ]
        else:
            contents = prompt
        return client().models.generate_content(
            model=config.GEMINI_IMAGE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )

    resp = await _retry(lambda: asyncio.to_thread(_call))
    cand = resp.candidates[0]
    for part in cand.content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("Gemini no devolvió imagen (posible bloqueo de seguridad)")


# ───────────────────────────────────────────────────────────────── TTS ──
async def tts_pcm(text: str, voice: str | None = None) -> bytes:
    """TTS de Gemini → WAV (PCM s16le 24kHz mono)."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")
    voice = voice or config.GEMINI_TTS_VOICE

    def _call():
        from google.genai import types
        return client().models.generate_content(
            model=config.GEMINI_TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
                    )
                ),
            ),
        )

    resp = await _retry(lambda: asyncio.to_thread(_call))
    pcm = resp.candidates[0].content.parts[0].inline_data.data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm)
    return buf.getvalue()


def pcm_to_wav_bytes(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ───────────────────────────────────────────────────── Utilidades JSON ──
def schema_scenes() -> dict:
    """Esquema para guiones escena por escena con soporte para variantes A/B de hook."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "hook": {"type": "string"},
            "hook_variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "label": {"type": "string"},
                        "hook": {"type": "string"},
                        "visual_cue": {"type": "string"},
                        "estimated_retention": {"type": "string"},
                    },
                    "required": ["id", "type", "label", "hook", "visual_cue"],
                },
            },
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "narration": {"type": "string"},
                        "image_prompt": {"type": "string"},
                    },
                    "required": ["title", "narration", "image_prompt"],
                },
            },
            "cta": {"type": "string"},
        },
        "required": ["title", "scenes"],
    }


def schema_viral_hooks() -> dict:
    """Esquema dedicado para el generador A/B de hooks virales (3 segundos de impacto)."""
    return {
        "type": "object",
        "properties": {
            "hooks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "label": {"type": "string"},
                        "hook": {"type": "string"},
                        "visual_cue": {"type": "string"},
                        "estimated_retention": {"type": "string"},
                    },
                    "required": ["id", "type", "label", "hook", "visual_cue", "estimated_retention"],
                },
            },
        },
        "required": ["hooks"],
    }


def b64_image(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()
