"""
Unit tests para INT-058: Circle PiP Avatar Presenter (HeyGen & Synthesia Cloned)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.avatar_pip import (
    create_circle_avatar,
    build_pip_overlay_filter,
    apply_pip_to_video,
    BORDER_PRESETS
)


def test_create_circle_avatar(tmp_path: Path):
    """Verifica que el avatar circular se recorte con canal alfa, borde y sombra."""
    # Crear imagen sintética cuadrada
    src = tmp_path / "avatar_source.png"
    im = Image.new("RGB", (400, 400), (45, 80, 200))
    im.save(src)

    out = tmp_path / "avatar_circle.png"
    res = create_circle_avatar(
        src,
        diameter=300,
        border_color="cyan",
        border_width=6,
        add_shadow=True,
        output_path=out
    )
    assert res.is_file()

    with Image.open(res) as img:
        assert img.mode == "RGBA"
        # Debe ser más grande que el diámetro debido al padding del borde y sombra
        assert img.width > 300
        assert img.height > 300
        # Esquina exterior debe ser transparente
        corner = img.getpixel((2, 2))
        assert corner[3] == 0
        # El centro debe ser opaco
        center = img.getpixel((img.width // 2, img.height // 2))
        assert center[3] == 255


def test_border_presets_exist():
    """Verifica que todos los colores de borde estén disponibles."""
    for key, color in BORDER_PRESETS.items():
        assert len(color) == 4
        assert color[3] == 255


def test_build_pip_overlay_filter():
    """Verifica las coordenadas del filtro overlay para diferentes esquinas."""
    p = Path("C:/assets/avatar_pip.png")
    f_br = build_pip_overlay_filter(p, position="bottom_right", margin_x=40, margin_y=160)
    assert "x=main_w-overlay_w-40:y=main_h-overlay_h-160" in f_br

    f_bl = build_pip_overlay_filter(p, position="bottom_left", margin_x=30, margin_y=150)
    assert "x=30:y=main_h-overlay_h-150" in f_bl

    f_tr = build_pip_overlay_filter(p, position="top_right", margin_x=25, margin_y=50)
    assert "x=main_w-overlay_w-25:y=50" in f_tr


def test_apply_pip_to_video_runner_mock(tmp_path: Path):
    """Verifica que apply_pip_to_video construya y ejecute el comando FFmpeg correcto."""
    v_in = tmp_path / "in.mp4"
    v_out = tmp_path / "out.mp4"
    av_png = tmp_path / "avatar.png"
    v_in.touch()
    av_png.touch()

    runner = MagicMock()
    apply_pip_to_video(v_in, av_png, v_out, position="bottom_right", runner=runner)
    assert runner.called
    cmd = runner.call_args[0][0]
    assert "ffmpeg" in cmd
    assert "-filter_complex" in cmd
    assert any("overlay=" in arg for arg in cmd)


def test_api_avatar_circle_pip(tmp_path: Path):
    """Verifica el endpoint POST /api/avatars/{avatar_id}/circle-pip."""
    from fastapi.testclient import TestClient
    from main import app
    import database as db

    # Crear imagen de avatar mock
    mock_avatar_img = tmp_path / "mock_portrait.png"
    im = Image.new("RGB", (256, 256), (200, 100, 50))
    im.save(mock_avatar_img)

    av = db.create_avatar(
        name="Alex Tech",
        description="Tech host",
        image_path=str(mock_avatar_img)
    )

    client = TestClient(app)
    resp = client.post(f"/api/avatars/{av['id']}/circle-pip", json={"border_color": "gold"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert f"avatar_pip_{av['id']}_gold.png" in data["pip_url"]
