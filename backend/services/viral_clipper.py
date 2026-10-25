"""
YOUTUBE AUTOMATION v2.24 — Viral Moment Detector & Clipper (INT-044)
Inspirado en OpenShorts (mutonby/openshorts).

Convierte videos largos (podcasts, entrevistas, webinars, streams) en Shorts/Reels/TikToks
virales en formato vertical 9:16 listos para publicar:

1. Ingesta inteligente: Metadatos y transcripción con timestamps (VTT / Whisper).
2. Estratega Viral AI: LLM (Gemini o NVIDIA) analiza la retención, calcula el
   Virality Score (0-100), detecta el Hook inicial y la razón psicológica de retención.
3. Render Vertical 9:16 Quirúrgico: Descarga mediante yt-dlp SOLO el fragmento exacto
   (--download-sections) y lo reencuadra con FFmpeg a 1080x1920 con fondo desenfocado (blur_bg).
4. Conversión a Proyecto: Integra el clip como proyecto editable en 1 clic.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from config import DATA_DIR, TMP_DIR
from services import gemini_client, nvidia_client, url_mode, whisper_service

log = logging.getLogger("viral_clipper")

RENDERS_DIR = DATA_DIR / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)


class ViralClipperError(Exception):
    def __init__(self, message: str, code: str = "CLIPPER_ERROR"):
        super().__init__(message)
        self.code = code


def _format_ts(seconds: float) -> str:
    """Convierte segundos en formato MM:SS o HH:MM:SS."""
    s = max(0.0, float(seconds))
    hrs = int(s // 3600)
    mins = int((s % 3600) // 60)
    secs = int(s % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _parse_ts(val: Any) -> float:
    """Convierte un string MM:SS o número en segundos flotantes."""
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    val_str = str(val).strip()
    parts = val_str.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return max(0.0, float(val_str))
    except ValueError:
        return 0.0


def parse_vtt(content: str) -> list[dict]:
    """Parsea el contenido de un archivo WebVTT en bloques estructurados."""
    blocks = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})", line)
        if m:
            h1, m1, s1, ms1 = m.group(1) or 0, m.group(2), m.group(3), m.group(4)
            h2, m2, s2, ms2 = m.group(5) or 0, m.group(6), m.group(7), m.group(8)
            t_start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
            t_end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not ("-->" in lines[i]):
                cleaned = re.sub(r"<[^>]+>", "", lines[i].strip())
                if cleaned:
                    text_lines.append(cleaned)
                i += 1
            if text_lines:
                raw_text = " ".join(text_lines)
                if not blocks or blocks[-1]["text"] != raw_text:
                    blocks.append({"start": round(t_start, 2), "end": round(t_end, 2), "text": raw_text})
            continue
        i += 1
    return blocks


def group_segments(blocks: list[dict], target_duration: float = 25.0) -> list[dict]:
    """Agrupa bloques pequeños de subtítulos en ventanas coherentes con timestamps."""
    if not blocks:
        return []
    grouped = []
    cur_start = blocks[0]["start"]
    cur_end = blocks[0]["end"]
    cur_texts = [blocks[0]["text"]]

    for b in blocks[1:]:
        if (b["end"] - cur_start) >= target_duration or (b["start"] - cur_end) > 3.0:
            grouped.append({
                "start": cur_start,
                "end": cur_end,
                "duration": round(cur_end - cur_start, 1),
                "text": " ".join(cur_texts)
            })
            cur_start = b["start"]
            cur_end = b["end"]
            cur_texts = [b["text"]]
        else:
            cur_end = b["end"]
            if b["text"] not in cur_texts:
                cur_texts.append(b["text"])

    if cur_texts:
        grouped.append({
            "start": cur_start,
            "end": cur_end,
            "duration": round(cur_end - cur_start, 1),
            "text": " ".join(cur_texts)
        })
    return grouped


async def fetch_timed_transcript(url: str, cookies: str | None = None) -> tuple[dict, list[dict]]:
    """Obtiene metadatos y transcripción segmentada con marcas de tiempo."""
    url = url_mode.clean_url(url)
    url = url_mode._guard_ssrf(url)
    meta = await url_mode.fetch_metadata(url, cookies)

    title = meta.get("title", "Video")
    duration = meta.get("duration", 0)
    channel = meta.get("uploader", "Canal")
    thumbnail = meta.get("thumbnail", "")

    job_id = f"clip_{uuid.uuid4().hex[:8]}"
    out_base = TMP_DIR / job_id

    # 1. Intentar descargar subtítulos automáticos en formato VTT (rápido, sin descargar video)
    def _get_subs():
        cmd = [
            *url_mode.ytdlp_cmd(),
            "--skip-download",
            "--write-auto-subs",
            "--write-subs",
            "--sub-langs", "es.*,en.*,es,en",
            "--sub-format", "vtt",
            *url_mode._cookies_args(cookies),
            "-o", str(out_base),
            url
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=90)

    p_subs = await asyncio.to_thread(_get_subs)
    vtt_files = list(TMP_DIR.glob(f"{job_id}*.vtt"))
    blocks = []

    if vtt_files:
        try:
            content = vtt_files[0].read_text(encoding="utf-8", errors="ignore")
            blocks = parse_vtt(content)
        finally:
            for vf in vtt_files:
                try:
                    vf.unlink(missing_ok=True)
                except Exception:
                    pass

    # 2. Si no hay subtítulos en YouTube, transcribir audio con Whisper o estimar
    if not blocks:
        try:
            audio_path = await url_mode.download_audio(url, job_id, cookies)
            words = await whisper_service.transcribe_words(str(audio_path))
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass

            if words:
                # Convertir palabras de Whisper a bloques
                cur_text = []
                cur_s = words[0]["start"]
                cur_e = words[0]["end"]
                for w in words:
                    cur_text.append(w["word"])
                    cur_e = w["end"]
                    if len(cur_text) >= 12 or (cur_e - cur_s) >= 4.0:
                        blocks.append({"start": cur_s, "end": cur_e, "text": " ".join(cur_text)})
                        cur_text = []
                        cur_s = cur_e
                if cur_text:
                    blocks.append({"start": cur_s, "end": cur_e, "text": " ".join(cur_text)})
        except Exception as e:
            log.warning("[viral_clipper] Fallback audio/whisper falló: %s", e)

    # 3. Si aún no hay bloques, generar segmentos sintéticos espaciados
    if not blocks:
        log.info("[viral_clipper] Sin transcripción directa; generando ventanas estimadas")
        total_d = max(60, duration or 600)
        step = 45.0
        t = 10.0
        while t + step <= total_d:
            blocks.append({
                "start": round(t, 2),
                "end": round(t + step, 2),
                "text": f"Segmento destacado del video ({_format_ts(t)} a {_format_ts(t+step)})"
            })
            t += step

    segments = group_segments(blocks, target_duration=30.0)
    source_meta = {
        "title": title,
        "channel": channel,
        "duration": duration,
        "duration_fmt": _format_ts(duration),
        "thumbnail": thumbnail,
        "views": meta.get("view_count", 0),
        "url": url
    }
    return source_meta, segments


def _fallback_heuristics(segments: list[dict], count: int = 5, min_dur: int = 20, max_dur: int = 60) -> list[dict]:
    """Genera momentos virales heurísticos de alta calidad si no hay LLM online."""
    moments = []
    # Selecciona segmentos distribuidos estratégicamente evitando los primeros 10s de intro
    usable = [s for s in segments if s["start"] >= 15.0 and (s["end"] - s["start"]) >= 15.0]
    if not usable:
        usable = segments

    step = max(1, len(usable) // count)
    for idx in range(min(count, len(usable))):
        s = usable[idx * step]
        dur = min(max_dur, max(min_dur, round(s["end"] - s["start"], 1)))
        score = 95 - (idx * 3)
        tier = "ULTRA VIRAL 🔥" if score >= 90 else "ALTO IMPACTO 🚀"
        text_snip = s.get("text", "")[:90]
        hook = text_snip.split(".")[0] if "." in text_snip else text_snip
        moments.append({
            "id": f"moment_{idx+1}",
            "rank": idx + 1,
            "title": f"💡 Momento Clave #{idx+1}: {hook[:45]}...",
            "start": round(s["start"], 1),
            "end": round(s["start"] + dur, 1),
            "start_fmt": _format_ts(s["start"]),
            "end_fmt": _format_ts(s["start"] + dur),
            "duration": dur,
            "virality_score": score,
            "virality_tier": tier,
            "hook": f"«{hook}»",
            "summary": s.get("text", "")[:200],
            "reason": "Segmento de alta densidad narrativa con ritmo dinámico ideal para Shorts.",
            "category": "revelacion" if idx % 2 == 0 else "historia"
        })
    return moments


async def detect_viral_moments(
    url: str,
    count: int = 5,
    min_duration: int = 20,
    max_duration: int = 65,
    cookies: str | None = None
) -> dict:
    """Detecta y rankea los mejores momentos virales con Virality Score (0-100)."""
    source_meta, segments = await fetch_timed_transcript(url, cookies)
    if not segments:
        raise ViralClipperError("No se pudieron extraer segmentos de video para analizar", "NO_SEGMENTS")

    # Limitar transcripción enviada al LLM para no desbordar tokens
    lines = []
    for s in segments[:180]:
        lines.append(f"[{_format_ts(s['start'])} - {_format_ts(s['end'])}] {s['text']}")
    transcript_text = "\n".join(lines)

    prompt = f"""Actúa como un Senior Short-Form Video Strategist y Viral Editor (estilo OpenShorts / OpusClip).
