"""B-Roll Auto-Inserter & Overlay Layering Engine (INT-046)
Metodología ClonaKit: Clonación limpia de InVideo AI, OpusClip y OpenShorts.

Permite superponer clips de apoyo visual (B-Roll) de stock (Pexels / Pixabay)
sobre el video principal en los momentos clave para maximizar la retención de audiencia,
manteniendo los subtítulos animados siempre en la capa superior (Top Layer).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx

from config import PEXELS_API_KEY, PIXABAY_API_KEY
from services import gemini_client, nvidia_client, url_mode

log = logging.getLogger("broll_overlay")

TMP_DIR = Path(os.getenv("TEMP_DIR", "temp_renders"))
TMP_DIR.mkdir(parents=True, exist_ok=True)


class BrollError(Exception):
    def __init__(self, message: str, code: str = "BROLL_ERROR"):
        super().__init__(message)
        self.code = code


def extract_broll_keywords_heuristic(text: str, max_keywords: int = 2) -> list[str]:
    """Extracción heurística rápida de conceptos visuales clave desde el texto."""
    if not text:
        return ["technology timelapse", "money success"]

    # Diccionario de conceptos visuales recurrentes
    mapping = {
        r"\b(dinero|dólar|dolares|plata|inversión|invertir|rico|millonario|ganar)\b": "money luxury wealth",
        r"\b(negocio|empresa|startup|ventas|cliente|oficina|trabajo)\b": "office business meeting",
        r"\b(código|programar|software|ia|inteligencia artificial|computadora|tecnología)\b": "artificial intelligence computer code",
        r"\b(tiempo|reloj|rápido|futuro|años|días|mañana)\b": "clock time lapse future",
        r"\b(casa|bienes raíces|apartamento|propiedad|inmueble)\b": "modern architecture real estate",
        r"\b(mente|pensar|idea|cerebro|psicología|concentración)\b": "focus thinking brain",
        r"\b(éxito|ganador|disciplina|meta|superación)\b": "athlete running success mountain summit",
        r"\b(ciudad|mundo|país|viaje|global)\b": "city skyline drone aerial"
    }

    results = []
    text_lower = text.lower()
    for pattern, query in mapping.items():
        if re.search(pattern, text_lower):
            results.append(query)
            if len(results) >= max_keywords:
                break

    if not results:
        # Palabras de más de 5 letras como fallback
        words = [w for w in re.findall(r"\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]{5,}\b", text_lower)
                 if w not in ("cuando", "porque", "entonces", "también", "donde", "mientras", "siempre")]
        if words:
            results.append(f"{words[0]} dynamic")
        else:
            results.append("modern dynamic motion")

    return results[:max_keywords]


async def extract_broll_keywords_ai(text: str, max_keywords: int = 2) -> list[str]:
    """Usa IA (Gemini/NVIDIA) para identificar los mejores términos de búsqueda de stock video."""
    prompt = f"""Analiza el siguiente texto de un video corto y devuelve exactamente {max_keywords} términos de búsqueda visual en inglés para videos de stock (como Pexels/iStock).
Deben ser conceptos visuales concretos, cinemáticos y atractivos para insertar como B-Roll.

Texto: "{text}"

