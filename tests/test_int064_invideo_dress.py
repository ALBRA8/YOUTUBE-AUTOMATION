import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.invideo_dress import (
    auto_dress_timeline,
    detect_sfx_cues_in_text
)
from starlette.testclient import TestClient
from main import app

client = TestClient(app)

def test_detect_sfx_cues():
    assert "ding" in detect_sfx_cues_in_text("Aprovecha este descuento del 50% hoy mismo")
    assert "ding" in detect_sfx_cues_in_text("Cuesta solo $19.99 dólares")
    assert "pop" in detect_sfx_cues_in_text("¡Cuidado con este grave error!")
    assert len(detect_sfx_cues_in_text("Un día soleado en el parque")) == 0

def test_auto_dress_timeline():
    scenes = [
        {"scene_id": "s1", "duration_sec": 3.8, "narration": "¡Cuidado! Este error te está costando más de $500 al mes."},
        {"scene_id": "s2", "duration_sec": 4.0, "narration": "La mayoría de personas no sabe cómo invertir su dinero."},
        {"scene_id": "s3", "duration_sec": 3.2, "narration": "Haz clic abajo para comenzar ahora."}
    ]
    res = auto_dress_timeline(scenes=scenes)
    assert res["ok"] is True
    summary = res["timeline_summary"]
    assert summary["scene_count"] == 3
    assert summary["broll_count"] >= 1
    assert summary["sfx_count"] >= 2
    assert "%" in summary["predicted_retention_boost"]

def test_api_invideo_auto_dress():
    resp = client.post("/api/invideo/auto-dress", json={
        "scenes": [
            {"scene_id": "s1", "duration_sec": 3.5, "narration": "Aprende a programar con IA en 30 días."},
            {"scene_id": "s2", "duration_sec": 4.0, "narration": "El método probado para ganar $1000 extra al mes."}
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "broll_cutaways" in data
    assert "sfx_events" in data

def test_api_invideo_preview_sfx():
    resp = client.post("/api/invideo/preview-sfx", json={"type": "whoosh"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["type"] == "whoosh"
    assert "sfx_url" in data
