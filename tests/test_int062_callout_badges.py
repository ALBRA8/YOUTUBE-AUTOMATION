import sys
from pathlib import Path
import pytest
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ecommerce_overlays import (
    generate_product_callout_layer,
    build_callouts_ffmpeg_filter,
    FEATURE_PRESETS
)
from starlette.testclient import TestClient
from main import app

client = TestClient(app)

def test_feature_presets_available():
    assert "battery" in FEATURE_PRESETS
    assert "waterproof" in FEATURE_PRESETS
    assert "power" in FEATURE_PRESETS
    assert "anc" in FEATURE_PRESETS
    assert "materials" in FEATURE_PRESETS

def test_generate_product_callout_layer(tmp_path: Path):
    out_file = tmp_path / "test_callouts.png"
    callouts = [
        {"preset": "battery", "target_x": 300, "target_y": 600, "direction": "top_right"},
        {"preset": "waterproof", "target_x": 700, "target_y": 1200, "direction": "bottom_left"},
    ]
    p = generate_product_callout_layer(
        callouts=callouts,
        canvas_size=(1080, 1920),
        output_path=out_file
    )
    assert p.is_file()
    with Image.open(p) as img:
        assert img.size == (1080, 1920)
        assert img.mode == "RGBA"

def test_build_callouts_ffmpeg_filter(tmp_path: Path):
    f_path = tmp_path / "callouts.png"
    filt = build_callouts_ffmpeg_filter(f_path, start_sec=2.0, duration_sec=4.5)
    assert "between(t,2.0,6.5)" in filt
    assert "overlay=0:0" in filt

def test_api_product_callout_layer():
    resp = client.post("/api/product/callout-layer", json={
        "callouts": [
            {"preset": "battery", "target_x": 400, "target_y": 800, "direction": "top_right"},
            {"preset": "anc", "target_x": 600, "target_y": 1100, "direction": "top_left"}
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["callouts_count"] == 2
    assert "callouts_url" in data