Devuelve ÚNICAMENTE los términos separados por comas, sin explicaciones ni viñetas.
Ejemplo: luxury car driving, counting dollar bills"""

    try:
        raw_res = None
        if gemini_client.available():
            raw_res = await asyncio.to_thread(gemini_client.generate_text, prompt)
        elif nvidia_client.available():
            raw_res = await asyncio.to_thread(nvidia_client.generate_text, prompt)

        if raw_res:
            terms = [t.strip().strip('"').strip("'") for t in raw_res.replace("\n", ",").split(",") if t.strip()]
            if terms:
                return terms[:max_keywords]
    except Exception as ex:
        log.debug("[broll_overlay] AI keyword extraction fallback a heurística: %s", ex)

    return extract_broll_keywords_heuristic(text, max_keywords=max_keywords)


def plan_broll_intervals(duration: float, count: int = 1, broll_duration: float = 3.0) -> list[dict]:
    """Genera ventanas de tiempo seguras para B-rolls (evitando el gancho de los primeros 3s y los últimos 2s)."""
    if duration < 7.0 or count <= 0:
        return []

    # Ajustar duración si el clip es muy corto
    b_dur = min(broll_duration, (duration - 4.0) / count)
    intervals = []

    if count == 1:
        # Colocar alrededor del 25% - 40% del video
        start = max(3.5, round(duration * 0.28, 1))
        end = round(start + b_dur, 1)
        if end <= duration - 1.5:
            intervals.append({"start": start, "end": end, "duration": round(end - start, 1)})
    else:
        # 2 o más B-rolls espaciados
        step = (duration - 5.0) / (count + 1)
        for i in range(count):
            start = round(3.5 + (i * step), 1)
            end = round(start + b_dur, 1)
            if end <= duration - 1.0:
                intervals.append({"start": start, "end": end, "duration": round(end - start, 1)})

    return intervals


async def fetch_stock_video_pexels(query: str, dest_path: Path, orientation: str = "portrait") -> bool:
    """Descarga un clip de stock gratis desde Pexels Video API."""
    key = os.getenv("PEXELS_API_KEY", PEXELS_API_KEY).strip()
    if not key:
        return False

    url = f"https://api.pexels.com/videos/search?query={httpx.URL(query).raw_path.decode()}&orientation={orientation}&per_page=3"
    headers = {"Authorization": key}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                log.warning("[broll_overlay] Pexels API retornó %s", resp.status_code)
                return False

            data = resp.json()
            videos = data.get("videos", [])
            if not videos:
                return False

            # Buscar video con resolución adecuada (vertical o HD)
            best_link = None
            for vid in videos:
                files = vid.get("video_files", [])
                # Priorizar archivos portrait o 1080p
                for f in files:
                    if f.get("link"):
                        best_link = f.get("link")
                        if f.get("width", 0) <= 1080 and f.get("height", 0) >= 1080:
                            break
                if best_link:
                    break

            if not best_link:
                return False

            # Descargar archivo MP4
            dl_resp = await client.get(best_link)
            if dl_resp.status_code == 200 and len(dl_resp.content) > 10000:
                dest_path.write_bytes(dl_resp.content)
                log.info("[broll_overlay] Video de Pexels descargado exitosamente: %s", dest_path.name)
                return True
    except Exception as ex:
        log.warning("[broll_overlay] Error al consultar Pexels API: %s", ex)

    return False


def generate_synthetic_broll(dest_path: Path, duration: float = 3.0, query_label: str = "B-ROLL") -> bool:
    """Genera un B-roll visual de movimiento cinemático sintético con FFmpeg si no hay internet o API key."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False

    # Crea un fondo animado en degradado moderno con ligero movimiento
    vf = (
        f"testsrc=size=1080x1920:rate=30,boxblur=20:5,"
        f"drawbox=x=0:y=0:w=1080:h=1920:color=0x0a1128@0.4:t=fill"
    )

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x111936:s=1080x1920:r=30:d={duration}",
        "-vf", "noise=c1s=8:c0f=u",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(dest_path)
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        return res.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 0
    except Exception as ex:
        log.warning("[broll_overlay] No se pudo generar B-roll sintético: %s", ex)
        return False


async def prepare_broll_clip(query: str, duration: float, out_path: Path) -> bool:
    """Intenta descargar de Pexels; si no es posible, genera un clip de fallback seguro."""
    ok = await fetch_stock_video_pexels(query, out_path, orientation="portrait")
    if not ok:
        ok = generate_synthetic_broll(out_path, duration=duration, query_label=query)
    return ok
