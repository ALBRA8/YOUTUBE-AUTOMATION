"""
Test P2-2: Rediseño de codificación de video (intermedios casi sin pérdida + única codificación final).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.pipeline.video import get_video_encoder, _probe_nvenc
from tests.benchmark_video_quality import run_benchmark


def test_intermediate_vs_final_video_encoder_flags():
    """P2-2: Los intermedios deben usar CRF bajo (10) y preset rápido, y el final debe usar
    calidad alta (CRF 18) y +faststart."""
    with patch.dict(os.environ, {"INTERMEDIATE_CRF": "10", "INTERMEDIATE_PRESET": "ultrafast",
                                 "VIDEO_CRF": "18", "VIDEO_PRESET": "veryfast"}):
        inter_args = get_video_encoder(final=False)
        assert "-crf" in inter_args
        crf_idx = inter_args.index("-crf")
        assert inter_args[crf_idx + 1] == "10"
        preset_idx = inter_args.index("-preset")
        assert inter_args[preset_idx + 1] == "ultrafast"

        final_args = get_video_encoder(final=True)
        assert "-crf" in final_args
        crf_idx = final_args.index("-crf")
        assert final_args[crf_idx + 1] == "18"
        preset_idx = final_args.index("-preset")
        assert final_args[preset_idx + 1] == "veryfast"
        assert "-movflags" in final_args
        mf_idx = final_args.index("-movflags")
        assert final_args[mf_idx + 1] == "+faststart"


def test_nvenc_evaluation_probe():
    """P2-2: Evaluación de aceleración por hardware NVENC."""
    with patch("video_encode.ENABLE_NVENC", False):
        with patch("video_encode._NVENC_AVAILABLE", None):
            assert _probe_nvenc() is False

    with patch("video_encode.ENABLE_NVENC", True):
        with patch("video_encode._NVENC_AVAILABLE", True):
            enc = get_video_encoder(final=True)
            assert "h264_nvenc" in enc
            assert "-cq" in enc
            assert "+faststart" in enc


def test_video_quality_benchmark_reproducible(tmp_path):
    """P2-2: El benchmark reproducible demuestra cuantitativamente que la Cadena B
    supera a la Cadena A en SSIM y PSNR (+dB) frente a la referencia original."""
    metrics = run_benchmark(tmp_path)
    assert metrics["gain"]["ssim_higher"] is True, "Cadena B debe tener mayor SSIM que Cadena A"
    assert metrics["gain"]["psnr_delta_db"] > 0, "Cadena B debe tener mayor PSNR que Cadena A"
    assert metrics["cadena_b"]["psnr_db"] >= 48.0, "Cadena B debe lograr fidelidad visual > 48 dB"


if __name__ == "__main__":
    test_intermediate_vs_final_video_encoder_flags()
    test_nvenc_evaluation_probe()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        test_video_quality_benchmark_reproducible(Path(td))
    print("PASS: test_p2_2_video_encoding_chain")
