"""
Unit tests for INT-053: Auto Face-Tracking Pan & Scan (OpenShorts 100% Cloned)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import face_tracker
from services.viral_clipper import render_vertical_moment

def test_build_face_tracking_filter_default_fallback():
    """Verify build_face_tracking_filter creates centered 9:16 crop when trajectory is empty."""
    f = face_tracker.build_face_tracking_filter([], orig_w=1920, orig_h=1080)
    assert "crop=607:1080:" in f
    assert ":0,scale=1080:1920" in f

def test_build_face_tracking_filter_with_trajectory():
    """Verify build_face_tracking_filter uses mean position from trajectory."""
    traj = [
        {"time": 0.0, "crop_x": 200},
        {"time": 1.0, "crop_x": 300},
        {"time": 2.0, "crop_x": 400}
    ]
    f = face_tracker.build_face_tracking_filter(traj, orig_w=1920, orig_h=1080)
    # Mean of 200, 300, 400 is 300
    assert "crop=607:1080:300:0,scale=1080:1920" in f

@pytest.mark.anyio
@patch("subprocess.run")
async def test_render_vertical_moment_face_tracking(mock_run, tmp_path):
    """Test render_vertical_moment invokes ffmpeg with face_tracking filtergraph."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    with patch("services.viral_clipper.TMP_DIR", tmp_path), \
         patch("services.viral_clipper.RENDERS_DIR", tmp_path), \
         patch("services.face_tracker.track_face_trajectory", return_value=[{"time": 0.0, "crop_x": 450}]):

        def side_effect_run(cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "-o" and i + 1 < len(cmd):
                    Path(cmd[i+1]).touch()
            if cmd and isinstance(cmd[-1], str) and cmd[-1].endswith(".mp4"):
                Path(cmd[-1]).touch()
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = side_effect_run

        res = await render_vertical_moment(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            start=5.0,
            end=20.0,
            title="Interview Pan Scan",
            style="face_tracking"
        )

        assert res["ok"] is True
        assert res["style"] == "face_tracking"

        calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        ffmpeg_calls = [c for c in calls if "ffmpeg" in c[0]]
        assert len(ffmpeg_calls) >= 1
        last_ffmpeg = " ".join(ffmpeg_calls[-1])

        assert "crop=607:1080:450:0" in last_ffmpeg
        assert "scale=1080:1920" in last_ffmpeg
