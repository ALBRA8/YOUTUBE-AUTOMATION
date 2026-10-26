"""
YOUTUBE AUTOMATION v2.32 — Circle PiP Avatar Presenter (INT-058)
Inspirado en HeyGen y Synthesia.

Genera una burbuja circular estilizada del avatar (presentador flotante)
con borde brillante y sombra proyectada, y la incrusta de forma determinista
en la esquina del video (9:16 o 16:9).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable
from PIL import Image, ImageDraw, ImageFilter, ImageOps

log = logging.getLogger("avatar_pip")

BORDER_PRESETS = {
    "cyan": (56, 189, 248, 255),      # Neon Sky Blue (#38bdf8)
    "gold": (245, 158, 11, 255),      # Amber Gold (#f59e0b)
    "emerald": (16, 185, 129, 255),   # Emerald Green (#10b981)
    "purple": (168, 85, 247, 255),    # Cyber Purple (#a855f7)
    "white": (255, 255, 255, 255),    # Pure Minimalist White
}


def create_circle_avatar(
    image_path: Path,
    diameter: int = 340,
    border_color: tuple[int, int, int, int] | str = "cyan",
    border_width: int = 6,
    add_shadow: bool = True,
    output_path: Path | None = None
) -> Path:
    """Genera un avatar recortado en círculo con borde estilizado y sombra (INT-058).

    Retorna la ruta al archivo PNG transparente resultante.
    """
    if isinstance(border_color, str):
        b_color = BORDER_PRESETS.get(border_color.lower(), BORDER_PRESETS["cyan"])
    else:
        b_color = border_color

    img = Image.open(image_path).convert("RGBA")

    # 1. Recorte cuadrado centrado en el sujeto
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = int((h - min_dim) * 0.2)  # Favorecer la parte superior (rostro)
    top = max(0, min(top, h - min_dim))
    right = left + min_dim
    bottom = top + min_dim
    img_cropped = img.crop((left, top, right, bottom))

    # 2. Redimensionar al diámetro deseado
    img_resized = img_cropped.resize((diameter, diameter), Image.Resampling.LANCZOS)

    # 3. Máscara circular con anti-aliasing (supersampling 2x)
    scale = 2
    mask_large = Image.new("L", (diameter * scale, diameter * scale), 0)
    draw_mask = ImageDraw.Draw(mask_large)
    draw_mask.ellipse([0, 0, diameter * scale - 1, diameter * scale - 1], fill=255)
    mask = mask_large.resize((diameter, diameter), Image.Resampling.LANCZOS)

    # Aplicar máscara circular
    circle_im = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    circle_im.paste(img_resized, (0, 0), mask)

    # 4. Marco exterior con borde brillante
    padding = border_width + 12 if add_shadow else border_width + 2
    canvas_size = diameter + (padding * 2)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

    offset = padding

    # 5. Sombra proyectada suave detrás del círculo
    if add_shadow:
        shadow_box = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow_box)
        s_margin = padding - 4
        s_draw.ellipse(
            [s_margin, s_margin + 6, s_margin + diameter + 8, s_margin + diameter + 14],
            fill=(0, 0, 0, 140)
        )
        shadow_blurred = shadow_box.filter(ImageFilter.GaussianBlur(8))
        canvas.paste(shadow_blurred, (0, 0), shadow_blurred)

    # 6. Pegar el avatar circular
    canvas.paste(circle_im, (offset, offset), circle_im)

    # 7. Dibujar el aro/borde circular exterior
    draw_border = ImageDraw.Draw(canvas)
    draw_border.ellipse(
        [offset, offset, offset + diameter - 1, offset + diameter - 1],
        outline=b_color,
        width=border_width
    )

    out = output_path or image_path.parent / f"{image_path.stem}_circle_pip.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG")
    return out


def build_pip_overlay_filter(
    avatar_png_path: Path,
    video_w: int = 1080,
    video_h: int = 1920,
    position: str = "bottom_right",
    margin_x: int = 36,
    margin_y: int = 160
) -> str:
    """Genera la expresión del filtro FFmpeg para incrustar el avatar en PiP."""
    # Coordenadas según la esquina deseada
    pos = position.lower()
    if pos == "bottom_left":
        coords = f"x={margin_x}:y=main_h-overlay_h-{margin_y}"
    elif pos == "top_right":
        coords = f"x=main_w-overlay_w-{margin_x}:y={margin_y}"
    elif pos == "top_left":
        coords = f"x={margin_x}:y={margin_y}"
    else:  # bottom_right por defecto
        coords = f"x=main_w-overlay_w-{margin_x}:y=main_h-overlay_h-{margin_y}"

    return f"overlay={coords}"


def apply_pip_to_video(
    video_in: Path,
    avatar_png: Path,
    video_out: Path,
    position: str = "bottom_right",
    runner: Callable[[list[str]], Any] | None = None
) -> Path:
    """Superpone el presentador circular sobre el video."""
    overlay_filter = build_pip_overlay_filter(avatar_png, position=position)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(avatar_png),
        "-filter_complex", f"[0:v][1:v]{overlay_filter}[v]",
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        str(video_out)
    ]

    if runner:
        runner(cmd)
    else:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg PiP overlay falló: {res.stderr[-300:]}")

    return video_out
