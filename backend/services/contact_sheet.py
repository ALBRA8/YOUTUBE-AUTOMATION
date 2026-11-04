"""
INT-085 · Hoja de Contacto QA (Contact Sheet) — auditoría visual instantánea.

Genera una cuadrícula 4x4 con 16 fotogramas EQUIDISTANTES del video terminado,
con overlay por cuadro de:
  · timestamp legible (formato MM:SS.d, ej. «00:04.2»),
  · líneas guía semitransparentes CIAN de las zonas seguras TikTok/Shorts
    (arriba 15% · abajo 20% · derecha 15%) cuando el video es vertical.

El comando ffmpeg fue validado en vivo (INT-085): drawtext con expresión
`eif` para el timestamp + drawbox por frame + scale a tile 270px de ancho
(270·4 = 1080 → la hoja de un 9:16 sale a 1080x1920 exactos) + `tile=4x4`
(que hace flush automático del grid parcial si el video tiene menos de 16
frames — verificado con un video de 0.4 s).
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import safe_zones

log = logging.getLogger("contact_sheet")

TILE_W = 270                     # 270·4 = 1080 (hoja 9:16 a resolución nativa)
GRID_COLS, GRID_ROWS = 4, 4      # cuadrícula 4x4 (16 fotogramas)

# Fuentes candidatas para el timestamp (la primera que exista). Los glifos
# son dígitos/«:.» — cualquier sans serif del sistema sirve.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

# Timestamp MM:SS.d (ej. 00:04.2). Escapes \\: y \\, requeridos por el
# parser de filtergraph (validado en vivo, INT-085).
_TS_TEXT = (
    "%{eif\\:trunc(mod(t\\,3600)/60)\\:d\\:2}"
    "\\:%{eif\\:mod(trunc(t)\\,60)\\:d\\:2}"
    ".%{eif\\:trunc(mod(t\\,1)*10)\\:d\\:1}"
)


def _find_font() -> str:
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    return ""


def _ffprobe_meta(video_path: Path) -> tuple[int, int, float]:
    """(width, height, duration) del video vía ffprobe JSON."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height:format=duration",
           "-of", "json", str(video_path)]
    p = subprocess.run(cmd, capture_output=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe falló: {p.stderr.decode(errors='replace')[-200:]}")
    data = json.loads(p.stdout or "{}")
    st = (data.get("streams") or [{}])[0]
    dur = float((data.get("format") or {}).get("duration") or 0.0)
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    if w <= 0 or h <= 0 or dur <= 0:
        raise RuntimeError("video sin dimensiones o duración utilizables")
    return w, h, dur


def _safe_zone_boxes(w: int, h: int) -> list[str]:
    """Filtros drawbox (líneas cian semitransparentes) para frame vertical."""
    lines = safe_zones.safe_lines(w, h)
    if not lines:
        return []
    y_top, y_bottom, x_right = lines
    return [
        f"drawbox=x=0:y={y_top}:w=iw:h=4:color=cyan@0.6:t=4",
        f"drawbox=x=0:y={y_bottom}:w=iw:h=4:color=cyan@0.6:t=4",
        f"drawbox=x={x_right}:y=0:w=4:h=ih:color=cyan@0.6:t=4",
    ]


def build_contact_sheet_filter(w: int, h: int, dur: float,
                               num_frames: int = GRID_COLS * GRID_ROWS,
                               safe_zones_on: bool = True) -> str:
    """Cadena -vf completa (drawtext timestamp + zonas seguras + tile).

    Expuesta para tests/observabilidad: el QA puede validar el filtro sin
    ejecutar ffmpeg.
    """
    fps_expr = f"fps={num_frames}/{dur:.6f}"
    filters: list[str] = [
        fps_expr,
        f"drawtext=fontfile={_find_font()}:text='{_TS_TEXT}'"
        ":x=10:y=10:fontsize=44:fontcolor=white:box=1:boxcolor=black@0.6",
    ]
    if safe_zones_on:
        filters += _safe_zone_boxes(w, h)
    rows = (num_frames + GRID_COLS - 1) // GRID_COLS or GRID_ROWS
    filters.append(f"scale={TILE_W}:-2")
    filters.append(f"tile={GRID_COLS}x{rows}")
    return ",".join(filters)


def generate_contact_sheet(video_path: Path, output_path: Path,
                           num_frames: int = GRID_COLS * GRID_ROWS,
                           safe_zones: bool = True) -> Path:
    """Extrae `num_frames` fotogramas equidistantes de `video_path` y compone
    la hoja de contactos en `output_path` (JPG ligero). Si el video es
    vertical 9:16 dibuja las líneas guía cian de zonas seguras.

    Lanza RuntimeError/FileNotFoundError ante video inexistente o fallo de
    ffmpeg — el llamador decide la degradación (el endpoint responde 500 y
    el render la ignora: la hoja es QA, nunca un bloqueo).
    """
    video_path, output_path = Path(video_path), Path(output_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"video no encontrado: {video_path}")
    w, h, dur = _ffprobe_meta(video_path)

    vf = build_contact_sheet_filter(w, h, dur, num_frames=num_frames,
                                    safe_zones_on=safe_zones)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
           "-vf", vf, "-frames:v", "1", "-q:v", "5", str(output_path)]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    if p.returncode != 0 or not output_path.is_file() \
            or output_path.stat().st_size == 0:
        err = p.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"no se pudo generar la hoja de contactos: {err}")
    log.info("contact_sheet: %s (%dx%d, %.1fs) → %s",
             video_path.name, w, h, dur, output_path.name)
    return output_path
