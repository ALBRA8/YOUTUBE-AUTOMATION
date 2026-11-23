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


def test_scene_clip_cmd_4k_usa_ruta_b_factor_2x():
    """P1-1: en 4K el factor de safe_kenburns_scale cae a 1.125 (mitigación
    inerte). La ruta B debe activarse: zoompan a media resolución con factor
    2x real + upscale lanczos final; NUNCA intermedio 4320x7680."""
    cmd = scene_clip_cmd(
        img=Path("dummy.png"), duration=2.0, out=Path("out.mp4"),
        w=2160, h=3840, fps=30, zoom_dir=1, rotate_deg=0)
    s = " ".join(cmd)
    assert "zoompan=" in s and "s=1080x1920" in s, "zoompan debe salir a media resolución"
    assert "scale=2160:3840:flags=lanczos" in s, "upscale final lanczos"
    assert "scale=2160:3840:force_original_aspect_ratio=increase" in s,         "intermedio = resolución original (2x de 1080p), memoria acotada"
    assert "scale=2430:4320" not in s, "factor 1.125 NO debe usarse en 4K"
    assert "4320:7680" not in s, "prohibido intermedio 8K (OOM)"


def test_scene_clip_cmd_1080p_mantiene_camino_directo():
    """P1-1: con factor ≥ 2.0 (1080p → 2.25x) NO cambia el comportamiento."""
    cmd = scene_clip_cmd(
        img=Path("dummy.png"), duration=2.0, out=Path("out.mp4"),
        w=1080, h=1920, fps=30, zoom_dir=1, rotate_deg=0)
    s = " ".join(cmd)
    assert "scale=2430:4320" in s and "s=1080x1920" in s
    assert "flags=lanczos" not in s, "sin upscale extra en 1080p"


if __name__ == "__main__":
    test_safe_kenburns_scale_bounds()
    test_scene_clip_cmd_uses_safe_scaling()
    test_scene_clip_cmd_4k_usa_ruta_b_factor_2x()
    test_scene_clip_cmd_1080p_mantiene_camino_directo()
    print("PASS: test_p2_4_kenburns_jitter")
