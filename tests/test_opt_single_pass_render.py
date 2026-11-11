# -*- coding: utf-8 -*-
"""Test hermético de optimización de render en un solo paso (single-pass overlay)."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pipeline import video


def test_single_pass_subtitles_only(tmp_path):
    """Verifica que sin capas extra se mantenga el comando directo con final=True."""
    proj_dir = tmp_path / "proj_simple"
    proj_dir.mkdir(parents=True)

    words_file = proj_dir / "words.json"
    words_file.write_text(json.dumps([{"word": "hola", "start": 0.0, "end": 0.5}]), encoding="utf8")

    video_raw = proj_dir / "raw.mp4"
    video_raw.write_bytes(b"dummy_video")

    project = {
        "id": "proj_simple",
        "format": "short",
        "meta": {}
    }

    recorded_cmds = []

    def fake_run_ffmpeg(cmd, timeout=300):
        recorded_cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"dummy_rendered")
        mock_p = MagicMock()
        mock_p.returncode = 0
        return mock_p

    with patch.object(video, "OUTPUT_DIR", tmp_path), \
         patch.object(video, "_run_ffmpeg", side_effect=fake_run_ffmpeg):
        res = asyncio.run(video.burn_subtitles(project, video_raw, words_file))
        assert res.is_file()
        render_cmds = [c for c in recorded_cmds if "-y" in c]
        assert len(render_cmds) == 1
        cmd = render_cmds[0]
        assert "-vf" in cmd
        assert "-filter_complex" not in cmd


def test_single_pass_composite_badge_and_pip(tmp_path):
    """Verifica que con badge y avatar PiP se use un único comando filter_complex."""
    proj_dir = tmp_path / "proj_comp"
    proj_dir.mkdir(parents=True)

    words_file = proj_dir / "words.json"
    words_file.write_text(json.dumps([{"word": "producto", "start": 0.0, "end": 1.0}]), encoding="utf8")

    video_raw = proj_dir / "raw.mp4"
    video_raw.write_bytes(b"dummy_video")

    avatar_img = tmp_path / "avatar.png"
    avatar_img.write_bytes(b"dummy_avatar")

    project = {
        "id": "proj_comp",
        "format": "short",
        "mode": "product",
        "avatar_id": "av_test",
        "meta": {
            "ecommerce_badge": {"type": "discount"},
            "circle_avatar_pip": {"border_color": "cyan", "position": "bottom_right"}
        }
    }

    recorded_cmds = []

    def fake_run_ffmpeg(cmd, timeout=300):
        recorded_cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"dummy_rendered")
        mock_p = MagicMock()
        mock_p.returncode = 0
        return mock_p

    def fake_get_avatar(aid):
        return {"id": aid, "image_path": str(avatar_img)}

    with patch.object(video, "OUTPUT_DIR", tmp_path), \
         patch.object(video, "_run_ffmpeg", side_effect=fake_run_ffmpeg), \
         patch("database.get_avatar", side_effect=fake_get_avatar), \
         patch("services.ecommerce_overlays.generate_ecommerce_badge", lambda **kw: Path(kw["out_path"]).write_bytes(b"badge")), \
         patch("services.avatar_pip.create_circle_avatar", lambda *a, **kw: Path(kw["output_path"]).write_bytes(b"pip")):
        
        res = asyncio.run(video.burn_subtitles(project, video_raw, words_file))
        assert res.is_file()
        # DEBE SER EXACTAMENTE 1 COMANDO DE RENDER (sin pasadas intermedias a disco)
        render_cmds = [c for c in recorded_cmds if "-y" in c]
        assert len(render_cmds) == 1
        cmd = render_cmds[0]
        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        fc_str = cmd[fc_idx + 1]
        # Debe encadenar el filtro ASS y los overlays
        assert "ass=" in fc_str
        assert "overlay=" in fc_str
        assert "[v0]" in fc_str
        assert "[v1]" in fc_str
        assert "[v2]" in fc_str
