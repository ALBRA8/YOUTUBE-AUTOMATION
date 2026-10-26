"""
YOUTUBE AUTOMATION v2.27 — Barra de Progreso Dinámica para Shorts (INT-051)
Inspirado en OpenShorts (mutonby/openshorts) y el formato viral de alta retención.

Genera una barra de progreso inferior animada en tiempo real usando el filtro nativo drawbox de FFmpeg:
- Pista de fondo semitransparente (track)
- Relleno progresivo exacto de izquierda a derecha: w = iw * (t / DURATION)
- Sincronización perfecta al milisegundo sin desajustes
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("progress_overlay")


def build_progress_bar_filter(
    duration: float,
    color: str = "0x10B981",  # Verde esmeralda de YouTube Automation
    height: int = 6,
    y_pos: int = 1914,       # Justo en el borde inferior para Shorts 9:16 (1080x1920)
    width: int = 1080,
    bg_opacity: float = 0.45,
    bar_opacity: float = 0.95
) -> str:
    """Construye la cláusula FFmpeg drawbox para la barra de progreso animada.

    Retorna la cadena de filtros encadenados:
    1. Fondo semitransparente (track de fondo)
    2. Barra de relleno proporcional al tiempo actual: w='min(iw,iw*(t/DUR))'
    """
    safe_dur = max(0.5, float(duration))
    # Limpiar color si viene con #
    clean_color = color.replace("#", "0x")
    if not clean_color.startswith("0x"):
        clean_color = f"0x{clean_color}"

    # Filtro de fondo oscuro sutil
    bg_filter = f"drawbox=x=0:y={y_pos}:w={width}:h={height}:color=0x000000@{bg_opacity}:t=fill"

    # Filtro de relleno animado con función de tiempo 't'
    fg_filter = (
        f"drawbox=x=0:y={y_pos}:"
        f"w='min(iw,iw*(t/{safe_dur:.3f}))':"
        f"h={height}:"
        f"color={clean_color}@{bar_opacity}:"
        f"t=fill"
    )

    return f"{bg_filter},{fg_filter}"
