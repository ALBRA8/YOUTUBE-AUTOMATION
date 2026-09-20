"""
YOUTUBE AUTOMATION v2.0 — Modo "Desde URL" (killer feature de Labsia, aquí gratis)
Flujo: yt-dlp descarga el audio del video viral (TikTok/YouTube) →
Whisper lo transcribe → Gemini crea un guion ORIGINAL mejorado
(nuevo ángulo, misma estructura ganadora — sin copiar contenido).
"""
import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path

from config import TMP_DIR
from services import whisper_service

log = logging.getLogger("url_mode")


class UrlModeError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def clean_url(url: str) -> str:
    """Quita parámetros de tracking para evitar contenido privado/roto."""
    url = url.strip()
    if "youtube.com" in url or "youtu.be" in url:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{6,})", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url.split("?")[0] or url


async def fetch_metadata(url: str) -> dict:
    def _run():
        p = _run(["yt-dlp", "-j", "--no-warnings", "--skip-download", url], timeout=60)
        if p.returncode != 0:
            raise UrlModeError(f"yt-dlp no pudo leer el video: {p.stderr[:300]}")
        return json.loads(p.stdout)
    return await asyncio.to_thread(_run)


async def download_audio(url: str, out_base: str) -> Path:
    """Descarga solo el audio (mp3) del video origen."""
    dest = TMP_DIR / f"{out_base}.%(ext)s"

    def _run():
        p = _run([
            "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
            "--no-playlist", "--no-warnings", "-o", str(dest), url,
        ], timeout=300)
        if p.returncode != 0:
            raise UrlModeError(f"Descarga fallida: {p.stderr[-300:]}")
        hits = sorted(TMP_DIR.glob(f"{out_base}.*"),
                      key=lambda f: f.stat().st_size, reverse=True)
        if not hits:
            raise UrlModeError("No se encontró el archivo de audio descargado")
        return hits[0]

    return await asyncio.to_thread(_run)


async def transcript_from_url(url: str, job_base: str) -> dict:
    """Devuelve {metadata, transcript} del video viral."""
    url = clean_url(url)
    meta = await fetch_metadata(url)
    audio = await download_audio(url, job_base)
    words = await whisper_service.transcribe_words(str(audio))
    if words:
        transcript = " ".join(w["word"] for w in words)
    else:
        # sin Whisper: intentar subtítulos automáticos de la plataforma
        def _subs():
            p = _run(["yt-dlp", "--skip-download", "--write-auto-subs",
                      "--sub-langs", "es,en", "--sub-format", "vtt",
                      "-o", str(TMP_DIR / job_base), url], timeout=120)
            vtts = list(TMP_DIR.glob(f"{job_base}*.vtt"))
            if not vtts:
                return ""
            text = _parse_vtt(vtts[0])
            return text
        transcript = await asyncio.to_thread(_subs)
    audio.unlink(missing_ok=True)
    if not transcript.strip():
        raise UrlModeError(
            "No se pudo obtener transcripción (instala faster-whisper o usa un video con subtítulos)")
    return {"metadata": {
                "title": meta.get("title", ""),
                "channel": meta.get("uploader", ""),
                "duration": meta.get("duration", 0),
                "views": meta.get("view_count", 0),
                "url": url,
            },
            "transcript": transcript.strip()[:12000]}


def _parse_vtt(path: Path) -> str:
    lines, seen = [], set()
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:",
                                                         "NOTE")):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return " ".join(lines)
