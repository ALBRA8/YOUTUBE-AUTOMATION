"""
Test P2-5: Verificación de -movflags +faststart para streaming en el reproductor del panel.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from backend.pipeline.video import get_video_encoder


def test_final_encoder_includes_faststart():
    """P2-5: El codificador final debe incluir -movflags +faststart."""
    enc = get_video_encoder(final=True)
    assert "-movflags" in enc
    idx = enc.index("-movflags")
    assert enc[idx + 1] == "+faststart"


def test_rendered_mp4_has_moov_before_mdat(tmp_path):
    """P2-5: Comprueba físicamente que un MP4 generado con faststart ubica
    el átomo 'moov' antes de 'mdat' para permitir streaming progresivo HTTP."""
    out_video = tmp_path / "streamable.mp4"
    enc = get_video_encoder(final=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=15",
        *enc, str(out_video)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    assert out_video.exists()

    with open(out_video, "rb") as f:
        header = f.read(65536)

    pos_moov = header.find(b"moov")
    pos_mdat = header.find(b"mdat")

    assert pos_moov != -1, "No se encontró el átomo moov en la cabecera"
    assert pos_mdat != -1, "No se encontró el átomo mdat en el archivo"
    assert pos_moov < pos_mdat, f"moov ({pos_moov}) debe preceder a mdat ({pos_mdat}) para streaming web"


if __name__ == "__main__":
    test_final_encoder_includes_faststart()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        test_rendered_mp4_has_moov_before_mdat(Path(td))
    print("PASS: test_p2_5_faststart")