Analiza la siguiente transcripción con marcas de tiempo de un video largo y selecciona los {count} momentos con MAYOR potencial de viralidad en TikTok, YouTube Shorts e Instagram Reels.

CRITERIOS DE SELECCIÓN OBLIGATORIOS:
1. Hook Test (3 primeros segundos): El momento DEBE abrir con una frase impactante, pregunta intrigante o afirmación provocadora.
2. Historia Autocontenida: El espectador debe entender la anécdota, lección o revelación completa sin haber visto el resto del video.
3. Duración: Cada clip debe durar entre {min_duration} y {max_duration} segundos.
4. Virality Score (0 a 100):
   - 90-100: Impacto extremo, genera discusión o revelación sorprendente.
   - 80-89: Alto valor educativo, emoción o curiosidad.
   - 70-79: Entretenido y fluido.

TRANSCRIPCIÓN CON TIMESTAMPS:
{transcript_text}

Responde ÚNICAMENTE en formato JSON válido con la siguiente estructura:
{{
  "moments": [
    {{
      "rank": 1,
      "title": "Título corto y magnético con 1 emoji",
      "start": 124.5,
      "end": 169.0,
      "virality_score": 96,
      "hook": "La frase exacta con la que arranca el momento",
      "summary": "Resumen conciso del contenido del clip",
      "reason": "Explicación de por qué este momento retendrá audiencia en Shorts",
      "category": "revelacion"
    }}
  ]
}}"""

    system = "Eres un algoritmo experto en detección de clips virales y retención en videos cortos 9:16."
    raw_moments = []

    # Intentar Gemini primero
    if gemini_client.available():
        try:
            res = await gemini_client.generate_json(prompt, system=system)
            if isinstance(res, dict) and "moments" in res:
                raw_moments = res["moments"]
            elif isinstance(res, list):
                raw_moments = res
        except Exception as e:
            log.warning("[viral_clipper] Gemini generate_json falló: %s", e)

    # Fallback a NVIDIA si Gemini no respondió
    if not raw_moments and nvidia_client.available():
        try:
            ans = await nvidia_client.ask_agent([{"role": "user", "content": prompt}])
            clean = re.sub(r"```(?:json)?", "", ans).strip()
            data = json.loads(clean)
            raw_moments = data.get("moments", [])
        except Exception as e:
            log.warning("[viral_clipper] NVIDIA falló: %s", e)

    # Fallback heurístico si no hay LLM
    if not raw_moments:
        log.info("[viral_clipper] Usando heurística de momentos virales")
        raw_moments = _fallback_heuristics(segments, count=count, min_dur=min_duration, max_dur=max_duration)

    # Normalizar y ordenar por virality_score
    clean_moments = []
    for idx, m in enumerate(raw_moments):
        start_sec = _parse_ts(m.get("start", 0))
        end_sec = _parse_ts(m.get("end", start_sec + 45))
        if end_sec <= start_sec:
            end_sec = start_sec + 35.0
        dur = round(end_sec - start_sec, 1)
        score = int(m.get("virality_score", 85))
        score = max(50, min(100, score))
        tier = "ULTRA VIRAL 🔥" if score >= 90 else ("ALTO IMPACTO 🚀" if score >= 80 else "BUEN POTENCIAL 💡")
        clean_moments.append({
            "id": f"moment_{idx+1}",
            "rank": idx + 1,
            "title": str(m.get("title", f"Clip Viral #{idx+1}"))[:80],
            "start": round(start_sec, 2),
            "end": round(end_sec, 2),
            "start_fmt": _format_ts(start_sec),
            "end_fmt": _format_ts(end_sec),
            "duration": dur,
            "virality_score": score,
            "virality_tier": tier,
            "hook": str(m.get("hook", ""))[:140],
            "summary": str(m.get("summary", ""))[:300],
            "reason": str(m.get("reason", "Momento seleccionado por retención"))[:250],
            "category": str(m.get("category", "destacado")).lower()
        })

    clean_moments.sort(key=lambda x: x["virality_score"], reverse=True)
    for i, m in enumerate(clean_moments, 1):
        m["rank"] = i

    return {
        "ok": True,
        "source": source_meta,
        "total_moments": len(clean_moments),
        "moments": clean_moments
    }


async def render_vertical_moment(
    url: str,
    start: float,
    end: float,
    title: str = "Short",
    style: str = "blur_bg",
    cookies: str | None = None
) -> dict:
    """Descarga el segmento exacto y lo reencuadra con FFmpeg a vertical 9:16 (1080x1920)."""
    url = url_mode.clean_url(url)
    url = url_mode._guard_ssrf(url)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ViralClipperError("FFmpeg no está disponible en el servidor", "NO_FFMPEG")

    clip_id = f"short_{uuid.uuid4().hex[:8]}"
    raw_dest = TMP_DIR / f"{clip_id}_raw.mp4"
    final_dest = RENDERS_DIR / f"{clip_id}.mp4"

    start_fmt = _format_ts(start)
    end_fmt = _format_ts(end)

    # 1. Descargar ÚNICAMENTE la sección con yt-dlp usando --download-sections
    def _download_section():
        cmd = [
            *url_mode.ytdlp_cmd(),
            "--download-sections", f"*{start_fmt}-{end_fmt}",
            "--force-keyframes-at-cuts",
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            *url_mode._cookies_args(cookies),
            "-o", str(raw_dest),
            url
        ]
        log.info("[viral_clipper] Descargando sección %s - %s...", start_fmt, end_fmt)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    res_dl = await asyncio.to_thread(_download_section)
    if res_dl.returncode != 0 or not raw_dest.exists() or raw_dest.stat().st_size == 0:
        # Fallback sin secciones si el extractor no soporta corte remoto
        def _download_full_fallback():
            cmd = [
                *url_mode.ytdlp_cmd(),
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format", "mp4",
                *url_mode._cookies_args(cookies),
                "-o", str(raw_dest),
                url
            ]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=240)

        res_full = await asyncio.to_thread(_download_full_fallback)
        if res_full.returncode != 0 or not raw_dest.exists():
            raise ViralClipperError("No se pudo descargar el fragmento del video original", "DOWNLOAD_FAILED")

    # 2. Reencuadrar a 9:16 con FFmpeg
    def _ffmpeg_render():
        # Filtro podcast con fondo desenfocado (blur_bg):
        # Escala y desenfoca fondo a 1080x1920 y centra el video original nítido
        if style == "blur_bg":
            vf = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=25:5[bg];"
                "[0:v]scale=1080:1080:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
            )
        else:
            # Recorte centrado directo 9:16
            vf = "scale=ih*16/9:-1,crop=ih*9/16:ih,scale=1080:1920[outv]"

        cmd = [
            ffmpeg, "-y",
            "-i", str(raw_dest),
            "-filter_complex", vf,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(final_dest)
        ]
        log.info("[viral_clipper] Renderizando vertical 9:16 con FFmpeg...")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    res_ff = await asyncio.to_thread(_ffmpeg_render)
    try:
        raw_dest.unlink(missing_ok=True)
    except Exception:
        pass

    if res_ff.returncode != 0 or not final_dest.exists():
        raise ViralClipperError(f"Error al renderizar vertical 9:16 con FFmpeg: {res_ff.stderr[:200]}", "FFMPEG_ERROR")

    file_size = final_dest.stat().st_size
    duration = end - start
    return {
        "ok": True,
        "clip_id": clip_id,
        "title": title,
        "file_name": final_dest.name,
        "url": f"/api/renders/{final_dest.name}",
        "file_size": file_size,
        "duration": round(duration, 1),
        "format": "9:16",
        "style": style
    }
