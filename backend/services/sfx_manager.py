"""
YOUTUBE AUTOMATION v2.26 — Sound Effects (SFX) Automáticos (INT-050)
Inspirado en OpenShorts (mutonby/openshorts) y editores de retención viral (CapCut/Premiere).

Inserta micro-efectos de sonido (SFX) automáticos en:
- Cortes y transiciones de escenas (Whoosh suave)
- Entradas de B-Roll cutaways (Impact / Swish)
- Palabras clave con emojis destacados o ganchos (Pop / Ding)

Incluye generador offline 100% nativo con FFmpeg lavfi (cero dependencias externas y $0 coste).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import DATA_DIR, TMP_DIR

log = logging.getLogger("sfx_manager")

SFX_DIR = DATA_DIR / "sfx"


def ensure_sfx_library() -> dict[str, Path]:
    """Asegura la disponibilidad de los efectos de audio base (Whoosh, Pop, Ding).

    Si los archivos no existen en disco, los sintetiza al vuelo con FFmpeg lavfi.
    Retorna un diccionario con las rutas locales de cada sonido.
    """
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")

    library: dict[str, Path] = {
        "whoosh": SFX_DIR / "whoosh.wav",
        "pop": SFX_DIR / "pop.wav",
        "ding": SFX_DIR / "ding.wav",
        "glitch": SFX_DIR / "glitch.wav"
    }

    if not ffmpeg:
        log.warning("[sfx_manager] FFmpeg no disponible para síntesis de SFX")
        return {k: p for k, p in library.items() if p.is_file()}

    # 1. Whoosh: ruido rosa barrido con curva de volumen (transiciones dinámicas)
    if not library["whoosh"].is_file():
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", "anoisesrc=d=0.35:c=pink:r=44100,lowpass=f=900,volume=0.3,afade=t=in:ss=0:d=0.12,afade=t=out:st=0.18:d=0.17",
            "-c:a", "pcm_s16le", str(library["whoosh"])
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            log.info("[sfx_manager] Sintetizado SFX 'whoosh.wav' con FFmpeg")
        except Exception as ex:
            log.debug("[sfx_manager] Error sintetizando whoosh: %s", ex)

    # 2. Pop: micro-tono senoidal con caída de frecuencia (para palabras / emojis)
    if not library["pop"].is_file():
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", "sine=f=480:d=0.14:r=44100,volume=0.25,afade=t=out:st=0.03:d=0.11",
            "-c:a", "pcm_s16le", str(library["pop"])
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            log.info("[sfx_manager] Sintetizado SFX 'pop.wav' con FFmpeg")
        except Exception as ex:
            log.debug("[sfx_manager] Error sintetizando pop: %s", ex)

    # 3. Ding: campana armónica clara para tips / revelaciones clave
    if not library["ding"].is_file():
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", "sine=f=1760:d=0.4:r=44100,volume=0.18,afade=t=out:st=0.04:d=0.36",
            "-c:a", "pcm_s16le", str(library["ding"])
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            log.info("[sfx_manager] Sintetizado SFX 'ding.wav' con FFmpeg")
        except Exception as ex:
            log.debug("[sfx_manager] Error sintetizando ding: %s", ex)

    # 4. Glitch: pulso corto filtrado
    if not library["glitch"].is_file():
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", "anoisesrc=d=0.1:c=white:r=44100,bandpass=f=1200:w=400,volume=0.2,afade=t=out:st=0.02:d=0.08",
            "-c:a", "pcm_s16le", str(library["glitch"])
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            log.info("[sfx_manager] Sintetizado SFX 'glitch.wav' con FFmpeg")
        except Exception as ex:
            log.debug("[sfx_manager] Error sintetizando glitch: %s", ex)

    return {k: p for k, p in library.items() if p.is_file()}


def plan_sfx_events(
    scene_durations: list[float],
    broll_intervals: list[dict[str, float]] | None = None,
    include_whoosh: bool = True,
    include_broll_sfx: bool = True
) -> list[dict[str, Any]]:
    """Genera la lista de eventos SFX con sus timestamps exactos en la línea de tiempo.

    - Whoosh: en cada corte entre escenas (excepto al inicio t=0 para no tapar el gancho vocal).
    - Pop / Ding: al inicio de cada B-roll cutaway.
    """
    events: list[dict[str, Any]] = []

    # 1. Transiciones entre escenas (Whoosh)
    if include_whoosh and len(scene_durations) > 1:
        cursor = 0.0
        for i, dur in enumerate(scene_durations[:-1]):
            cursor += float(dur)
            # Desplazar sutilmente -0.08s para que el sonido empiece justo antes del corte visual
            t_sfx = max(0.1, round(cursor - 0.08, 2))
            events.append({
                "type": "whoosh",
                "time": t_sfx,
                "volume": 0.22
            })

    # 2. Entradas de B-Roll (Pop / Ding)
    if include_broll_sfx and broll_intervals:
        for b in broll_intervals:
            start_t = float(b.get("start", 0))
            if start_t > 0.5:
                events.append({
                    "type": "pop",
                    "time": round(start_t - 0.04, 2),
                    "volume": 0.28
                })

    # Ordenar cronológicamente y desduplicar eventos muy cercanos (< 0.25s)
    events.sort(key=lambda x: x["time"])
    deduped: list[dict[str, Any]] = []
    last_t = -1.0
    for ev in events:
        if ev["time"] - last_t >= 0.25:
            deduped.append(ev)
            last_t = ev["time"]

    return deduped


def mix_sfx_track(
    main_audio: Path,
    events: list[dict[str, Any]],
    output_audio: Path,
    sfx_lib: dict[str, Path] | None = None
) -> bool:
    """Mezcla los eventos SFX sobre la pista de audio principal (voz/música) usando FFmpeg."""
    if not events:
        if main_audio != output_audio:
            shutil.copy2(main_audio, output_audio)
        return True

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not main_audio.is_file():
        return False

    lib = sfx_lib or ensure_sfx_library()
    if not lib:
        return False

    # Filtrar solo eventos cuyos archivos existan
    valid_events = [ev for ev in events if ev.get("type") in lib and lib[ev["type"]].is_file()]
    if not valid_events:
        return False

    cmd = [ffmpeg, "-y", "-i", str(main_audio)]
    filter_parts = []
    mix_labels = ["[0:a]"]

    for idx, ev in enumerate(valid_events, start=1):
        sfx_path = lib[ev["type"]]
        cmd.extend(["-i", str(sfx_path)])

        delay_ms = int(round(max(0.0, ev["time"]) * 1000))
        vol = float(ev.get("volume", 0.25))

        # adelay retrasa canales izquierdo y derecho en milisegundos
        filter_parts.append(
            f"[{idx}:a]volume={vol},adelay={delay_ms}|{delay_ms}[sfx{idx}];"
        )
        mix_labels.append(f"[sfx{idx}]")

    num_inputs = len(mix_labels)
    filter_parts.append(
        f"{''.join(mix_labels)}amix=inputs={num_inputs}:duration=first:dropout_transition=0:normalize=0[aout]"
    )

    full_filter = "".join(filter_parts)
    cmd.extend([
        "-filter_complex", full_filter,
        "-map", "[aout]",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_audio)
    ])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if res.returncode == 0 and output_audio.is_file() and output_audio.stat().st_size > 100:
            log.info("[sfx_manager] Mezclados %d SFX exitosamente en %s", len(valid_events), output_audio.name)
            return True
        log.warning("[sfx_manager] Falló mezcla SFX FFmpeg: %s", res.stderr[-200:])
        return False
    except Exception as ex:
        log.warning("[sfx_manager] Error ejecutando mezcla de SFX: %s", ex)
        return False
