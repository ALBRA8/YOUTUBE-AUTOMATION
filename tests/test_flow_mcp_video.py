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



class TestOrchestratorFlowVideoWiring(unittest.IsolatedAsyncioTestCase):
    """Pruebas del puente de orquestación en pipeline/orchestrator._run (Gate C.2)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.project_id = "test_orch_vid_proj"
        self.proj_dir = self.tmp / self.project_id
        self.proj_dir.mkdir(parents=True, exist_ok=True)

        self.img0 = self.proj_dir / "scene_01.png"
        self.img0.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
        self.img1 = self.proj_dir / "scene_02.png"
        self.img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)

        self.project = {
            "id": self.project_id,
            "format": "short",
            "mode": "production_json",
            "style": "cinematic",
            "title": "Test Orch",
            "status": "created",
            "meta": {},
        }
        self.scenes = [
            {"id": "s1", "project_id": self.project_id, "idx": 0, "text": "Scene 1", "image_path": str(self.img0)},
            {"id": "s2", "project_id": self.project_id, "idx": 1, "text": "Scene 2", "image_path": str(self.img1)},
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def _setup_common_patches(self):
        p_db_get_proj = patch("pipeline.orchestrator.db.get_project", return_value=self.project)
        p_db_get_sc = patch("pipeline.orchestrator.db.get_scenes", return_value=self.scenes)
        p_db_up_proj = patch("pipeline.orchestrator.db.update_project")
        p_db_up_job = patch("pipeline.orchestrator.db.update_job")
        p_emit = patch("pipeline.orchestrator._emit", new_callable=AsyncMock)
        p_gen_all = patch("pipeline.orchestrator.imgs.generate_all", new_callable=AsyncMock)
        p_gate_img = patch("pipeline.orchestrator._gate_imagenes_reales")
        p_gate_tts = patch("pipeline.orchestrator._gate_voz_real")
        p_gate_qa = patch("pipeline.orchestrator._gate_qa_final")
        p_synth = patch("pipeline.orchestrator.tts_step.synthesize_scenes", new_callable=AsyncMock, return_value=([3.0, 3.0], [[], []]))
        p_track = patch("pipeline.orchestrator.tts_step.build_full_track", new_callable=AsyncMock, return_value=self.proj_dir / "voice.mp3")
        p_words = patch("pipeline.orchestrator.tts_step.save_words_timeline", return_value=self.proj_dir / "words.json")
        p_dev = patch("pipeline.orchestrator._record_duration_deviations")
        p_concat = patch("pipeline.orchestrator.video.concat_clips", new_callable=AsyncMock, return_value=self.proj_dir / "silent.mp4")
        p_mux = patch("pipeline.orchestrator.video.mux_audio_music", new_callable=AsyncMock, return_value=self.proj_dir / "raw.mp4")
        p_burn = patch("pipeline.orchestrator.video.burn_subtitles", new_callable=AsyncMock, return_value=self.proj_dir / "final.mp4")
        p_thumb = patch("pipeline.orchestrator.video.make_thumbnail", return_value=self.proj_dir / "thumb.jpg")
        p_arch = patch("pipeline.orchestrator._archive_library")
        p_pub = patch("pipeline.orchestrator.broker.publish", new_callable=AsyncMock)
        p_out = patch("pipeline.orchestrator.OUTPUT_DIR", self.tmp)

        patches = [
            p_db_get_proj, p_db_get_sc, p_db_up_proj, p_db_up_job, p_emit,
            p_gen_all, p_gate_img, p_gate_tts, p_gate_qa, p_synth, p_track,
            p_words, p_dev, p_concat, p_mux, p_burn, p_thumb, p_arch, p_pub, p_out
        ]
        return patches

    async def test_orchestrator_video_disabled_fallback_kenburns(self):
        from pipeline import orchestrator

        patches = self._setup_common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("config.FLOW_MCP_VIDEO_ENABLED", False):
            with patch("pipeline.orchestrator.imgs.generate_scene_video", new_callable=AsyncMock) as mock_gen_vid:
                with patch("pipeline.orchestrator.video.render_scenes", new_callable=AsyncMock) as mock_render:
                    mock_render.return_value = [self.proj_dir / "clip_00.mp4", self.proj_dir / "clip_01.mp4"]

                    await orchestrator._run("job_1", self.project_id, autopublish=False)

                    # No se debe solicitar video cuando est\xe1 deshabilitado
                    mock_gen_vid.assert_not_called()
                    # render_scenes debe recibir flow_videos=None (Ken Burns)
                    mock_render.assert_called_once()
                    self.assertIsNone(mock_render.call_args.kwargs.get("flow_videos"))

    async def test_orchestrator_video_enabled_generates_and_passes_flow_videos(self):
        from pipeline import orchestrator

        patches = self._setup_common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        vid0 = self.proj_dir / "flow" / "Escena_01_video.mp4"
        vid1 = self.proj_dir / "flow" / "Escena_02_video.mp4"
        _create_dummy_mp4(vid0)
        _create_dummy_mp4(vid1)

        async def _mock_gen_vid(scene, project, idx, **kwargs):
            return vid0 if idx == 0 else vid1

        with patch("config.FLOW_MCP_VIDEO_ENABLED", True):
            with patch("services.flow_mcp_client.available", return_value=True):
                with patch("pipeline.orchestrator.imgs.generate_scene_video", side_effect=_mock_gen_vid) as mock_gen_vid:
                    with patch("pipeline.orchestrator.video.render_scenes", new_callable=AsyncMock) as mock_render:
                        mock_render.return_value = [self.proj_dir / "clip_00.mp4", self.proj_dir / "clip_01.mp4"]

                        await orchestrator._run("job_2", self.project_id, autopublish=False)

                        self.assertEqual(mock_gen_vid.call_count, 2)
                        mock_render.assert_called_once()
                        fv = mock_render.call_args.kwargs.get("flow_videos")
                        self.assertIsNotNone(fv)
                        self.assertEqual(fv[0], vid0)
                        self.assertEqual(fv[1], vid1)

    async def test_orchestrator_video_idempotency_skips_existing(self):
        from pipeline import orchestrator

        patches = self._setup_common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        flow_dir = self.proj_dir / "flow"
        flow_dir.mkdir(parents=True, exist_ok=True)
        vid0 = flow_dir / "Escena_01_video.mp4"
        _create_dummy_mp4(vid0)
        vid1 = flow_dir / "Escena_02_video.mp4"

        with patch("config.FLOW_MCP_VIDEO_ENABLED", True):
            with patch("services.flow_mcp_client.available", return_value=True):
                with patch("pipeline.orchestrator.flow_import.find_flow_videos", return_value={0: vid0}):
                    with patch("pipeline.orchestrator.imgs.generate_scene_video", new_callable=AsyncMock) as mock_gen_vid:
                        mock_gen_vid.return_value = vid1
                        with patch("pipeline.orchestrator.video.render_scenes", new_callable=AsyncMock) as mock_render:
                            mock_render.return_value = [self.proj_dir / "clip_00.mp4", self.proj_dir / "clip_01.mp4"]

                            await orchestrator._run("job_3", self.project_id, autopublish=False)

                            # Solo se debe haber generado la escena 1 (idx=1), pues la 0 ya exist\xeda
                            self.assertEqual(mock_gen_vid.call_count, 1)
                            self.assertEqual(mock_gen_vid.call_args.kwargs["idx"], 1)

                            fv = mock_render.call_args.kwargs.get("flow_videos")
                            self.assertIn(0, fv)
                            self.assertIn(1, fv)

    async def test_orchestrator_video_failure_graceful_fallback(self):
        from pipeline import orchestrator

        patches = self._setup_common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        vid1 = self.proj_dir / "flow" / "Escena_02_video.mp4"
        _create_dummy_mp4(vid1)

        async def _mock_gen_fail(scene, project, idx, **kwargs):
            if idx == 0:
                raise RuntimeError("Flow timeout simulado en escena 0")
            return vid1

        with patch("config.FLOW_MCP_VIDEO_ENABLED", True):
            with patch("services.flow_mcp_client.available", return_value=True):
                with patch("pipeline.orchestrator.imgs.generate_scene_video", side_effect=_mock_gen_fail):
                    with patch("pipeline.orchestrator.video.render_scenes", new_callable=AsyncMock) as mock_render:
                        mock_render.return_value = [self.proj_dir / "clip_00.mp4", self.proj_dir / "clip_01.mp4"]

                        # No debe lanzar excepci\xf3n no capturada
                        await orchestrator._run("job_4", self.project_id, autopublish=False)

                        # Escena 0 no est\xe1 en flow_videos; escena 1 s\xed est\xe1
                        fv = mock_render.call_args.kwargs.get("flow_videos")
                        self.assertNotIn(0, fv)
                        self.assertEqual(fv[1], vid1)


if __name__ == "__main__":
    unittest.main()
