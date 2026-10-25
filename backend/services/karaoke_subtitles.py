"""
YOUTUBE AUTOMATION v2.25 — Subtítulos Karaoke Dinámicos Palabra por Palabra (INT-045)
Inspirado en OpenShorts (mutonby/openshorts) y el estilo de alta retención de Alex Hormozi/MrBeast.

Genera archivos de subtítulos Advanced SubStation Alpha (.ass) con sincronización
por palabra (Word-Level Timing):
- La palabra activa se ilumina en tiempo real con el color de acento del preset
  (Amarillo Oro en Hormozi, Verde Neón en MrBeast, Magenta en Cyberpunk).
- Efecto pop-in sutil (escala 112-118%) sobre la palabra que la voz está pronunciando.
- Agrupación en ventanas cortas de 3 a 5 palabras para lectura dinámica e hipnótica.
- Quema directa y nativa con FFmpeg (filtro `subtitles` o `ass` con libass).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from services import whisper_service

log = logging.getLogger("karaoke_subtitles")

ASS_NAME = "final_captions.ass"

# ─────────────────────────── PRESETS DE ESTILO KARAOKE ─────────────────────
# Colores ASS: &HAABBGGRR& (al revés de web hex, Alpha-Blue-Green-Red)
KARAOKE_PRESETS: dict[str, dict[str, Any]] = {
    "hormozi": {
        "name": "Hormozi",
        "font": "Impact",
        "fallback_font": "Arial Black",
        "fontsize_v": 62,
        "fontsize_h": 36,
        "primary_color": "&H00FFFFFF&",    # Blanco puro
        "highlight_color": "&H0000D7FF&",  # Amarillo oro / oro neón (#FFD700)
        "outline_color": "&H00000000&",    # Contorno negro
        "back_color": "&H80000000&",       # Sombra suave 50%
        "bold": -1,
        "outline": 4.5,
        "shadow": 2.0,
        "alignment": 2,                    # Bottom-center
        "margin_v_9_16": 380,              # Despegado de la barra inferior de TikTok/Reels
        "margin_v_16_9": 90,
        "uppercase": True,
        "chunk_size": 3,
        "pop_scale": 115,                  # Rebote 115% en palabra activa
    },
    "mrbeast": {
        "name": "MrBeast",
        "font": "Montserrat",
        "fallback_font": "Arial Black",
        "fontsize_v": 66,
        "fontsize_h": 38,
        "primary_color": "&H00FFFFFF&",    # Blanco
        "highlight_color": "&H0032FF00&",  # Verde neón brillante (#00FF32)
        "outline_color": "&H00000000&",    # Contorno negro muy grueso
        "back_color": "&H90000000&",
        "bold": -1,
        "outline": 5.5,
        "shadow": 2.5,
        "alignment": 2,
        "margin_v_9_16": 390,
        "margin_v_16_9": 95,
        "uppercase": True,
        "chunk_size": 3,
        "pop_scale": 118,
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "font": "Arial Black",
        "fallback_font": "Impact",
        "fontsize_v": 56,
        "fontsize_h": 34,
        "primary_color": "&H0000FFFF&",    # Amarillo neón base
        "highlight_color": "&H00FF00FF&",  # Magenta neón (#FF00FF)
        "outline_color": "&H00220022&",    # Contorno violeta oscuro
        "back_color": "&H80000000&",
        "bold": -1,
        "outline": 4.0,
        "shadow": 2.0,
        "alignment": 2,
        "margin_v_9_16": 380,
        "margin_v_16_9": 90,
        "uppercase": True,
        "chunk_size": 4,
        "pop_scale": 112,
    },
    "minimal": {
        "name": "Minimal",
        "font": "Helvetica",
        "fallback_font": "Arial",
        "fontsize_v": 50,
        "fontsize_h": 30,
        "primary_color": "&H00D0D0D0&",    # Gris perla
        "highlight_color": "&H00FFFFFF&",  # Blanco brillante
        "outline_color": "&H00111111&",
        "back_color": "&H40000000&",
        "bold": 0,
        "outline": 2.2,
        "shadow": 0.0,
        "alignment": 2,
        "margin_v_9_16": 350,
        "margin_v_16_9": 80,
        "uppercase": False,
        "chunk_size": 5,
        "pop_scale": 108,
    }
}


def get_preset(style_name: str | None) -> dict[str, Any]:
    key = str(style_name or "hormozi").lower().strip()
    return KARAOKE_PRESETS.get(key, KARAOKE_PRESETS["hormozi"])


def format_ass_time(seconds: float) -> str:
    """Timestamp ASS: H:MM:SS.cs (centésimas de segundo, 2 dígitos)."""
    cs = int(round(max(0.0, seconds) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_header(preset: dict[str, Any], resolution: str = "1080x1920") -> str:
    is_vertical = "1920" in resolution or "9:16" in resolution
    rx, ry = (1080, 1920) if is_vertical else (1920, 1080)
    fs = preset["fontsize_v"] if is_vertical else preset["fontsize_h"]
    mv = preset["margin_v_9_16"] if is_vertical else preset["margin_v_16_9"]

    font_name = preset["font"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {rx}
PlayResY: {ry}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {preset['name']},{font_name},{fs},{preset['primary_color']},{preset['highlight_color']},{preset['outline_color']},{preset['back_color']},{preset['bold']},0,0,0,100,100,1,0,1,{preset['outline']},{preset['shadow']},{preset['alignment']},30,30,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header


def build_karaoke_dialogues(words: list[dict], preset: dict[str, Any]) -> list[str]:
    """Genera las líneas de diálogo ASS iluminando la palabra activa."""
    if not words:
        return []

    chunk_size = preset.get("chunk_size", 3)
    highlight = preset["highlight_color"]
    pop_scale = preset.get("pop_scale", 115)
    is_upper = preset.get("uppercase", True)
    style_name = preset["name"]

    dialogues: list[str] = []

    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue

        for active_idx, target_word in enumerate(chunk):
            w_start = float(target_word.get("start", 0))
            w_end = float(target_word.get("end", w_start + 0.3))
            if w_end <= w_start:
                w_end = w_start + 0.25

            parts = []
            for j, w in enumerate(chunk):
                raw = str(w.get("word", "")).strip()
                if not raw:
                    continue
                txt = raw.upper() if is_upper else raw
                if j == active_idx:
                    # Palabra activa: cambia a color de acento y hace pop-in
                    parts.append(f"{{\\c{highlight}\\fscx{pop_scale}\\fscy{pop_scale}}}{txt}{{\\r}}")
                else:
                    parts.append(txt)

            if parts:
                line_text = " ".join(parts)
                dialogues.append(
                    f"Dialogue: 0,{format_ass_time(w_start)},{format_ass_time(w_end)},{style_name},,0,0,0,,{line_text}"
                )

    return dialogues


def build_ass_from_scenes(
    entries: list[dict],
    style_name: str = "hormozi",
    resolution: str = "1080x1920"
) -> str:
    """Construye un .ass completo a partir de las escenas consolidadas del manifest."""
    preset = get_preset(style_name)
    header = build_ass_header(preset, resolution)

    all_words: list[dict] = []
    cursor = 0.0

    for e in entries:
        dur = float(e.get("duration_sec") or 0)
        text = (e.get("subtitle_text") or e.get("narration") or "").strip()
        if not text:
            cursor += dur
            continue

        scene_words: list[dict] = []
        audio_path = str(e.get("audio_path") or "")

        # Si hay audio real y faster-whisper está instalado, extraer tiempos exactos
        if audio_path and Path(audio_path).is_file() and whisper_service.available():
            try:
                import asyncio
                # En contexto sync usamos loop o estimate
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    pass
                if loop and loop.is_running():
                    # si estamos dentro de loop, fallback estimación
                    scene_words = whisper_service.estimate_words(text, start=0.0, duration=dur)
                else:
                    scene_words = asyncio.run(whisper_service.transcribe_words(audio_path)) or []
            except Exception as ex:
                log.debug("[karaoke] fallback Whisper: %s", ex)

        if not scene_words:
            scene_words = whisper_service.estimate_words(text, start=0.0, duration=dur)

        # Desplazar tiempos por el cursor acumulado de la escena
        for w in scene_words:
            all_words.append({
                "word": w["word"],
                "start": round(cursor + float(w["start"]), 2),
                "end": round(cursor + float(w["end"]), 2)
            })

        cursor += dur

    dialogues = build_karaoke_dialogues(all_words, preset)
    return header + "\n".join(dialogues) + "\n"


def write_ass(
    run_dir: Path,
    entries: list[dict],
    style_name: str = "hormozi",
    resolution: str = "1080x1920"
) -> Path:
    """Escribe el archivo final_captions.ass en run_dir."""
    p = Path(run_dir) / ASS_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    ass_text = build_ass_from_scenes(entries, style_name, resolution)
    p.write_text(ass_text, encoding="utf-8")
    return p
