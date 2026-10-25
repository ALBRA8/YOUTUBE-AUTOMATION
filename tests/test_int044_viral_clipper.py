"""
Tests para INT-044: Detector de Momentos Virales (Long-to-Shorts)
Inspirado en OpenShorts (mutonby/openshorts).
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from services import viral_clipper
from main import app

client = TestClient(app)


def test_vtt_parsing():
    sample_vtt = """WEBVTT
Kind: captions
Language: es

00:00:02.000 --> 00:00:06.500
Este es el secreto que nadie te cuenta sobre los negocios

00:00:06.500 --> 00:00:11.200
La mayoría de las personas se rinde antes de ver resultados
"""
    blocks = viral_clipper.parse_vtt(sample_vtt)
    assert len(blocks) == 2
    assert blocks[0]["start"] == 2.0
    assert blocks[0]["end"] == 6.5
    assert "secreto" in blocks[0]["text"]
    assert blocks[1]["start"] == 6.5
    assert blocks[1]["end"] == 11.2


def test_group_segments():
    blocks = [
        {"start": 1.0, "end": 4.0, "text": "Parte 1"},
        {"start": 4.0, "end": 8.0, "text": "Parte 2"},
        {"start": 8.0, "end": 28.0, "text": "Parte 3"},
        {"start": 30.0, "end": 40.0, "text": "Parte 4"},
    ]
    grouped = viral_clipper.group_segments(blocks, target_duration=20.0)
    assert len(grouped) >= 2
    assert grouped[0]["start"] == 1.0
    assert "Parte 1" in grouped[0]["text"]
    assert "Parte 2" in grouped[0]["text"]


def test_fallback_heuristics():
    segments = [
        {"start": 10.0, "end": 30.0, "text": "Introducción irrelevante."},
        {"start": 35.0, "end": 75.0, "text": "La clave real para ser millonario está en el apalancamiento."},
        {"start": 80.0, "end": 120.0, "text": "Si no construyes tu sueño, alguien te contratará para construir el suyo."},
        {"start": 130.0, "end": 170.0, "text": "El error que cometen todos los principiantes al invertir dinero."},
    ]
    moments = viral_clipper._fallback_heuristics(segments, count=3, min_dur=20, max_dur=60)
    assert len(moments) <= 3
    assert all("virality_score" in m for m in moments)
    assert all("hook" in m for m in moments)
    assert all(m["virality_score"] >= 80 for m in moments)


@pytest.mark.anyio
async def test_detect_viral_moments_orchestration():
    mock_meta = {
        "title": "Podcast de Negocios #42",
        "uploader": "Emprendedores",
        "duration": 1800,
        "view_count": 50000,
        "thumbnail": "https://example.com/thumb.jpg"
    }
    mock_segments = [
        {"start": 30.0, "end": 75.0, "text": "El secreto de la disciplina es no depender de la motivación."},
        {"start": 100.0, "end": 145.0, "text": "Tres hábitos que cambiaron mi productividad para siempre."},
    ]

    with patch("services.viral_clipper.fetch_timed_transcript", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_meta, mock_segments)
        res = await viral_clipper.detect_viral_moments("https://www.youtube.com/watch?v=dQw4w9WgXcQ", count=2)
        assert res["ok"] is True
        assert res["source"]["title"] == "Podcast de Negocios #42"
        assert len(res["moments"]) > 0
        m1 = res["moments"][0]
        assert "virality_score" in m1
        assert m1["duration"] > 0


def test_api_clipper_create_project():
    payload = {
        "title": "Short: El secreto de la disciplina",
        "hook": "La disciplina vence al talento",
        "summary": "Explicación del hábito de la constancia",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "video_url": "/api/renders/short_123.mp4",
        "start": 30.0,
        "end": 75.0
    }
    resp = client.post("/api/clipper/create-project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["project"]["title"] == "Short: El secreto de la disciplina"
    assert data["project"]["mode"] == "url"
    assert data["project"]["format"] == "short"
    assert data["project"]["video_url"] == "/api/renders/short_123.mp4"
