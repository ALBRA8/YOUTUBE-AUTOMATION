"""Batería de pruebas unitarias para INT-046: B-Roll Auto-Inserter & Overlay Layering.

Metodología ClonaKit: Fase 5 (Probar y Validar)
- Planificación de intervalos seguros de B-roll (respetando ganchos iniciales y llamadas a la acción)
- Extracción heurística y por IA de conceptos visuales cinemáticos
- Generación de B-Roll sintético como fallback seguro de alta fidelidad
- Composición multi-capa FFmpeg asegurando subtítulos en la capa superior
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import broll_overlay


def test_plan_broll_intervals():
    """Valida que los intervalos de B-roll no pisen el gancho (primeros 3.5s) ni el final."""
    # Video corto (<7s) no debe tener B-roll
    assert broll_overlay.plan_broll_intervals(5.0) == []

    # Video de 30s con 1 B-roll
    intervals = broll_overlay.plan_broll_intervals(30.0, count=1, broll_duration=3.0)
    assert len(intervals) == 1
    iv = intervals[0]
    assert iv["start"] >= 3.5
    assert iv["end"] <= 30.0 - 1.0
    assert iv["duration"] == 3.0

    # Video de 60s con 2 B-rolls espaciados
    intervals_2 = broll_overlay.plan_broll_intervals(60.0, count=2, broll_duration=3.5)
    assert len(intervals_2) == 2
    assert intervals_2[0]["start"] < intervals_2[1]["start"]
    assert intervals_2[1]["end"] <= 59.0


def test_extract_broll_keywords_heuristic():
    """Valida la detección de conceptos visuales recurrentes en español/inglés."""
    # Dinero / Finanzas
    kw_money = broll_overlay.extract_broll_keywords_heuristic("Cómo ganar un millón de dólares invirtiendo joven")
    assert any("money" in k or "wealth" in k for k in kw_money)

    # Tecnología / Software / IA
    kw_tech = broll_overlay.extract_broll_keywords_heuristic("El futuro de la inteligencia artificial y el código")
    assert any("computer" in k or "intelligence" in k for k in kw_tech)

    # Bienes raíces
    kw_real = broll_overlay.extract_broll_keywords_heuristic("Compré mi primera casa y departamento")
    assert any("real estate" in k or "architecture" in k for k in kw_real)

    # Texto neutro genera fallback visual seguro
    kw_fallback = broll_overlay.extract_broll_keywords_heuristic("")
    assert len(kw_fallback) > 0


def test_generate_synthetic_broll():
    """Valida que FFmpeg genere un clip de B-roll dinámico utilizable cuando no hay internet."""
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "synth_broll.mp4"
        ok = broll_overlay.generate_synthetic_broll(dest, duration=1.5)
        assert ok is True
        assert dest.is_file()
        assert dest.stat().st_size > 1000


def test_prepare_broll_clip_offline_fallback():
    """Valida que prepare_broll_clip no falle nunca, cayendo al fallback sintético."""
    import asyncio
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "test_broll.mp4"
        # Mock de Pexels para simular offline o sin API key
        with patch.object(broll_overlay, "fetch_stock_video_pexels", return_value=False):
            ok = asyncio.run(broll_overlay.prepare_broll_clip("luxury car", duration=1.0, out_path=dest))
            assert ok is True
            assert dest.is_file()
            assert dest.stat().st_size > 500
