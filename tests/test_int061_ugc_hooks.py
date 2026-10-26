import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ugc_hooks import (
    generate_multi_angle_hooks,
    build_ab_variants,
    HOOK_ANGLES
)
from starlette.testclient import TestClient
from main import app

client = TestClient(app)

def test_generate_multi_angle_hooks_structure():
    hooks = generate_multi_angle_hooks(
        name="Lámpara Sunset Lamp",
        problem="habitaciones oscuras y fotos aburridas",
        action="tomando fotos con luz normal",
        benefit="tener fotos de revista al instante"
    )

    assert len(hooks) == 5
    # Debería estar ordenado por stop-rate descendente
    assert hooks[0]["predicted_stop_rate"] >= hooks[1]["predicted_stop_rate"]
    for h in hooks:
        assert "Lámpara Sunset Lamp" in h["hook_text"]
        assert h["duration_sec"] > 0
        assert len(h["visual_cue"]) > 5
        assert len(h["visual_prompt"]) > 5
        assert h["predicted_stop_rate"] >= 80

def test_generate_multi_angle_hooks_fallback():
    hooks = generate_multi_angle_hooks()
    assert len(hooks) == 5
    for h in hooks:
        assert len(h["hook_text"]) > 10
        assert h["predicted_stop_rate"] > 0

def test_build_ab_variants():
    product = "Mini Proyector Portátil"
    body = "Cuenta con resolución 4K y altavoces estéreo incorporados para convertir cualquier pared en un cine."
    cta = "Toca el enlace de abajo y aprovecha el descuento del 40% hoy mismo."

    variants = build_ab_variants(
        product_name=product,
        base_body=body,
        base_cta=cta
    )

    assert len(variants) == 5
    letters = [v["variant_letter"] for v in variants]
    assert letters == ["A", "B", "C", "D", "E"]

    for v in variants:
        assert v["variant_id"].startswith("variant_")
        assert len(v["scenes"]) == 3
        assert v["scenes"][0]["type"] == "hook"
        assert v["scenes"][1]["type"] == "body"
        assert v["scenes"][2]["type"] == "cta"
        assert v["total_duration_sec"] > 15.0
        assert body in v["full_script"]
        assert cta in v["full_script"]

def test_api_multi_angle_hooks():
    resp = client.post("/api/ugc/multi-angle-hooks", json={
        "product_name": "Auriculares Cancelación Ruido Pro",
        "problem": "ruido constante en la oficina",
        "action": "usando auriculares normales",
        "benefit": "silencio total y máxima concentración"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["hooks"]) == 5
    assert "Auriculares Cancelación Ruido Pro" in data["hooks"][0]["hook_text"]

def test_api_ab_variants():
    resp = client.post("/api/ugc/ab-variants", json={
        "product_name": "Humidificador Volcán LED",
        "base_body": "Con efecto de llama realista y difusor ultrasónico para aromaterapia.",
        "base_cta": "Consíguelo con 50% de descuento en el link de abajo."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["variants"]) == 5
    assert data["variants"][0]["variant_letter"] == "A"
    assert "Humidificador Volcán LED" in data["variants"][0]["scenes"][0]["narration"]
