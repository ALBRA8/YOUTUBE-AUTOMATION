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

    def _make_valid_png(p):
        from PIL import Image
        im = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
        im.save(p, format="PNG")

    with patch.object(video, "OUTPUT_DIR", tmp_path), \
         patch.object(video, "_run_ffmpeg", side_effect=fake_run_ffmpeg), \
         patch("database.get_avatar", side_effect=fake_get_avatar), \
         patch("services.ecommerce_overlays.generate_ecommerce_badge", lambda **kw: _make_valid_png(kw["out_path"])), \
         patch("services.avatar_pip.create_circle_avatar", lambda *a, **kw: _make_valid_png(kw["output_path"])):
        
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

        # subs_status.json debe reportar capas omitidas vacías cuando todas son válidas
        st_file = proj_dir / "subs_status.json"
        assert st_file.is_file()
        st_data = json.loads(st_file.read_text(encoding="utf8"))
        assert st_data.get("burned") is True
        assert st_data.get("omitted_layers") == []


def test_aa2_corrupt_layer_png_omitted_and_subs_present(tmp_path):
    """AA2: Si un PNG de capa está corrupto (PIL.verify falla), se omite,
    se sigue con subtítulos y se lista en omitted_layers de subs_status.json."""
    proj_dir = tmp_path / "proj_corrupt"
    proj_dir.mkdir(parents=True)

    words_file = proj_dir / "words.json"
    words_file.write_text(json.dumps([{"word": "oferta", "start": 0.0, "end": 0.8}]), encoding="utf8")

    video_raw = proj_dir / "raw.mp4"
    video_raw.write_bytes(b"dummy_video")

    avatar_img = tmp_path / "avatar.png"
    avatar_img.write_bytes(b"dummy_avatar")

    project = {
        "id": "proj_corrupt",
        "format": "short",
        "mode": "product",
        "avatar_id": "av_corrupt",
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

    def _write_corrupt_file(p):
        Path(p).write_bytes(b"CORRUPT_PNG_NOT_AN_IMAGE_HEADER_123456789")

    def _make_valid_png(p):
        from PIL import Image
        im = Image.new("RGBA", (20, 20), (0, 255, 0, 255))
        im.save(p, format="PNG")

    # Badge corrupto, pero avatar PiP válido
    with patch.object(video, "OUTPUT_DIR", tmp_path), \
         patch.object(video, "_run_ffmpeg", side_effect=fake_run_ffmpeg), \
         patch("database.get_avatar", side_effect=fake_get_avatar), \
         patch("services.ecommerce_overlays.generate_ecommerce_badge", lambda **kw: _write_corrupt_file(kw["out_path"])), \
         patch("services.avatar_pip.create_circle_avatar", lambda *a, **kw: _make_valid_png(kw["output_path"])):

        res = asyncio.run(video.burn_subtitles(project, video_raw, words_file))
        assert res.is_file()

        render_cmds = [c for c in recorded_cmds if "-y" in c]
        assert len(render_cmds) == 1
        cmd = render_cmds[0]
        # El comando debe tener subtítulos presentes
        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        fc_str = cmd[fc_idx + 1]
        assert "ass=" in fc_str
        # NO debe tener badge_discount.png en los inputs
        assert not any("badge_discount.png" in str(arg) for arg in cmd)

        # subs_status.json debe listar la capa omitida
        st_file = proj_dir / "subs_status.json"
        assert st_file.is_file()
        st_data = json.loads(st_file.read_text(encoding="utf8"))
        assert st_data.get("burned") is True
        assert "badge_discount.png" in st_data.get("omitted_layers", [])


def test_aa2_ffmpeg_retry_subs_only_on_filter_complex_failure(tmp_path):
    """AA2: Si ffmpeg falla en filter_complex (rc!=0), reintentar una vez
    solo con -vf de subtítulos antes de copiar video_raw."""
    proj_dir = tmp_path / "proj_retry"
    proj_dir.mkdir(parents=True)

    words_file = proj_dir / "words.json"
    words_file.write_text(json.dumps([{"word": "prueba", "start": 0.0, "end": 0.5}]), encoding="utf8")

    video_raw = proj_dir / "raw.mp4"
    video_raw.write_bytes(b"dummy_video")

    project = {
        "id": "proj_retry",
        "format": "short",
        "mode": "product",
        "meta": {"ecommerce_badge": {"type": "rating"}}
    }

    recorded_cmds = []

    def fake_run_ffmpeg(cmd, timeout=300):
        recorded_cmds.append(cmd)
        mock_p = MagicMock()
        if "-filter_complex" in cmd:
            mock_p.returncode = 1
            mock_p.stderr = "error en filter_complex"
        else:
            # Reintento con subtítulos solos (-vf): tiene éxito
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"rendered_subs_only")
            mock_p.returncode = 0
            mock_p.stderr = ""
        return mock_p

    def _make_valid_png(p):
        from PIL import Image
        im = Image.new("RGBA", (20, 20), (0, 0, 255, 255))
        im.save(p, format="PNG")

    with patch.object(video, "OUTPUT_DIR", tmp_path), \
         patch.object(video, "_run_ffmpeg", side_effect=fake_run_ffmpeg), \
         patch("services.ecommerce_overlays.generate_ecommerce_badge", lambda **kw: _make_valid_png(kw["out_path"])):

        res = asyncio.run(video.burn_subtitles(project, video_raw, words_file))
        assert res.is_file()

        # Debe haber ejecutado 2 comandos de render (-y):
        # 1. filter_complex que falló
        # 2. reintento solo con -vf de subtítulos que tuvo éxito
        render_cmds = [c for c in recorded_cmds if "-y" in c]
        assert len(render_cmds) == 2
        assert "-filter_complex" in render_cmds[0]
        assert "-vf" in render_cmds[1]
        assert "-filter_complex" not in render_cmds[1]

        st_file = proj_dir / "subs_status.json"
        assert st_file.is_file()
        st_data = json.loads(st_file.read_text(encoding="utf8"))
        assert st_data.get("burned") is True
        assert "badge_rating.png" in st_data.get("omitted_layers", [])

