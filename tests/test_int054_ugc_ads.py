"""
Unit tests for INT-054: UGC & E-Commerce Ad Generator (v4v.ai Cloned)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import ugc_ad_generator

def test_scrape_product_info_from_text():
    """Verify scrape_product_info parses raw text into structured product info."""
    raw = "Auriculares Inalámbricos Pro ANC\nCancelación activa de ruido con 40 horas de batería."
    info = ugc_ad_generator.scrape_product_info(raw)
    assert info["name"] == "Auriculares Inalámbricos Pro ANC"
    assert "Cancelación activa" in info["description"]
    assert info["is_url"] is False

def test_generate_ugc_script_angles():
    """Verify generate_ugc_script produces 4-scene conversion structure across angles."""
    product = {
        "name": "Mochila Antirrobo Viajera",
        "description": "Impermeable con puerto USB y candado TSA integrado.",
        "price": "$49.99"
    }

    # Angle: 3_reasons
    ad_reasons = ugc_ad_generator.generate_ugc_script(product, angle="3_reasons", duration_sec=40)
    assert len(ad_reasons["scenes"]) == 4
    assert "Mochila Antirrobo Viajera" in ad_reasons["full_script"]
    assert "Tres razones" in ad_reasons["full_script"]
    assert "$49.99" in ad_reasons["full_script"]

    # Angle: dont_buy_before
    ad_warning = ugc_ad_generator.generate_ugc_script(product, angle="dont_buy_before")
    assert "¡No compres" in ad_warning["full_script"]

def test_api_create_project_product_mode():
    """Verify backend accepts mode='product' and creates project with UGC script."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    payload = {
        "mode": "product",
        "url": "Termo Inteligente con Pantalla LED",
        "angle": "3_reasons",
        "auto_start": False,
        "format": "short"
    }

    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "product"
    assert "UGC Ad:" in data["title"]
    assert "Termo Inteligente" in data["title"]
    assert data["format"] == "short"

def test_api_product_scrape_endpoint():
    """Verify POST /api/product/scrape endpoint returns parsed product data."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.post("/api/product/scrape", json={"text": "Lámpara Solar Jardín LED"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["product"]["name"] == "Lámpara Solar Jardín LED"
