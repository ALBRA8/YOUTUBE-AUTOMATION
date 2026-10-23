"""
YOUTUBE AUTOMATION v2 — INT-021: Tipografía de impacto + contraste dinámico.

Utilidad de tipografía para subtítulos de Shorts:
  - calculate_luminance(): luminancia relativa WCAG 2.x (0..1).
  - get_contrasting_style(): paleta texto/borde/sombra con contraste
    verificado >= 4.5:1 (WCAG AA), adaptada a 3 bandas de brillo de escena.
  - generate_shorts_sub_style(): línea `Style:` ASS lista para incrustar
    en el .ass, resuelta para la resolución real del render.
  - estimate_video_brightness(): brillo medio REAL del video (ffmpeg
    signalstats YAVG sobre una muestra); cualquier fallo cae en 0.5
    (banda neutra) — el quemado nunca depende de esta medición.

Fuente: backend/data/fonts/Montserrat-ExtraBold.ttf (SIL OFL 1.1; OFL.txt
junto a la fuente). NOTA DE MATCHING VERIFICADA EMPÍRICAMENTE (A/B de MD5
de fotogramas con ffmpeg+libass real; detalles en CONTEXTO INT-021 §3):
libass indexa el directorio (fontsdir) por el nombre de familia ID1 de la
TTF — 'Montserrat ExtraBold' — y NO resuelve la familia tipográfica ID16
('Montserrat'): pedir 'Montserrat' con fontsdir degrada SILENCIOSAMENTE a
la fuente por defecto. Por eso Fontname usa 'Montserrat ExtraBold' cuando
existe la fuente embarcada, y 'Montserrat' solo si se confía en una fuente
instalada en el sistema.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parents[1] / "data" / "fonts"
FONT_FILE = FONT_DIR / "Montserrat-ExtraBold.ttf"
FONT_LOCAL_NAME = "Montserrat ExtraBold"  # familia ID1 de la TTF embarcada
FONT_SYSTEM_NAME = "Montserrat"           # caso fuente instalada en sistema

WCAG_MIN_CONTRAST = 4.5

# Paletas candidatas: texto / borde / sombra (RGB base; la sombra es
# siempre negra, su opacidad la fija la banda vía alfa BackColour).
_PALETTES = {
    "white":      ((255, 255, 255), (8, 8, 8), (0, 0, 0)),
    "yellow":     ((255, 255, 0),   (8, 8, 8), (0, 0, 0)),
    "white_deep": ((255, 255, 255), (16, 16, 16), (0, 0, 0)),
}
_PREFERENCE = ("white", "yellow", "white_deep")

_YAVG_RE = re.compile(r"YAVG=([0-9]+(?:\.[0-9]+)?)")


def find_font() -> str | None:
    """Ruta de la TTF embarcada si existe (None si no)."""
    return str(FONT_FILE) if FONT_FILE.is_file() else None


def calculate_luminance(r: float, g: float, b: float) -> float:
    """Luminancia relativa WCAG 2.x de un color RGB (canales 0-255)."""
    def _lin(c: float) -> float:
        c = min(max(float(c), 0.0), 255.0) / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(l1: float, l2: float) -> float:
    """Ratio de contraste WCAG entre dos luminancias (1..21)."""
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _ass_color(r: int, g: int, b: int, alpha: int = 0x00) -> str:
    """RGB -> &HAABBGGRR (ASS es BGR; alfa invertido: 00 = opaco)."""
    return f"&H{alpha:02X}{b & 0xFF:02X}{g & 0xFF:02X}{r & 0xFF:02X}"


def get_contrasting_style(avg_brightness: float = 0.5) -> dict:
    """Paleta de subtítulos con contraste >= 4.5:1 verificado.

    Contrato (dos interfaces, ambas >= WCAG AA):
      - texto vs borde (la interfaz por donde se lee el glifo);
      - max(texto vs escena, borde vs escena): el borde separa del fondo
        o el texto se sostiene por sí mismo sobre él.

    Bandas por brillo medio de escena (0..1):
      oscura <0.45  -> texto blanco + borde 3 + sombra alfa 80
      mixta  <0.72  -> texto amarillo (energía Hormozi) + borde 4 + alfa 9E
      clara  >=0.72 -> blanco + borde oscuro reforzado 4 + sombra alfa B4

    Devuelve el primer candidato de banda que cumple el contrato; si
    ninguno lo cumple (no ocurre en 0..1), el de mayor score mínimo.
    El dict incluye los contrastes MEDIDOS (auditables en tests).
    """
    lum = min(max(float(avg_brightness), 0.0), 1.0)
    if lum < 0.45:
        band, outline_px, back_alpha = "dark", 3, 0x80
    elif lum < 0.72:
        band, outline_px, back_alpha = "mid", 4, 0x9E
    else:
        band, outline_px, back_alpha = "bright", 4, 0xB4
    band_key = {"dark": "white", "mid": "yellow", "bright": "white_deep"}[band]
    candidates = [band_key] + [k for k in _PREFERENCE if k != band_key]

    best: tuple[float, str, float, float, float] | None = None
    for key in candidates:
        text_rgb, out_rgb, back_rgb = _PALETTES[key]
        l_text = calculate_luminance(*text_rgb)
        l_out = calculate_luminance(*out_rgb)
        cr_to = _contrast_ratio(l_text, l_out)   # texto vs borde
        cr_ts = _contrast_ratio(l_text, lum)     # texto vs escena
        cr_os = _contrast_ratio(l_out, lum)      # borde vs escena
        score = min(cr_to, max(cr_ts, cr_os))
        if best is None or score > best[0]:
            best = (score, key, cr_to, cr_ts, cr_os)
        if cr_to >= WCAG_MIN_CONTRAST and max(cr_ts, cr_os) >= WCAG_MIN_CONTRAST:
            break  # primer candidato de banda que cumple el contrato
    _, key, cr_to, cr_ts, cr_os = best
    text_rgb, out_rgb, back_rgb = _PALETTES[key]
    return {
        "band": band,
        "avg_brightness": round(lum, 4),
        "text_rgb": text_rgb, "outline_rgb": out_rgb, "back_rgb": back_rgb,
        "text_color": _ass_color(*text_rgb),
        "outline_color": _ass_color(*out_rgb),
        "back_color": _ass_color(*back_rgb, alpha=back_alpha),
        "outline": outline_px, "shadow": 2,
        "contrast_text_outline": round(cr_to, 2),
        "contrast_text_scene": round(cr_ts, 2),
        "contrast_outline_scene": round(cr_os, 2),
        "contrast_min": round(min(cr_to, max(cr_ts, cr_os)), 2),
        "meets_wcag": cr_to >= WCAG_MIN_CONTRAST
                      and max(cr_ts, cr_os) >= WCAG_MIN_CONTRAST,
    }


def generate_shorts_sub_style(font_path: str | None = None,
                              w: int = 1080, h: int = 1920,
                              avg_brightness: float = 0.5) -> str:
    """Línea `Style:` ASS para Shorts (nombre de estilo: 'Shorts').

    - Fontname: 'Montserrat ExtraBold' con la TTF embarcada (matching
      libass VERIFICADO — docstring del módulo) o 'Montserrat' si
      font_path es None (fuente instalada en el sistema).
    - Fontsize: 3.7% de la altura -> 71pt a 1080x1920 (banda 68-75) y
      escala proporcional (142pt a 3840) — PlayRes viaja con la
      resolución real del render.
    - MarginV: >= 280px desde abajo (zona segura UI Shorts/TikTok),
      escalado en 4K (560px a 3840).
    - Bold 1 · BorderStyle 1 · Outline 3-4 (banda) · Shadow 2 · Align 2.
    """
    style = get_contrasting_style(avg_brightness)
    h = max(int(h), 1)
    fontname = FONT_LOCAL_NAME if font_path else FONT_SYSTEM_NAME
    size = max(28, int(h * 0.037))            # 71 @1920 · 142 @3840
    marginv = max(280, int(h * 280 / 1920))   # 280 @1920 · 560 @3840
    return (f"Style: Shorts,{fontname},{size},{style['text_color']},"
            f"&H00FFFFFF,{style['outline_color']},{style['back_color']},"
            f"1,0,0,0,100,100,1,0,1,{style['outline']},{style['shadow']},"
            f"2,60,60,{marginv},1")


def estimate_video_brightness(video_path: str | Path, timeout_s: int = 45,
                              sample_seconds: int = 45,
                              runner=None) -> float:
    """Brillo medio REAL (0..1) de una muestra del video.

    Liviano por diseño: UNA pasada decodificando como máximo
    `sample_seconds` s, escala 64x64, sin audio, timeout propio.
    YAVG es luma BT.601 en rango limitado (16-235): normaliza (Y-16)/219.

    `runner` (opcional) permite inyectar el ejecutor (video._run_ffmpeg)
    para que las baterías herméticas capturen esta pasada como cualquier
    otra invocación ffmpeg. FALLBACK 0.5 ante CUALQUIER fallo (timeout,
    rc!=0, sin muestras, ffmpeg ausente) — jamás lanza ni tumba el burn.
    """
    try:
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info",
               "-t", str(max(int(sample_seconds), 1)), "-i", str(video_path),
               "-vf", "scale=64:64,signalstats,"
                      "metadata=print:key=lavfi.signalstats.YAVG",
               "-an", "-sn", "-dn", "-f", "null", "-"]
        if runner is not None:
            p = runner(cmd, timeout=max(int(timeout_s), 1))
        else:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=max(int(timeout_s), 1))
        vals = [float(m) for m in _YAVG_RE.findall(getattr(p, "stderr", "") or "")]
        if not vals:
            return 0.5
        mean = sum(vals) / len(vals)
        return min(max((mean - 16.0) / 219.0, 0.0), 1.0)
    except Exception:
        return 0.5
