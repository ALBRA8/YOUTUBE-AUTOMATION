import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.multilang_dubber import (
    translate_text,
    synthesize_dubbed_speech,
    swap_video_audio,
    DUB_LANGUAGES
)
from starlette.testclient import TestClient
from main import app

client = TestClient(app)

def test_dub_languages_catalog():
    assert "en" in DUB_LANGUAGES
    assert "pt" in DUB_LANGUAGES
    assert "fr" in DUB_LANGUAGES
    assert "de" in DUB_LANGUAGES
    assert "ja" in DUB_LANGUAGES

@pytest.mark.asyncio
async def test_translate_text_fallback():
    src = "¡Detente un segundo! No cometas este grave error."
    res = await translate_text(src, "en")
    assert "Stop for a second" in res or "mistake" in res

def test_api_dubbing_languages():
    resp = client.get("/api/dubbing/languages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "en" in data["languages"]

def test_api_dubbing_translate():
    resp = client.post("/api/dubbing/translate", json={
        "text": "Haz clic en el enlace y aprovecha el descuento",
        "target_lang": "en"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["target_lang"] == "en"
    assert len(data["translated_text"]) > 5
