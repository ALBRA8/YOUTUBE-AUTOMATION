"""
YOUTUBE AUTOMATION v2.0 — TTS dual
Primario:  Gemini TTS (voz premium, prosodia natural)
Fallback:  edge-tts (100% gratuito e ilimitado, voces neuronales)
Devuelve (ruta_wav, duración_segundos) siempre en WAV 24kHz mono.
"""
import asyncio
import logging
import struct
import subprocess
from pathlib import Path

import config
from services import gemini_client

log = logging.getLogger("tts")

SAMPLE_RATE = 24000


def _mp3_to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", str(SAMPLE_RATE),
         "-ac", "1", str(dst)],
        check=True, capture_output=True)


def wav_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


async def synth_gemini(text: str, out_path: Path, voice: str | None = None) -> float:
    wav_bytes = await gemini_client.tts_pcm(text, voice or config.GEMINI_TTS_VOICE)
    out_path.write_bytes(wav_bytes)
    return wav_duration(out_path)


async def synth_edge(text: str, out_path: Path,
                     voice: str | None = None, rate: str | None = None) -> float:
    import edge_tts
    voice = voice or config.EDGE_TTS_VOICE
    rate = rate or config.TTS_RATE
    mp3 = out_path.with_suffix(".mp3")
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(mp3))
    _mp3_to_wav(mp3, out_path)
    mp3.unlink(missing_ok=True)
    return wav_duration(out_path)


async def synthesize(text: str, out_path: Path, provider: str | None = None,
                     voice: str | None = None) -> tuple[Path, float]:
    """Sintetiza con el proveedor pedido; si falla, cae al otro automáticamente."""
    provider = (provider or config.TTS_PROVIDER).lower()
    voice = voice or (config.GEMINI_TTS_VOICE if provider == "gemini" else config.EDGE_TTS_VOICE)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    primary = synth_gemini if provider == "gemini" else synth_edge
    fallback = synth_edge if provider == "gemini" else synth_gemini
    fb_voice = config.EDGE_TTS_VOICE if provider == "gemini" else config.GEMINI_TTS_VOICE

    try:
        dur = await primary(text, out_path, voice)
        used = provider
    except Exception as e:  # noqa: BLE001
        log.warning("TTS primario '%s' falló (%s) → fallback edge/gemini", provider, e)
        if provider == "gemini":
            dur = await fallback(text, out_path, config.EDGE_TTS_VOICE)
        else:
            if not gemini_client.available():
                raise
            dur = await fallback(text, out_path, fb_voice)
        used = "edge" if provider == "gemini" else "gemini"
    return out_path, dur, used


def probe_duration(path: Path) -> float:
    try:
        return wav_duration(Path(path))
    except Exception:  # noqa: BLE001
        return 0.0


def pcm_duration_estimate(data: bytes) -> float:
    return len(data) / 2 / SAMPLE_RATE


def silence_wav(path: Path, seconds: float) -> None:
    """Genera un WAV de silencio (para padding)."""
    n = int(SAMPLE_RATE * seconds)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n * 2))
        f.write(b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1,
                                          SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", n * 2))
        f.write(b"\x00" * n * 2)
