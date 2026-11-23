"""
Test Z2: Test hermético del endpoint lipsync-musetalk con dobles.
Verifica:
1. Camino exitoso: ejecuta sin NameError y devuelve el JSON esperado (ok=True, video_url, audio_url, etc.)
2. Fallo de ffmpeg: si subprocess.run falla con CalledProcessError, falla de forma clara y explícita.
"""
import sys
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main
from main import app
import database as db


class DummyCommunicate:
    def __init__(self, text, voice):
        self.text = text
        self.voice = voice

    async def save(self, target_path):
        Path(target_path).write_bytes(b"dummy mp3 data")


def test_lipsync_musetalk_success(tmp_path: Path, monkeypatch):
    # 1. Crear avatar de prueba en base de datos con imagen existente
    img_file = tmp_path / "avatar_test.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    avatar = db.create_avatar(name="Tester Z2", image_path=str(img_file), voice="es-ES-AlvaroNeural")
    avatar_id = avatar["id"]

    # 2. Doble para edge_tts
    import edge_tts
    monkeypatch.setattr(edge_tts, "Communicate", DummyCommunicate)

    # 3. Doble para subprocess.run (ffmpeg)
    ffmpeg_called = []
    def fake_subprocess_run(cmd, capture_output=True, check=True):
        ffmpeg_called.append(cmd)
        # Generar el archivo wav de salida esperado
        out_wav = Path(cmd[-1])
        out_wav.write_bytes(b"dummy wav data")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(main.subprocess, "run", fake_subprocess_run)

    # 4. Doble para render_avatar_animation
    import services.avatar_motion as am
    fake_render = AsyncMock(return_value={
        "ok": True,
        "engine": "liveportrait_hf",
        "space": "mock-hf-space",
        "fallback": False
    })
    monkeypatch.setattr(am, "render_avatar_animation", fake_render)

    client = TestClient(app)
    response = client.post(
        f"/api/avatars/{avatar_id}/lipsync-musetalk",
        json={"text": "Prueba de lipsync automatizada", "voice": "es-ES-AlvaroNeural"}
    )

    assert response.status_code == 200, f"Respuesta inesperada: {response.text}"
    data = response.json()
    assert data["ok"] is True
    assert data["engine"] == "LivePortrait-HF"
    assert data["space"] == "mock-hf-space"
    assert data["fallback"] is False
    assert "video_url" in data
    assert "audio_url" in data
    assert data["spoken_text"] == "Prueba de lipsync automatizada"
    assert len(ffmpeg_called) == 1
    assert "ffmpeg" in ffmpeg_called[0][0]


def test_lipsync_musetalk_fails_when_ffmpeg_fails(tmp_path: Path, monkeypatch):
    # 1. Crear avatar de prueba
    img_file = tmp_path / "avatar_test_fail.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    avatar = db.create_avatar(name="Tester Z2 Fail", image_path=str(img_file))
    avatar_id = avatar["id"]

    # 2. Doble para edge_tts
    import edge_tts
    monkeypatch.setattr(edge_tts, "Communicate", DummyCommunicate)

    # 3. Doble para subprocess.run que simula fallo en ffmpeg
    def fake_subprocess_run_fail(cmd, capture_output=True, check=True):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            output=b"",
            stderr=b"ffmpeg conversion error: invalid input codec"
        )

    monkeypatch.setattr(main.subprocess, "run", fake_subprocess_run_fail)

    # TestClient por defecto propaga excepciones del servidor
    client = TestClient(app)
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        client.post(
            f"/api/avatars/{avatar_id}/lipsync-musetalk",
            json={"text": "Fallo simulado ffmpeg"}
        )

    assert exc_info.value.returncode == 1
    assert b"ffmpeg conversion error" in exc_info.value.stderr
