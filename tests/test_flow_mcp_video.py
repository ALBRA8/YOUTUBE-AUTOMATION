#!/usr/bin/env python3
"""
Pruebas automatizadas de la integración de Video (Gate C.1)
en tools/GoogleFlowMCP y backend/services/flow_mcp_client.py.

Hermético y sin Chrome:
- Verificación de archivos de video (MP4/WebM).
- Parsing de respuestas de flow_generate_video.
- Cliente Python generate_video().
- Pipeline bridge generate_scene_video().
- Compatibilidad con flow_import.find_flow_videos().
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
from pipeline import flow_import, images as imgs_pipeline
from services import flow_mcp_client


def _create_dummy_mp4(path: Path, size_bytes: int = 15000) -> Path:
    """Crea un archivo binario con cabecera ftyp simulando un contenedor MP4."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cabecera ISO/IEC 14496-12 ftyp box
    header = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41"
    content = header + b"\x00" * (size_bytes - len(header))
    path.write_bytes(content)
    return path


class TestFlowMCPVideoVerificationAndParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_verify_video_file_valid(self):
        vid = self.tmp / "sample.mp4"
        _create_dummy_mp4(vid, size_bytes=20000)
        self.assertTrue(flow_mcp_client.verify_video_file(vid))

    def test_verify_video_file_too_small(self):
        vid = self.tmp / "tiny.mp4"
        _create_dummy_mp4(vid, size_bytes=100)
        self.assertFalse(flow_mcp_client.verify_video_file(vid, min_bytes=1000))

    def test_verify_video_file_non_existent(self):
        self.assertFalse(flow_mcp_client.verify_video_file(self.tmp / "absent.mp4"))

    def test_parse_video_paths_from_text(self):
        vid = self.tmp / "test_out.mp4"
        _create_dummy_mp4(vid, size_bytes=12000)

        raw_output = f'Generated video in 45s (5000000 bytes, 9:16) with startFrame "orb":\n{vid}\n'
        parsed = flow_mcp_client.parse_video_paths_from_text(raw_output, verify=True)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].resolve(), vid.resolve())


class TestFlowMCPVideoClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_generate_video_success(self):
        out_vid = self.tmp / "flow" / "Escena_01_video.mp4"
        _create_dummy_mp4(out_vid, size_bytes=25000)

        mock_resp = f"Generated video in 120s:\n{out_vid}"
        with patch("services.flow_mcp_client.call_tool", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_resp
            res = await flow_mcp_client.generate_video(
                prompt="Animate cinematic",
                start_frame="crystal_orb",
                aspect="9:16",
                out_file=out_vid,
            )
            mock_call.assert_called_once()
            args = mock_call.call_args[0][1]
            self.assertEqual(args["startFrame"], "crystal_orb")
            self.assertEqual(args["aspect"], "9:16")
            self.assertEqual(res.resolve(), out_vid.resolve())


class TestPipelineVideoBridge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_generate_scene_video_bridge_and_import(self):
        proj_dir = self.tmp / "test_proj"
        flow_dir = proj_dir / "flow"
        flow_dir.mkdir(parents=True, exist_ok=True)

        # 1. Crear Start Frame dummy
        start_img = proj_dir / "scene_01.png"
        start_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 5000)

        scene = {
            "idx": 0,
            "image_path": str(start_img),
            "video_prompt": "Animate camera forward",
        }
        project = {
            "id": "test_proj",
            "format": "short",
            "output_dir": str(proj_dir),
        }

        # Mockear upload_file y generate_video
        expected_mp4 = flow_dir / "Escena_01_video.mp4"

        async def _fake_generate(*args, **kwargs):
            _create_dummy_mp4(expected_mp4, size_bytes=30000)
            return expected_mp4

        with patch("services.flow_mcp_client.available", return_value=True):
            with patch("services.flow_mcp_client.upload_file", new_callable=AsyncMock) as mock_up:
                with patch("services.flow_mcp_client.generate_video", side_effect=_fake_generate) as mock_gen:
                    mock_up.return_value = {"ok": True}

                    res = await imgs_pipeline.generate_scene_video(
                        scene=scene,
                        project=project,
                        idx=0,
                        start_frame_path=start_img,
                        asset_name="orb_c1",
                    )
                    self.assertEqual(res, expected_mp4)
                    mock_up.assert_called_once()
                    mock_gen.assert_called_once()

        # 2. Verificar que flow_import.find_flow_videos lo detecta sin cambios en flow_import
        with patch("pipeline.video.probe_duration", return_value=8.0):
            found = flow_import.find_flow_videos(proj_dir, [0])
            self.assertIn(0, found)
            self.assertEqual(found[0].resolve(), expected_mp4.resolve())


if __name__ == "__main__":
    unittest.main()
