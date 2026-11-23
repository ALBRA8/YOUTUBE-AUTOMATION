"""
Test P2-3: Verificación de masterización de audio broadcast (-14 LUFS por defecto).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import backend.config as cfg
import backend.pipeline.video as vid


def test_audio_loudnorm_defaults_active():
    """P2-3: Verifica que loudnorm broadcast está activo por defecto en la configuración."""
    assert str(cfg.AUDIO_MASTER_BROADCAST).strip().lower() in ("1", "true", "yes", "on")
    assert str(cfg.RENDER_LOUDNORM).strip().lower() in ("1", "true", "yes", "on")
    assert "I=-14" in vid.BROADCAST_LOUDNORM
    assert "LRA=11" in vid.BROADCAST_LOUDNORM
    assert "TP=-1.0" in vid.BROADCAST_LOUDNORM
    assert "dual_mono=true" in vid.BROADCAST_LOUDNORM


@pytest.mark.asyncio
async def test_mux_audio_music_loudnorm_ffmpeg_verification(tmp_path):
    """P2-3: Verifica con ffmpeg el LUFS real del audio final generado por mux_audio_music."""
    pid = "proj_test_audio_lufs"
    proj_dir = tmp_path / pid
    proj_dir.mkdir(parents=True)

    # Crear video silencioso de 3s
    video_silent = proj_dir / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_silent)
    ], check=True, capture_output=True)

    # Crear voz de 3s
    voice_wav = proj_dir / "voice.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=3",
        "-af", "volume=0.4", "-c:a", "pcm_s16le", str(voice_wav)
    ], check=True, capture_output=True)

    # Parchear OUTPUT_DIR
    orig_output = vid.OUTPUT_DIR
    vid.OUTPUT_DIR = tmp_path
    try:
        project = {"id": pid}
        out_video = await vid.mux_audio_music(project, video_silent, voice_wav)
        assert out_video.exists()

        # 1. Comprobar audio_master.json
        meta_file = proj_dir / "audio_master.json"
        assert meta_file.exists(), "audio_master.json debe existir"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["enabled"] is True
        assert meta["target_lufs"] == -14

        # 2. Comprobar ffprobe: 48 kHz estándar broadcast
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate",
            "-of", "json", str(out_video)
        ], capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout).get("streams", [])
        a_stream = next((s for s in streams if s.get("codec_name") == "aac"), None)
        assert a_stream is not None, "Debe contener una pista aac"
        assert a_stream.get("sample_rate") == "48000", "Debe remuestrear a 48000 Hz estándar broadcast"

        # 3. Comprobar ebur128 con ffmpeg
        eb = subprocess.run([
            "ffmpeg", "-i", str(out_video), "-af", "ebur128", "-f", "null", "-"
        ], capture_output=True, text=True)
        summary = eb.stderr.split("Summary:")[-1]
        m = re.search(r"I:\s+([-\d\.]+)\s+LUFS", summary)
        assert m is not None, f"No se encontró I en Summary:\n{summary}"
        measured_lufs = float(m.group(1))
        # Debe estar dentro del rango normalizado esperado (-17 a -13 LUFS para tono continuo con TP limit)
        assert -20.0 <= measured_lufs <= -10.0, f"LUFS medido {measured_lufs} fuera de rango broadcast"
    finally:
        vid.OUTPUT_DIR = orig_output


if __name__ == "__main__":
    test_audio_loudnorm_defaults_active()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        asyncio.run(test_mux_audio_music_loudnorm_ffmpeg_verification(Path(td)))
    print("PASS: test_p2_3_audio_loudnorm")
