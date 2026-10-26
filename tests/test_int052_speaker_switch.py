"""
Unit tests for INT-052: Active Speaker Switch (Diarización y cambio dinámico de plano)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import speaker_switcher
from services.viral_clipper import render_vertical_moment

def test_detect_speaker_turns_with_segments():
    """Verify detect_speaker_turns alternates speakers based on pauses and questions."""
    segments = [
        {"start": 0.0, "end": 3.0, "text": "¿Cuál es tu estrategia de inversión?"},
        {"start": 3.6, "end": 7.0, "text": "Diversificar en índices y bienes raíces."}
    ]
    turns = speaker_switcher.detect_speaker_turns(segments, total_duration=8.0)
    assert len(turns) >= 2
    speakers = [t["speaker"] for t in turns]
    assert "left" in speakers
    assert "right" in speakers

def test_build_speaker_switch_filter_overlay_syntax():
    """Verify build_speaker_switch_filter generates dual crop streams and conditional overlay."""
    turns = [
        {"start": 0.0, "end": 4.0, "speaker": "left"},
        {"start": 4.0, "end": 8.0, "speaker": "right"}
    ]
    filter_str = speaker_switcher.build_speaker_switch_filter(turns)
    assert "[src_l]crop=iw/2:ih:0:0" in filter_str
    assert "[src_r]crop=iw/2:ih:iw/2:0" in filter_str
    assert "overlay=x=0:y=0:enable='between(t,4.00,8.00)'[base]" in filter_str

@pytest.mark.anyio
@patch("subprocess.run")
async def test_render_vertical_moment_speaker_switch(mock_run, tmp_path):
    """Test render_vertical_moment invokes ffmpeg with speaker_switch filtergraph."""
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
            title="Interview Clip",
            style="speaker_switch"
        )

        assert res["ok"] is True
        assert res["style"] == "speaker_switch"

        calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        ffmpeg_calls = [c for c in calls if "ffmpeg" in c[0]]
        assert len(ffmpeg_calls) >= 1
        last_ffmpeg = " ".join(ffmpeg_calls[-1])

        assert "[src_l]crop=iw/2" in last_ffmpeg
        assert "[src_r]crop=iw/2" in last_ffmpeg
        assert "overlay=x=0:y=0:enable='between" in last_ffmpeg
