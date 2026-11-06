"""
Test P2-4: Medición de jitter en Ken Burns zoompan y control de escalado para 4K.
"""
from __future__ import annotations

import math
from pathlib import Path
import pytest

from backend.pipeline.video import safe_kenburns_scale, scene_clip_cmd


def test_safe_kenburns_scale_bounds():
    """P2-4: safe_kenburns_scale debe subir la resolución intermedia para reducir jitter,
    pero nunca superar max_dim (4320 px) para prevenir OOM en 4K."""
    # Caso 1080p vertical (Shorts: 1080x1920)
    sw, sh = safe_kenburns_scale(1080, 1920, target_factor=2.5, max_dim=4320)
    assert max(sw, sh) <= 4320, f"Dimensión {max(sw, sh)} supera tope 4320"
    assert sw % 2 == 0 and sh % 2 == 0, "Dimensiones deben ser números pares para H.264"
    assert sh == 4320
    assert sw == 2430

    # Caso 4K vertical (2160x3840)
    sw_4k, sh_4k = safe_kenburns_scale(2160, 3840, target_factor=2.5, max_dim=4320)
    assert max(sw_4k, sh_4k) <= 4320, f"En 4K ({sw_4k}x{sh_4k}) la dimensión no debe exceder 4320"
    assert sw_4k % 2 == 0 and sh_4k % 2 == 0

    # Caso 720p vertical (720x1280) -> factor 2.5 directo
    sw_720, sh_720 = safe_kenburns_scale(720, 1280, target_factor=2.5, max_dim=4320)
    assert max(sw_720, sh_720) <= 4320
    assert sw_720 == int(720 * 2.5)
    assert sh_720 == int(1280 * 2.5)


def test_scene_clip_cmd_uses_safe_scaling():
    """P2-4: scene_clip_cmd debe incorporar las dimensiones intermedias seguras en scale y crop."""
    cmd = scene_clip_cmd(
        img=Path("dummy.png"), duration=2.0, out=Path("out.mp4"),
        w=1080, h=1920, fps=30, zoom_dir=1, rotate_deg=0
    )
    cmd_str = " ".join(cmd)
    assert "scale=2430:4320" in cmd_str
    assert "crop=2430:4320" in cmd_str
    assert "zoompan=" in cmd_str


if __name__ == "__main__":
    test_safe_kenburns_scale_bounds()
    test_scene_clip_cmd_uses_safe_scaling()
    print("PASS: test_p2_4_kenburns_jitter")
