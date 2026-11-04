"""
INT-085 · Zonas seguras móviles — ÚNICA fuente de verdad.

UI de TikTok / Reels / YouTube Shorts tapa partes del frame:
  · Arriba 15%   → barra de estado, título del video y campos de búsqueda.
  · Abajo  20%   → @usuario, descripción, botón de audio yCaption nativo.
  · Derecha 15%  → botonera de interacción (Like, Comentarios, Compartir).

Todas las proporciones son sobre la altura (para márgenes top/bottom) o el
ancho (para el margen derecho) del frame 9:16 (referencia 1080x1920).

Consumidores:
  · pipeline/subtitles.py  → banda segura del subtítulo (Y 1200-1350 @1920).
  · pipeline/typography.py → MarginV/Margins del estilo 'Shorts'.
  · services/contact_sheet.py → líneas guía cian de la hoja de contactos QA.
"""
from __future__ import annotations

# Proporciones de las zonas ocupadas por la UI (fracción del frame).
SAFE_TOP_RATIO = 0.15      # barra de estado / título superior
SAFE_BOTTOM_RATIO = 0.20   # título, descripción y botón de audio
SAFE_RIGHT_RATIO = 0.15    # botonera Like / Comentar / Compartir

# Banda vertical donde debe vivir el subtítulo en 9:16 (proporciones de
# 1080x1920): entre Y=1200 y Y=1350; hard-cap absoluto Y=1550.
SUB_Y_MIN_RATIO = 0.625     # 1200/1920
SUB_Y_MAX_RATIO = 0.703125  # 1350/1920 → bottom del texto (anchor Alignment=2)
SUB_Y_ABS_MAX_RATIO = 0.807292  # 1550/1920 — NUNCA por debajo


def is_vertical(w: int, h: int) -> bool:
    """True si el frame es vertical (9:16 / h > w)."""
    return h > w


def safe_lines(w: int, h: int) -> tuple[int, int, int] | None:
    """Coordenadas (px) de las 3 líneas guía de zonas seguras para un frame
    vertical: (y_top, y_bottom, x_right). None si el frame no es vertical.

    y_top     → límite inferior de la zona superior (0.15·H)
    y_bottom  → límite superior de la zona inferior (0.80·H)
    x_right   → límite izquierdo de la botonera derecha (0.85·W)
    """
    if not is_vertical(w, h):
        return None
    return (int(h * SAFE_TOP_RATIO),
            int(h * (1.0 - SAFE_BOTTOM_RATIO)),
            int(w * (1.0 - SAFE_RIGHT_RATIO)))


def subtitle_margins(w: int, h: int) -> tuple[int, int, int] | None:
    """Márgenes ASS (MarginL, MarginR, MarginV) que dejan el subtítulo dentro
    de la banda segura en un frame vertical; None si es horizontal.

    Con Alignment=2 (bottom-center), el borde inferior del texto queda en
    Y = h - MarginV = 0.703·h (1350 @1920): dentro de [1200, 1350] y nunca
    por debajo de 1550 incluso con wraps multilínea (el texto crece hacia
    arriba). MarginR reserva la botonera derecha completa (≥15% del ancho)
    y MarginL equilibra mínimamente para que el bloque siga legible.
    """
    if not is_vertical(w, h):
        return None
    ml = max(60, int(w * 0.06))            # 64 @1080
    mr = max(int(w * SAFE_RIGHT_RATIO), 170)  # 170 @1080 (≥ botonera 162px)
    mv = h - int(h * SUB_Y_MAX_RATIO)      # 570 @1920 → bottom del texto 1350
    return (ml, mr, mv)
