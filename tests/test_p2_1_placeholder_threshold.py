"""
Test P2-1: Umbral configurable de placeholders y reporte en video_qa.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.pipeline.orchestrator import _gate_imagenes_reales
from backend.services.video_qa import qa_project


def test_gate_imagenes_reales_threshold_fails_when_exceeded(tmp_path):
    """P2-1: Si el número de placeholders supera MAX_ALLOWED_PLACEHOLDERS y el reintento falla,
    _gate_imagenes_reales debe lanzar RuntimeError."""
    pid = "proj_test_ph_fail"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)

    scenes = []
    for i in range(5):
        img = pdir / f"scene_{i:02d}.png"
        img.write_text("fake img", encoding="utf-8")
        sf = pdir / f"scene_{i:02d}.style.json"
        # 3 placeholders, 2 reales
        method = "placeholder" if i in (0, 1, 2) else "gemini"
        sf.write_text(json.dumps({"method": method}), encoding="utf-8")
        scenes.append({"image_path": str(img), "scene_number": i + 1, "idx": i})

    # Con max permitido = 1, 3 placeholders excede el umbral
    with patch.dict(os.environ, {"MAX_ALLOWED_PLACEHOLDERS": "1"}):
        with pytest.raises(RuntimeError, match="placeholder"):
            _gate_imagenes_reales(pid, scenes)


def test_gate_imagenes_reales_threshold_passes_within_limit(tmp_path):
    """P2-1: Si el número de placeholders es <= MAX_ALLOWED_PLACEHOLDERS, pasa."""
    pid = "proj_test_ph_pass"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)

    scenes = []
    for i in range(5):
        img = pdir / f"scene_{i:02d}.png"
        img.write_text("fake img", encoding="utf-8")
        sf = pdir / f"scene_{i:02d}.style.json"
        # 1 placeholder, 4 reales
        method = "placeholder" if i == 0 else "gemini"
        sf.write_text(json.dumps({"method": method}), encoding="utf-8")
        scenes.append({"image_path": str(img), "scene_number": i + 1, "idx": i})

    with patch.dict(os.environ, {"MAX_ALLOWED_PLACEHOLDERS": "1"}):
        # No debe lanzar
        _gate_imagenes_reales(pid, scenes)


def test_video_qa_reports_placeholder_threshold_error(tmp_path):
    """P2-1: Video QA marca status='error' y documenta placeholders si superan el umbral."""
    pid = "proj_qa_ph"
    scenes = []
    from PIL import Image
    for i in range(4):
        img = tmp_path / f"scene_{i:02d}.png"
        im = Image.new("RGB", (300, 300), color="blue")
        im.save(img)
        sf = tmp_path / f"scene_{i:02d}.style.json"
        # 3 placeholders de 4
        method = "placeholder" if i in (0, 1, 2) else "gemini"
        sf.write_text(json.dumps({"method": method}), encoding="utf-8")
        scenes.append({"image_path": str(img), "scene_number": i + 1, "idx": i})

    with patch.dict(os.environ, {"MAX_ALLOWED_PLACEHOLDERS": "1"}), \
         patch("backend.services.video_qa.get_project", return_value={"id": pid}), \
         patch("backend.services.video_qa.get_scenes", return_value=scenes):
        res = qa_project(pid)
        assert res["status"] == "error", f"Esperado 'error' pero obtenido: {res['status']}"
        assert res["summary"]["placeholders"] == 3
        assert res["summary"]["max_allowed_placeholders"] == 1


if __name__ == "__main__":
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        test_gate_imagenes_reales_threshold_fails_when_exceeded(Path(td))
        test_gate_imagenes_reales_threshold_passes_within_limit(Path(td))
        test_video_qa_reports_placeholder_threshold_error(Path(td))
    print("PASS: test_p2_1_placeholder_threshold")
