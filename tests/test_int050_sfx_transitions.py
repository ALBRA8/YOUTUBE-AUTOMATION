"""
Unit tests for INT-050: Sound Effects (SFX) Automáticos en Transiciones (OpenShorts cloned)
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import sfx_manager
from services import video_assembler

def test_ensure_sfx_library_creates_files(tmp_path):
    """Verify ensure_sfx_library ensures whoosh, pop and ding are present or generated."""
    with patch("services.sfx_manager.SFX_DIR", tmp_path), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # Touch files to simulate successful synthesis
        def side_effect(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.touch()
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        lib = sfx_manager.ensure_sfx_library()
        assert "whoosh" in lib
        assert "pop" in lib
        assert "ding" in lib
        assert lib["whoosh"].name == "whoosh.wav"

def test_plan_sfx_events_timing():
    """Verify plan_sfx_events places whoosh sounds before scene cuts."""
    scene_durations = [4.0, 5.0, 3.0]
    broll_intervals = [{"start": 6.5, "end": 9.0}]

    events = sfx_manager.plan_sfx_events(
        scene_durations=scene_durations,
        broll_intervals=broll_intervals,
        include_whoosh=True,
        include_broll_sfx=True
    )

    assert len(events) >= 2
    types = [e["type"] for e in events]
    assert "whoosh" in types
    assert "pop" in types

    # First cut is at 4.0s -> whoosh around ~3.92s
    first_whoosh = [e for e in events if e["type"] == "whoosh"][0]
    assert 3.8 <= first_whoosh["time"] <= 4.1

    # B-roll starts at 6.5s -> pop around ~6.46s
    pop_ev = [e for e in events if e["type"] == "pop"][0]
    assert 6.3 <= pop_ev["time"] <= 6.6

def test_video_assembler_plan_render_includes_sfx(tmp_path):
    """Verify plan_render includes SFX mixing stage when scenes > 1."""
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()

    manifest = {
        "run_id": "test_sfx",
        "resolution": "1080x1920",
        "fps": 30,
        "sfx": True,
        "scenes": [
            {"scene_id": "s1", "status": "ready", "duration_sec": 4.0, "image_path": "s1.jpg"},
            {"scene_id": "s2", "status": "ready", "duration_sec": 4.0, "image_path": "s2.jpg"}
        ]
    }

    with patch("services.sfx_manager.SFX_DIR", tmp_path), \
         patch("services.video_assembler.has_filter", return_value=False):
        
        # Create fake whoosh file
        whoosh_file = tmp_path / "whoosh.wav"
        whoosh_file.touch()

        plan = video_assembler.plan_render(manifest, run_dir)
        steps = plan.get("steps", [])
        stages = [s["stage"] for s in steps]
        assert "sfx" in stages
        sfx_step = [s for s in steps if s["stage"] == "sfx"][0]
        assert "amix" in " ".join(sfx_step["cmd"])
