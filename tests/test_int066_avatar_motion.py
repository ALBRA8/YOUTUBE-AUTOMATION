import sys
from pathlib import Path
import pytest
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.avatar_motion import (
    generate_eyelid_blink_frame,
    generate_mouth_lip_frame,
    animate_liveportrait_local,
    extract_audio_amplitude_envelope
)
from starlette.testclient import TestClient
from main import app
import database as db

client = TestClient(app)

def test_generate_eyelid_blink_frame():
    im = Image.new("RGBA", (200, 200), (200, 180, 160, 255))
    blink_img = generate_eyelid_blink_frame(im, blink_factor=0.8)
    assert blink_img.size == (200, 200)

def test_generate_mouth_lip_frame():
    im = Image.new("RGBA", (200, 200), (200, 180, 160, 255))
    mouth_img = generate_mouth_lip_frame(im, mouth_open_factor=0.7)
    assert mouth_img.size == (200, 200)

def test_animate_liveportrait_local(tmp_path: Path):
    src_img = tmp_path / "avatar_face.png"
    im = Image.new("RGBA", (256, 256), (220, 190, 170, 255))
    im.save(src_img)

    out_mp4 = tmp_path / "avatar_loop.mp4"
    res = animate_liveportrait_local(src_img, out_mp4, duration_sec=1.0, fps=15)
    assert res.is_file()
    assert res.stat().st_size > 1000

def test_api_avatar_animate_liveportrait(tmp_path: Path):
    # Crear un avatar dummy con imagen
    img_file = tmp_path / "dummy_av.png"
    Image.new("RGBA", (256, 256), (180, 150, 120, 255)).save(img_file)

    av = db.create_avatar(name="Tester LivePortrait", image_path=str(img_file))
    aid = av["id"]

    resp = client.post(f"/api/avatars/{aid}/animate-liveportrait", json={"duration_sec": 1.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["engine"] == "LivePortrait"
    assert "video_url" in data
