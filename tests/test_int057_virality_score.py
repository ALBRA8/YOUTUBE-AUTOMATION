"""
Unit tests para INT-057: AI Virality Score Matrix (OpusClip & Klap Cloned)
- Virality Score (0-100)
- Hook Score, Flow Score, Value Score
- Tactical Viral Advice & Hashtags
"""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.viral_clipper import _fallback_heuristics, detect_viral_moments


def test_fallback_heuristics_includes_virality_matrix():
    """Verifica que la heurística incluya la matriz completa de viralidad."""
    segments = [
        {"start": 16.0, "end": 45.0, "text": "Este es el secreto que nadie te cuenta de YouTube."},
        {"start": 50.0, "end": 85.0, "text": "La retención de los primeros tres segundos lo es todo."},
        {"start": 90.0, "end": 125.0, "text": "Cuando aprendes a editar con ritmo, tus vistas explotan."}
    ]
    moments = _fallback_heuristics(segments, count=2, min_dur=20, max_dur=60)
    assert len(moments) == 2

    for m in moments:
        assert "virality_score" in m
        assert 50 <= m["virality_score"] <= 100
        assert "hook_score" in m
        assert 50 <= m["hook_score"] <= 100
        assert "flow_score" in m
        assert 50 <= m["flow_score"] <= 100
        assert "value_score" in m
        assert 50 <= m["value_score"] <= 100
        assert "viral_advice" in m
        assert len(m["viral_advice"]) > 10
        assert "hashtags" in m
        assert isinstance(m["hashtags"], list)
        assert len(m["hashtags"]) >= 3


@pytest.mark.anyio
@patch("services.viral_clipper.fetch_timed_transcript")
async def test_detect_viral_moments_matrix_normalized(mock_transcript):
    """Verifica que detect_viral_moments normalice y ordene los momentos con la matriz de viralidad."""
    mock_transcript.return_value = (
        {"title": "Podcast de Emprendimiento", "duration": 600, "channel": "Top Creators"},
        [
            {"start": 20.0, "end": 50.0, "text": "¿Por qué fracasa el 95% de los canales? Te lo explico."},
            {"start": 60.0, "end": 95.0, "text": "La disciplina supera al talento en creación de contenido."}
        ]
    )

    res = await detect_viral_moments("https://www.youtube.com/watch?v=mock123", count=2)
    assert res["ok"] is True
    assert res["total_moments"] >= 1
    top = res["moments"][0]

    assert top["virality_score"] >= 70
    assert "hook_score" in top
    assert "flow_score" in top
    assert "value_score" in top
    assert "viral_advice" in top
    assert "hashtags" in top
    assert top["rank"] == 1
