"""
YOUTUBE AUTOMATION v2.37 — MrBeast Style Multi-Language Dubber (INT-068)
Inspirado en el sistema de canales doblados de MrBeast y ElevenLabs Dubbing Studio.

Permite tomar un video o guion producido en Español y generar automáticamente
versiones dobladas con voces neuronales nativas en:
- 🇺🇸 Inglés (US) - en-US-ChristopherNeural / en-US-JennyNeural
- 🇧🇷 Portugués (Brasil) - pt-BR-AntonioNeural / pt-BR-FranciscaNeural
- 🇫🇷 Francés - fr-FR-HenriNeural / fr-FR-DeniseNeural
- 🇩🇪 Alemán - de-DE-ConradNeural / de-DE-KatjaNeural
- 🇯🇵 Japonés - ja-JP-KeitaNeural / ja-JP-NanamiNeural
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import DATA_DIR, TMP_DIR
from services import gemini_client

log = logging.getLogger("multilang_dubber")

DUB_LANGUAGES: dict[str, dict[str, Any]] = {
    "en": {
        "code": "en",
        "name": "Inglés (US)",
        "flag": "🇺🇸",
        "voice": "en-US-ChristopherNeural",
        "market": "Mercado Global & Tier 1 (Mayor RPM $8-$25)",
        "sample": "Hello! This is a complete game changer for your productivity."
    },
    "pt": {
        "code": "pt",
        "name": "Portugués (Brasil)",
        "flag": "🇧🇷",
        "voice": "pt-BR-AntonioNeural",
        "market": "Mercado Brasil (+210M habitantes, alto volumen viral)",
        "sample": "Olá! Isto vai mudar completamente a sua rotina diária."
    },
    "fr": {
        "code": "fr",
        "name": "Francés",
        "flag": "🇫🇷",
        "voice": "fr-FR-HenriNeural",
        "market": "Francia, Canadá y África francófona (RPM $7-$18)",
        "sample": "Bonjour! C'est une véritable révolution pour votre quotidien."
    },
    "de": {
        "code": "de",
        "name": "Alemán",
        "flag": "🇩🇪",
        "voice": "de-DE-ConradNeural",
        "market": "Alemania, Austria y Suiza (RPM más alto de Europa)",
        "sample": "Hallo! Das wird Ihren Alltag komplett verändern."
    },
    "ja": {
        "code": "ja",
        "name": "Japonés",
        "flag": "🇯🇵",
        "voice": "ja-JP-KeitaNeural",
        "market": "Japón (Comunidad de alta fidelidad y retención)",
        "sample": "こんにちは！これはあなたの日常を劇的に変えるものです。"
    }
}


async def translate_text(text: str, target_lang: str) -> str:
    """Traduce el texto preservando el tono persuasivo, ganchos y cifras.

    Usa Gemini si está disponible; si no, aplica reglas heurísticas directas.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return ""

    target_cfg = DUB_LANGUAGES.get(target_lang, DUB_LANGUAGES["en"])
    lang_name = target_cfg["name"]

    if gemini_client.available():
        try:
            prompt = (
                f"Translate the following YouTube video narration into natural, highly engaging {lang_name}. "
                f"Preserve all emotional hooks, numbers, and punchy pacing. Respond ONLY with the translated text:\n\n"
                f"{clean_text}"
            )
            translated = await gemini_client.generate_text(prompt)
            if translated and len(translated.strip()) > 5:
                return translated.strip()
        except Exception as e:
            log.warning("[multilang_dubber] Falló Gemini translate: %s", e)

    # Heurística de respaldo para pruebas offline
    if target_lang == "en":
        replacements = [
            ("¡Detente un segundo", "Stop for a second"),
            ("No cometas este grave error", "Don't make this huge mistake"),
            ("El secreto que las marcas", "The secret that brands"),
            ("nunca te dirán", "will never tell you"),
            ("este increíble producto", "this incredible product"),
            ("gracias a", "thanks to"),
            ("Haz clic en el enlace", "Click the link down below"),
            ("aprovecha el descuento", "grab the special discount today")
        ]
        out = clean_text
        for es_w, en_w in replacements:
            out = out.replace(es_w, en_w)
        return out
    elif target_lang == "pt":
        return f"[Dublado em Português]: {clean_text}"
    else:
        return f"[{lang_name} Dub]: {clean_text}"


async def synthesize_dubbed_speech(text: str, target_lang: str, out_wav: Path) -> Path:
    """Sintetiza la voz neuronal en el idioma de destino usando Edge-TTS (100% gratuito)."""
    target_cfg = DUB_LANGUAGES.get(target_lang, DUB_LANGUAGES["en"])
    voice = target_cfg["voice"]

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    mp3_file = out_wav.with_suffix(".mp3")

    import edge_tts
    comm = edge_tts.Communicate(text, voice)
    await comm.save(str(mp3_file))

    # Convertir a WAV PCM
    cmd = [
        "ffmpeg", "-y",
        "-i", str(mp3_file),
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_wav)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_wav


def swap_video_audio(
    video_path: Path,
    new_audio_path: Path,
    output_path: Path
) -> Path:
    """Sustituye la pista de audio del video original con la pista doblada mediante FFmpeg."""
    if not video_path.is_file():
        raise FileNotFoundError(f"Video original no encontrado: {video_path}")
    if not new_audio_path.is_file():
        raise FileNotFoundError(f"Audio doblado no encontrado: {new_audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(new_audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg swap audio falló: {res.stderr}")

    return output_path
