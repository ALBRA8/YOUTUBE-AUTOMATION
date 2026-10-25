"""Batería de pruebas unitarias para INT-047: Pacing Controller (Ritmo de Cortes LabsIA).

Metodología ClonaKit: Fase 5 (Probar y Validar)
- Valida el cálculo de número de escenas según el ritmo (Rápido 2.5s, Normal 4.0s, Pausado 6.0s)
- Formato short vs long
- Propagación de metadatos de pacing en la creación de proyectos
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline import script_gen
from main import app

client = TestClient(app)


def test_resolve_scene_count_short():
    """Valida los cortes para formato Short (9:16)."""
    assert script_gen.resolve_scene_count("short", "fast") == 16
    assert script_gen.resolve_scene_count("short", "rapido") == 16
    assert script_gen.resolve_scene_count("short", "normal") == 10
    assert script_gen.resolve_scene_count("short", "slow") == 7
    assert script_gen.resolve_scene_count("short", "pausado") == 7


def test_resolve_scene_count_long():
    """Valida los cortes para formato Largo (16:9)."""
    assert script_gen.resolve_scene_count("long", "fast") == 36
    assert script_gen.resolve_scene_count("long", "normal") == 24
    assert script_gen.resolve_scene_count("long", "slow") == 16


def test_api_create_project_stores_pacing():
    """Valida que el endpoint /api/projects almacene el ritmo de corte en meta."""
    res = client.post("/api/projects", json={
        "mode": "idea",
        "idea": "El secreto mejor guardado de los estoicos",
        "format": "short",
        "style": "estoicismo-clasico",
        "pacing": "fast"
    })
    assert res.status_code == 200
    data = res.json()
    assert "id" in data
    assert data["meta"].get("pacing") == "fast"
