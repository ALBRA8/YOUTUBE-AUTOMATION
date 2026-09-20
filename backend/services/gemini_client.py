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

from config import (GEMINI_API_KEY, GEMINI_IMAGE_MODEL, GEMINI_TEXT_MODEL,
                    GEMINI_TTS_MODEL, GEMINI_TTS_VOICE)

log = logging.getLogger("gemini")

_client = None


def available() -> bool:
    return bool(GEMINI_API_KEY)


def client():
    global _client
    if _client is None:
        from google import genai  # import perezoso
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


async def _retry(coro_factory, tries: int = 3, base: float = 2.0):
    for attempt in range(tries):
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            wait = base ** attempt
            log.warning("Gemini intento %d falló (%s). Reintento en %.0fs", attempt + 1, e, wait)
            await asyncio.sleep(wait)


# ─────────────────────────────────────────────────────────────── TEXTO ──
async def generate_json(prompt: str, schema: dict | None = None,
                        system: str | None = None) -> Any:
    """Genera contenido estructurado JSON. Lanza si no hay key."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

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
            model=GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg),
        )

    def _parse():
        txt = resp.text
        return json.loads(txt)

    resp = await _retry(lambda: asyncio.to_thread(_call))
    return await asyncio.to_thread(_parse)


async def generate_text(prompt: str, system: str | None = None) -> str:
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    def _call():
        from google.genai import types
        cfg = {"temperature": 0.9}
        if system:
            cfg["system_instruction"] = system
        return client().models.generate_content(
            model=GEMINI_TEXT_MODEL, contents=prompt,
            config=types.GenerateContentConfig(**cfg))

    resp = await _retry(lambda: asyncio.to_thread(_call))
    return resp.text


# ────────────────────────────────────────────────────────────── IMAGEN ──
async def generate_image(prompt: str) -> bytes:
    """Genera una imagen con Gemini 2.5 Flash Image (nano-banana).
    Devuelve los bytes PNG/JPG de la imagen."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    def _call():
        from google.genai import types
        return client().models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )

    resp = await _retry(lambda: asyncio.to_thread(_call))
    cand = resp.candidates[0]
    for part in cand.content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("Gemini no devolvió imagen (posible bloqueo de seguridad)")


# ───────────────────────────────────────────────────────────────── TTS ──
async def tts_pcm(text: str, voice: str = GEMINI_TTS_VOICE) -> bytes:
    """TTS de Gemini → WAV (PCM s16le 24kHz mono)."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY no configurada")

    def _call():
        from google.genai import types
        return client().models.generate_content(
            model=GEMINI_TTS_MODEL,
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
    """Esquema para guiones escena por escena."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "hook": {"type": "string"},
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


def b64_image(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()
