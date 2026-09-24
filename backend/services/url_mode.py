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
import shutil
import subprocess
import sys
from pathlib import Path

from config import TMP_DIR
from services import whisper_service
from services.trend_research import _translate_ytdlp_error

log = logging.getLogger("url_mode")


class UrlModeError(Exception):
    pass


_YTDLP: list[str] | None = None


def ytdlp_cmd() -> list[str]:
    """Comando yt-dlp robusto (fix real del E2E): el servidor suele arrancar
    con un PATH reducido que no incluye el bin/ del venv, así que el binario
    suelto no siempre se resuelve. Orden de resolución:
    1) binario junto al propio intérprete (venv clásico),
    2) binario en PATH (instalación global / pipx),
    3) módulo python del MISMO intérprete (`python -m yt_dlp`, funciona si
       se instaló con pip en el venv aunque PATH no lo exponga)."""
    global _YTDLP
    if _YTDLP is None:
        exe_dir = Path(sys.executable).parent
        local_bin = exe_dir / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
        if local_bin.exists():
            _YTDLP = [str(local_bin)]
        elif shutil.which("yt-dlp"):
            _YTDLP = ["yt-dlp"]
        else:
            try:
                import yt_dlp  # noqa: F401
                _YTDLP = [sys.executable, "-m", "yt_dlp"]
            except ImportError:
                _YTDLP = ["yt-dlp"]  # fallará con mensaje claro en stderr
    return _YTDLP


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def clean_url(url: str) -> str:
    """Quita parámetros de tracking para evitar contenido privado/roto.
    YouTube: normaliza a watch?v=ID. TikTok: conserva /@user/video/ID y
    los enlaces cortos vm.tiktok.com (siguen redirección con yt-dlp)."""
    url = url.strip()
    if "youtube.com" in url or "youtu.be" in url:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{6,})", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    if "tiktok.com" in url:
        m = re.search(r"(tiktok\.com/@[\w.\-]+/video/\d+)", url)
        if m:
            return f"https://www.{m.group(1)}"
        return url.split("?")[0] or url  # vm.tiktok.com/xxxx (corto)
    return url.split("?")[0] or url


def _cookies_args(cookies: str | None) -> list[str]:
    """[--cookies-from-browser X] — la solución $0 al anti-bot de
    YouTube/TikTok desde IP residencial (misma receta de trend_research)."""
    return ["--cookies-from-browser", cookies] if cookies else []


async def fetch_metadata(url: str, cookies: str | None = None) -> dict:
    def _job():
        p = _run([*ytdlp_cmd(), "-j", "--no-warnings", "--skip-download",
                  *_cookies_args(cookies), url], timeout=60)
        if p.returncode != 0:
            raise UrlModeError(
                "yt-dlp no pudo leer el video: "
                + _translate_ytdlp_error(p.stderr or ""))
        return json.loads(p.stdout)
    return await asyncio.to_thread(_job)


async def download_audio(url: str, out_base: str,
                         cookies: str | None = None) -> Path:
    """Descarga solo el audio (mp3) del video origen."""
    dest = TMP_DIR / f"{out_base}.%(ext)s"

    def _job():
        p = _run([
            *ytdlp_cmd(), "-x", "--audio-format", "mp3", "--audio-quality", "5",
            "--no-playlist", "--no-warnings", *_cookies_args(cookies),
            "-o", str(dest), url,
        ], timeout=300)
        if p.returncode != 0:
            raise UrlModeError("Descarga fallida: "
                               + _translate_ytdlp_error(p.stderr or ""))
        hits = sorted(TMP_DIR.glob(f"{out_base}.*"),
                      key=lambda f: f.stat().st_size, reverse=True)
        if not hits:
            raise UrlModeError("No se encontró el archivo de audio descargado")
        return hits[0]

    return await asyncio.to_thread(_job)


async def transcript_from_url(url: str, job_base: str,
                              cookies: str | None = None) -> dict:
    """Devuelve {metadata, transcript} del video viral.
    cookies: nombre del navegador ('chrome', 'firefox', 'edge', 'brave')
    para reutilizar su sesión — desbloquea el anti-bot sin coste."""
    url = clean_url(url)
    meta = await fetch_metadata(url, cookies)
    audio = await download_audio(url, job_base, cookies)
    words = await whisper_service.transcribe_words(str(audio))
    if words:
        transcript = " ".join(w["word"] for w in words)
    else:
        # sin Whisper: intentar subtítulos automáticos de la plataforma
        def _subs():
            p = _run([*ytdlp_cmd(), "--skip-download", "--write-auto-subs",
                      "--sub-langs", "es,en", "--sub-format", "vtt",
                      *_cookies_args(cookies),
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
