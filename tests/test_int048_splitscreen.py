"""
Unit tests for INT-048: Split-Screen Dual-Speaker Podcast Layout (OpenShorts cloned)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.viral_clipper import render_vertical_moment

@pytest.mark.anyio
@patch("subprocess.run")
async def test_render_vertical_moment_split_screen_filter(mock_run, tmp_path):
    """Test render_vertical_moment invokes ffmpeg with split_screen dual-crop and vstack."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    with patch("services.viral_clipper.TMP_DIR", tmp_path), \
         patch("services.viral_clipper.RENDERS_DIR", tmp_path):
        
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
            start=10.0,
            end=25.0,
            title="Podcast Clip",
            style="split_screen"
        )

        assert res["ok"] is True
        assert res["style"] == "split_screen"

        calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        ffmpeg_calls = [c for c in calls if "ffmpeg" in c[0]]
        assert len(ffmpeg_calls) >= 1
        last_ffmpeg = " ".join(ffmpeg_calls[-1])

        # Dual crop & vstack
        assert "split=2[in_top][in_bot]" in last_ffmpeg
        assert "crop=iw/2:ih:0:0" in last_ffmpeg
        assert "crop=iw/2:ih:iw/2:0" in last_ffmpeg
        assert "vstack=inputs=2" in last_ffmpeg
        assert "drawbox=x=0:y=958:w=1080:h=4" in last_ffmpeg

@pytest.mark.anyio
@patch("subprocess.run")
async def test_render_vertical_moment_split_screen_with_broll(mock_run, tmp_path):
    """Test split_screen integrates seamlessly with B-roll overlay and base stream."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    with patch("services.viral_clipper.TMP_DIR", tmp_path), \
         patch("services.viral_clipper.RENDERS_DIR", tmp_path), \
         patch("services.broll_overlay.prepare_broll_clip") as mock_broll_prep, \
         patch("services.broll_overlay.plan_broll_intervals") as mock_plan:

        mock_plan.return_value = [{"start": 2.0, "end": 6.0, "duration": 4.0}]

        fake_broll_file = tmp_path / "mock_broll.mp4"
        fake_broll_file.touch()

        async def fake_prep(q, duration, out_path):
            Path(out_path).touch()
            return True

        mock_broll_prep.side_effect = fake_prep

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
            start=10.0,
            end=25.0,
            title="Podcast Clip With BRoll",
            style="split_screen",
            broll=True,
            broll_query="technology computers"
        )

        assert res["ok"] is True
        assert res["style"] == "split_screen"

        calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        ffmpeg_calls = [c for c in calls if "ffmpeg" in c[0]]
        assert len(ffmpeg_calls) >= 1
        last_ffmpeg = " ".join(ffmpeg_calls[-1])

        assert "vstack=inputs=2" in last_ffmpeg
        assert "overlay=enable='between(t," in last_ffmpeg
