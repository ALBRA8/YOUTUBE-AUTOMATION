# -*- coding: utf-8 -*-
"""Test hermético de soporte NVENC para renders intermedios en video_encode.py."""
import sys
from pathlib import Path
from unittest.mock import patch

# Añadir backend al path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import video_encode


def test_nvenc_used_for_intermediates_when_available():
    """Si NVENC está disponible, los renders intermedios deben aprovecharlo con preset p1."""
    with patch.object(video_encode, "_probe_nvenc", return_value=True):
        args = video_encode.get_video_encoder(final=False)
        assert "-c:v" in args
        idx = args.index("-c:v")
        assert args[idx + 1] == "h264_nvenc"
        preset_idx = args.index("-preset")
        assert args[preset_idx + 1] == "p1"
        assert "-cq" in args
        # Los intermedios no deben tener faststart (overhead innecesario antes del mux final)
        assert "+faststart" not in args


def test_fallback_to_libx264_when_nvenc_unavailable():
    """Si NVENC no está disponible, los renders intermedios deben usar libx264."""
    with patch.object(video_encode, "_probe_nvenc", return_value=False):
        args = video_encode.get_video_encoder(final=False)
        assert "-c:v" in args
        idx = args.index("-c:v")
        assert args[idx + 1] == "libx264"
        assert "-crf" in args
        preset_idx = args.index("-preset")
        assert args[preset_idx + 1] == "ultrafast"
