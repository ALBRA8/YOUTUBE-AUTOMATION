"""
YOUTUBE AUTOMATION v2.30 — E-Commerce Badges & AI Cutout Compositor (INT-055 / INT-056)
Clonado limpio de v4v.ai para E-Commerce & UGC Video Ads.

INT-055: Badges y Stickers Gráficos de Conversión (Rating 4.9*, -50% OFF, Envío Gratis, Garantía).
INT-056: AI Product Cutout & Studio Background Compositor (Remoción de fondo y montaje en set 9:16).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

log = logging.getLogger("ecommerce_overlays")

BADGE_PRESETS = {
    "rating": {
        "tag": "⭐ TOP RATED",
        "tag_bg": (245, 158, 11, 255),      # Oro
        "tag_fg": (0, 0, 0, 255),
        "text": "★ ★ ★ ★ ★  4.9/5 (+14,200 Reviews)",
        "border": (245, 158, 11, 220),
    },
    "discount": {
        "tag": "🔥 OFERTA FLASH",
        "tag_bg": (239, 68, 68, 255),      # Rojo intenso
        "tag_fg": (255, 255, 255, 255),
        "text": "-50% DE DESCUENTO HOY",
        "border": (239, 68, 68, 220),
    },
    "shipping": {
        "tag": "🚚 EXPRESS",
        "tag_bg": (16, 185, 129, 255),     # Verde esmeralda
        "tag_fg": (255, 255, 255, 255),
        "text": "ENVÍO GRATIS 24/48 HORAS",
        "border": (16, 185, 129, 220),
    },
    "guarantee": {
        "tag": "🛡️ 100% SEGURO",
        "tag_bg": (59, 130, 246, 255),     # Azul eléctrico
        "tag_fg": (255, 255, 255, 255),
        "text": "GARANTÍA TOTAL DE 30 DÍAS",
        "border": (59, 130, 246, 220),
    }
}


def generate_ecommerce_badge(
    badge_type: str = "rating",
    text_main: str | None = None,
    tag: str | None = None,
    out_path: Path | None = None,
    scale: float = 1.0
) -> Path:
    """Genera un badge / sticker PNG transparente de alta conversión e-commerce (INT-055)."""
    preset = BADGE_PRESETS.get(badge_type, BADGE_PRESETS["rating"])
    tag_str = tag or preset["tag"]
    main_str = text_main or preset["text"]
    border_color = preset["border"]

    w = int(520 * scale)
    h = int(120 * scale)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # Fondo cápsula oscuro con gradiente visual simulado y borde
    bg_color = (15, 23, 42, 230)  # Slate 900 semitransparente
    radius = int(22 * scale)
    draw.rounded_rectangle([3, 3, w - 3, h - 3], radius=radius, fill=bg_color, outline=border_color, width=int(3 * scale))

    # Mini Tag
    tag_bg = preset["tag_bg"]
    tag_fg = preset["tag_fg"]
    tag_w = int(min(len(tag_str) * 11 + 24, w - 40) * scale)
    tag_h = int(28 * scale)
    tag_x = int(24 * scale)
    tag_y = int(14 * scale)
    draw.rounded_rectangle([tag_x, tag_y, tag_x + tag_w, tag_y + tag_h], radius=int(6 * scale), fill=tag_bg)
    draw.text((tag_x + int(8 * scale), tag_y + int(4 * scale)), tag_str, fill=tag_fg)

    # Texto Principal
    main_x = int(24 * scale)
    main_y = int(56 * scale)
    draw.text((main_x, main_y), main_str, fill=(255, 255, 255, 255))

    out = out_path or Path(f"backend/static/assets/badge_{badge_type}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def remove_product_background(
    image_path: Path,
    output_png: Path,
    bg_thresh: int = 238,
    feather: int = 3
) -> Path:
    """Remueve fondos claros de fotos de catálogo de e-commerce y genera un PNG transparente (INT-056)."""
    import cv2
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"No se pudo cargar la imagen: {image_path}")

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Máscara de fondo
    mask = np.zeros((h + 2, w + 2), np.uint8)
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]

    for cx, cy in corners:
        if gray[cy, cx] >= bg_thresh - 15:
            cv2.floodFill(
                img.copy(), mask, (cx, cy), (0, 0, 0),
                loDiff=(22, 22, 22), upDiff=(22, 22, 22),
                flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY
            )

    bg_mask = mask[1:h+1, 1:w+1]
    fg_mask = cv2.bitwise_not(bg_mask)

    if feather > 0:
        ksize = feather * 2 + 1
        fg_mask = cv2.GaussianBlur(fg_mask, (ksize, ksize), 0)

    b, g, r = cv2.split(img)
    rgba = cv2.merge([b, g, r, fg_mask])

    output_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_png), rgba)
    return output_png


def create_studio_background(
    width: int = 1080,
    height: int = 1920,
    style: str = "luxury_dark"
) -> Image.Image:
    """Crea un fondo de estudio cinemático 9:16 vertical."""
    # Gradiente radial con centro suavemente iluminado
    im = Image.new("RGB", (width, height), (15, 23, 42))
    draw = ImageDraw.Draw(im)

    if style == "luxury_dark":
        # Gradiente vertical elegante de azul pizarra oscuro a casi negro
        for y in range(height):
            ratio = y / height
            r = int(18 * (1 - ratio * 0.6))
            g = int(24 * (1 - ratio * 0.6))
            b = int(38 * (1 - ratio * 0.4))
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Luz de halo central (spotlight sutil)
        spotlight = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        spot_draw = ImageDraw.Draw(spotlight)
        cx, cy = width // 2, int(height * 0.48)
        max_r = int(width * 0.65)
        for r_step in range(max_r, 0, -25):
            alpha = int(40 * (1 - r_step / max_r))
            spot_draw.ellipse(
                [cx - r_step, cy - r_step, cx + r_step, cy + r_step],
                fill=(56, 189, 248, alpha)  # Cyan sutil spotlight
            )
        im = Image.alpha_composite(im.convert("RGBA"), spotlight).convert("RGB")

    elif style == "pastel_clean":
        # Fondo blanco humo / beige moderno estilo Apple / Dyson
        for y in range(height):
            ratio = y / height
            val = int(245 - 25 * ratio)
            draw.line([(0, y), (width, y)], fill=(val, val, val + 2))
    else:
        # Cyber / Neon
        for y in range(height):
            ratio = y / height
            r = int(10 + 20 * ratio)
            g = 10
            b = int(25 + 40 * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    return im


def composite_product_on_studio(
    product_img_path: Path,
    background_style: str = "luxury_dark",
    output_path: Path | None = None,
    width: int = 1080,
    height: int = 1920,
    add_shadow: bool = True
) -> Path:
    """Compone el producto recortado sobre un fondo de estudio cinemático vertical 9:16 (INT-056)."""
    # 1. Crear o cargar fondo
    bg = create_studio_background(width, height, style=background_style).convert("RGBA")

    # 2. Cargar imagen de producto
    prod_raw = Image.open(product_img_path).convert("RGBA")

    # 3. Escalar producto para ocupar ~65% del ancho del frame 9:16
    target_w = int(width * 0.65)
    ratio = target_w / float(prod_raw.width)
    target_h = int(prod_raw.height * ratio)

    # Si la altura excede el 60% del alto, restringir por alto
    if target_h > height * 0.55:
        target_h = int(height * 0.55)
        ratio = target_h / float(prod_raw.height)
        target_w = int(prod_raw.width * ratio)

    prod_resized = prod_raw.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 4. Posicionar producto en el tercio medio superior
    pos_x = (width - target_w) // 2
    pos_y = int(height * 0.42) - (target_h // 2)

    # 5. Sombra proyectada suave (Drop Shadow)
    if add_shadow:
        shadow_w = int(target_w * 0.85)
        shadow_h = int(36)
        shadow = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse([0, 0, shadow_w, shadow_h], fill=(0, 0, 0, 110))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))

        shadow_x = (width - shadow_w) // 2
        shadow_y = pos_y + target_h - int(shadow_h * 0.3)
        bg.paste(shadow, (shadow_x, shadow_y), shadow)

    # 6. Pegar producto con su canal alfa
    bg.paste(prod_resized, (pos_x, pos_y), prod_resized)

    out = output_path or product_img_path.parent / f"{product_img_path.stem}_studio.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out, quality=95)
    return out


def build_ecommerce_ffmpeg_filter(
    badge_path: Path,
    start_sec: float = 0.5,
    duration_sec: float = 6.0,
    position: str = "top"
) -> str:
    """Genera la expresión de filtro FFmpeg para incrustar el sticker de conversión animado."""
    badge_escaped = str(badge_path).replace("\\", "/").replace(":", "\\:")
    end_sec = round(start_sec + duration_sec, 2)
    enable_expr = f"between(t,{start_sec},{end_sec})"

    if position == "top":
        y_pos = "160"
    else:
        y_pos = "main_h-overlay_h-220"

    return f"overlay=x=(main_w-overlay_w)/2:y={y_pos}:enable='{enable_expr}'"
