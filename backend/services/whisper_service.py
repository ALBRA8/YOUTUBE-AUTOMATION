"""
YOUTUBE AUTOMATION v2.0 — Alineación palabra a palabra (Whisper)
Si faster-whisper está instalado → timestamps reales por palabra.
Si no → estimación por densidad de palabras (suficiente para subtítulos
TikTok/Hormozi en la mayoría de los casos). Siempre devuelve una lista:
[{"word": "...", "start": 0.32, "end": 0.71}, ...]
"""
import asyncio
import logging
import re

import config

log = logging.getLogger("whisper")
_model = None
_model_lock = asyncio.Lock()

WPM = 165  # velocidad de habla estimada para el fallback


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


async def _get_model():
    global _model
    async with _model_lock:
        # Si el modelo pedido cambia (ajustes del dashboard), se recarga
        wanted = (config.WHISPER_MODEL, config.WHISPER_DEVICE)
        if _model is None or getattr(_model, "_yta_sig", None) != wanted:
            def _load():
                from faster_whisper import WhisperModel
                m = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                 compute_type="int8")
                m._yta_sig = wanted
                return m
            _model = await asyncio.to_thread(_load)
    return _model


async def transcribe_words(audio_path: str, language: str = "es") -> list[dict] | None:
    """Transcribe con timestamps por palabra. None si Whisper no está disponible."""
    if not available():
        log.info("faster-whisper no instalado → usando estimación temporal")
        return None
    model = await _get_model()

    def _run():
        segments, _info = model.transcribe(
            audio_path, language=language, word_timestamps=True, vad_filter=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                token = w.word.strip()
                if token:
                    words.append({"word": token, "start": round(w.start, 3),
                                  "end": round(w.end, 3)})
        return words

    return await asyncio.to_thread(_run)


def estimate_words(text: str, start: float = 0.0, duration: float | None = None) -> list[dict]:
    """Fallback: reparte los tiempos uniformemente según WPM."""
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return []
    total = duration if duration and duration > 0 else max(1.0, len(tokens) / WPM * 60)
    per = total / len(tokens)
    t = start
    out = []
    for tok in tokens:
        out.append({"word": tok, "start": round(t, 3), "end": round(t + per, 3)})
        t += per
    return out


async def align_scene(text: str, audio_path: str, known_duration: float) -> list[dict]:
    words = await transcribe_words(audio_path)
    if words:
        return words
    return estimate_words(text, 0.0, known_duration)
