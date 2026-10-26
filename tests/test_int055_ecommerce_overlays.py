"""
Test Unitario para INT-055 e INT-056:
- INT-055: Badges y Stickers Gráficos de Conversión (Rating, Discount, Shipping, Guarantee)
- INT-056: AI Product Cutout & Studio Background Compositor
"""
import pytest
from pathlib import Path
import numpy as np
from PIL import Image

from services.ecommerce_overlays import (
    generate_ecommerce_badge,
    remove_product_background,
    create_studio_background,
    composite_product_on_studio,
    build_ecommerce_ffmpeg_filter,
    BADGE_PRESETS
)


def test_generate_all_badge_presets(tmp_path: Path):
    """Verifica que todos los presets de badges se generen correctamente en RGBA."""
    for badge_type in BADGE_PRESETS:
        out_file = tmp_path / f"badge_{badge_type}.png"
        res = generate_ecommerce_badge(
            badge_type=badge_type,
            out_path=out_file
        )
        assert res.is_file()
        assert res.stat().st_size > 500

        with Image.open(res) as img:
            assert img.mode == "RGBA"
            assert img.width == 520
            assert img.height == 120


def test_generate_custom_badge(tmp_path: Path):
    """Verifica la personalización de texto y tag en el badge."""
    out_file = tmp_path / "custom_badge.png"
    res = generate_ecommerce_badge(
        badge_type="discount",
        text_main="¡Solo por hoy 70% Menos!",
        tag="🔥 LIQUIDACIÓN",
        out_path=out_file,
        scale=1.5
    )
    assert res.is_file()
    with Image.open(res) as img:
        assert img.width == int(520 * 1.5)
        assert img.height == int(120 * 1.5)


def test_remove_product_background(tmp_path: Path):
    """Verifica la remoción de fondo claro en fotos de catálogo sintéticas."""
    # Crear imagen sintética: 300x300 blanca con un círculo rojo en el centro
    synth_raw = tmp_path / "product_white_bg.jpg"
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    # Dibujar producto en el centro (círculo azul)
    y, x = np.ogrid[:300, :300]
    mask = (x - 150) ** 2 + (y - 150) ** 2 <= 60 ** 2
    arr[mask] = [20, 40, 220]
    Image.fromarray(arr).save(synth_raw)

    out_cutout = tmp_path / "product_cutout.png"
    res = remove_product_background(synth_raw, out_cutout, bg_thresh=240, feather=2)
    assert res.is_file()

    with Image.open(res) as cut:
        assert cut.mode == "RGBA"
        # La esquina debe ser transparente (alfa = 0)
        corner_pixel = cut.getpixel((5, 5))
        assert corner_pixel[3] == 0
        # El centro debe ser opaco (alfa > 200)
        center_pixel = cut.getpixel((150, 150))
        assert center_pixel[3] > 200


def test_create_studio_background():
    """Verifica la creación del fondo de estudio vertical 9:16."""
    bg_dark = create_studio_background(width=540, height=960, style="luxury_dark")
    assert bg_dark.size == (540, 960)

    bg_pastel = create_studio_background(width=540, height=960, style="pastel_clean")
    assert bg_pastel.size == (540, 960)


def test_composite_product_on_studio(tmp_path: Path):
    """Verifica la composición del producto sobre el set 9:16 con sombra."""
    # Crear producto transparente
    prod_png = tmp_path / "item.png"
    prod_im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(prod_im)
    draw.rectangle([20, 20, 180, 180], fill=(255, 100, 50, 255))
    prod_im.save(prod_png)

    out_comp = tmp_path / "final_composite.jpg"
    res = composite_product_on_studio(
        product_img_path=prod_png,
        background_style="luxury_dark",
        output_path=out_comp,
        width=540,
        height=960,
        add_shadow=True
    )
    assert res.is_file()
    with Image.open(res) as final_img:
        assert final_img.size == (540, 960)


def test_build_ecommerce_ffmpeg_filter():
    """Verifica la expresión de overlay FFmpeg."""
    p = Path("C:/videos/badge.png")
    filter_str = build_ecommerce_ffmpeg_filter(p, start_sec=1.0, duration_sec=4.0, position="top")
    assert "overlay=x=(main_w-overlay_w)/2:y=160" in filter_str
    assert "between(t,1.0,5.0)" in filter_str


def test_api_product_badge_endpoint():
    """Verifica el endpoint POST /api/product/badge."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.post("/api/product/badge", json={
        "type": "discount",
        "text": "-40% OFF HOY",
        "tag": "OFERTA FLASH"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "badge_discount.png" in data["badge_url"]
