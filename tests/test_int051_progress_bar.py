"""
Unit tests for INT-051: Barra de Progreso Dinámica para Shorts (OpenShorts cloned)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import progress_overlay
from services.viral_clipper import render_vertical_moment

def test_build_progress_bar_filter_math():
    """Verify build_progress_bar_filter generates correct drawbox expressions."""
    f = progress_overlay.build_progress_bar_filter(
        duration=15.0,
        color="#10B981",
        height=6,
        y_pos=1914
    )
    assert "drawbox=x=0:y=1914:w=1080:h=6" in f
    assert "w='min(iw,iw*(t/15.000))'" in f
    assert "color=0x10B981@0.95" in f

@pytest.mark.anyio
@patch("subprocess.run")
async def test_render_vertical_moment_includes_progress_bar(mock_run, tmp_path):
    """Test render_vertical_moment appends progress bar filter clause."""
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
            title="Clip with Progress Bar",
            style="split_screen",
            progress_bar=True
        )

        assert res["ok"] is True

        calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        ffmpeg_calls = [c for c in calls if "ffmpeg" in c[0]]
        assert len(ffmpeg_calls) >= 1
        last_ffmpeg = " ".join(ffmpeg_calls[-1])

        assert "drawbox=x=0:y=1914" in last_ffmpeg
        assert "min(iw,iw*(t/" in last_ffmpeg
