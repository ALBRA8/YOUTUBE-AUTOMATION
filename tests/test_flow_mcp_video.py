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
import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Import ESTABLE a nivel de módulo: garantiza que `pipeline.orchestrator`
# existe en sys.modules DESDE LA COLECCIÓN (así el fixture hermético de
# conftest lo snapshot-ea y jamás lo purga entre tests — su identidad de
# módulo es constante y los patches sobre sus nombres permanecen).
from pipeline import orchestrator as _orch_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
from pipeline import flow_import, images as imgs_pipeline
from services import flow_mcp_client


# ── [FIX-C] aislamiento orden-independiente ────────────────────────────────
# test_generate_video_success y test_generate_scene_video_bridge_and_import
# PASABAN en solitario y fallaban en suite por estado GLOBAL mutado sin
# restaurar por otras baterías pytest-compatibles:
#   · tests/test_live_execution_c1.py:40 / c2.py:31 fijan
#     config.FLOW_MCP_ENABLED = True a nivel de MÓDULO → pytest lo ejecuta en
#     COLECCIÓN → available() REAL True en toda la sesión.
#   · tests/test_autopublish_generate.py purga sys.modules e inyecta un
#     `database` FAKE sin restaurar → los patch("services.flow_mcp_client.X")
#     (resueltos vía sys.modules) caían en un objeto DISTINTO del referido
#     por las capturas `from services import flow_mcp_client` de este módulo
#     → call_tool/upload_file REALES (spawn de `node mcp.js`, sin Chrome).
# Solución: los tests sensibles importan services/pipeline FRESCOS dentro de
# _isolated_app_state (purga + re-import con rutas en tmp + restauración
# EXACTA de sys.modules al salir) y parchean esos objetos frescos.
_APP_TOPS = ("config", "database", "security", "main", "mcp_server",
             "services", "pipeline")


def _is_app_module(name: str) -> bool:
    return name in _APP_TOPS or name.split(".")[0] in _APP_TOPS


@contextlib.contextmanager
def _isolated_app_state(tmp_root: Path):
    """Purga los módulos de la app de sys.modules, re-importa config/database
    con DB/OUTPUT/DATA/TMP redirigidos a tmp_root y, al salir, restaura
    sys.modules exactamente como estaba (cero huella)."""
    saved = {n: m for n, m in list(sys.modules.items()) if _is_app_module(n)}
    for n in saved:
        sys.modules.pop(n, None)
    try:
        import config as _cfg  # noqa: E402  (fresco: ni fake ni envenenado)
        _cfg.DB_PATH = tmp_root / "test.db"
        _cfg.OUTPUT_DIR = tmp_root / "output"
        _cfg.DATA_DIR = tmp_root / "data"
        _cfg.TMP_DIR = tmp_root / "tmp"
        for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
            _d.mkdir(parents=True, exist_ok=True)
        import database as _dbmod  # noqa: E402
        # database hace `from config import DB_PATH` (binding por valor) y un
        # hook externo (p.ej. conftest de sesión de FIX-A) puede reapuntar las
        # rutas tras el import: reafirmar AMBAS globals antes de init_db().
        _cfg.DB_PATH = tmp_root / "test.db"
        _cfg.OUTPUT_DIR = tmp_root / "output"
        _cfg.DATA_DIR = tmp_root / "data"
        _cfg.TMP_DIR = tmp_root / "tmp"
        _dbmod.DB_PATH = _cfg.DB_PATH
        _dbmod.init_db()
        yield
    finally:
        for n in [n for n in list(sys.modules)
                  if _is_app_module(n) and n not in saved]:
            del sys.modules[n]
        sys.modules.update(saved)


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
        with _isolated_app_state(self.tmp):
            from services import flow_mcp_client as fresh_fmc
            with patch.object(fresh_fmc, "call_tool",
                              new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_resp
                res = await fresh_fmc.generate_video(
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

        with _isolated_app_state(self.tmp):
            from pipeline import flow_import as fresh_flow_import
            from pipeline import images as fresh_imgs
            from services import flow_mcp_client as fresh_fmc

            with patch.object(fresh_fmc, "available", return_value=True):
                with patch.object(fresh_fmc, "upload_file",
                                  new_callable=AsyncMock) as mock_up:
                    with patch.object(fresh_fmc, "generate_video",
                                      side_effect=_fake_generate) as mock_gen:
                        mock_up.return_value = {"ok": True}

                        res = await fresh_imgs.generate_scene_video(
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
                found = fresh_flow_import.find_flow_videos(proj_dir, [0])
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
        # ⚠️ NO mutar módulos COMPARTIDOS: los patches antiguos apuntaban a
        # atributos de `database`/`tts_step`/`video`/`imgs`/`broker` (resueltos
        # vía pipeline.orchestrator.X). Aunque se restauraran al salir del
        # test, CUALQUIER import perezoso de servicios ejecutado DURANTE la
        # ventana del patch (p.ej. services.video_qa con su
        # `from database import get_scenes` por valor) quedaba ligado PARA
        # SIEMPRE al mock → envenenaba baterías posteriores (golden fixture:
        # KeyError 'width'). Ahora se sustituye el nombre DENTRO del
        # orquestador por namespaces falsos descartables; los parches
        # anidados de los cuerpos de test (p.ej.
        # patch("pipeline.orchestrator.video.render_scenes")) resuelven
        # contra el fake y dejan el módulo real intacto.
        import types as _types

        import database as _real_db
        from pipeline import images as _real_imgs
        from pipeline import tts_step as _real_tts
        from pipeline import video as _real_video
        from pipeline.orchestrator import broker as _real_broker  # instancia JobBroker

        def _fake_module(real, **overrides):
            ns = _types.SimpleNamespace()
            for k, v in vars(real).items():
                if not k.startswith("__"):
                    setattr(ns, k, v)
            for k, v in overrides.items():
                setattr(ns, k, v)
            return ns

        class _InstanceProxy:
            """Delega TODO en el objeto real salvo los overrides (para
            instancias p.ej. JobBroker, cuyos métodos viven en la clase)."""

            def __init__(self, real, **overrides):
                object.__setattr__(self, "_real", real)
                object.__setattr__(self, "_overrides", overrides)

            def __getattr__(self, name):
                if name in self._overrides:
                    return self._overrides[name]
                return getattr(self._real, name)

        fake_db = _fake_module(
            _real_db,
            get_project=MagicMock(return_value=self.project),
            get_scenes=MagicMock(return_value=self.scenes),
            update_project=MagicMock(),
            update_job=MagicMock(),
        )
        fake_imgs = _fake_module(_real_imgs, generate_all=AsyncMock())
        fake_tts = _fake_module(
            _real_tts,
            synthesize_scenes=AsyncMock(return_value=([3.0, 3.0], [[], []])),
            build_full_track=AsyncMock(return_value=self.proj_dir / "voice.mp3"),
            save_words_timeline=MagicMock(return_value=self.proj_dir / "words.json"),
        )
        fake_video = _fake_module(
            _real_video,
            concat_clips=AsyncMock(return_value=self.proj_dir / "silent.mp4"),
            mux_audio_music=AsyncMock(return_value=self.proj_dir / "raw.mp4"),
            burn_subtitles=AsyncMock(return_value=self.proj_dir / "final.mp4"),
            make_thumbnail=MagicMock(return_value=self.proj_dir / "thumb.jpg"),
        )
        fake_broker = _InstanceProxy(_real_broker, publish=AsyncMock())

        p_db = patch("pipeline.orchestrator.db", fake_db)
        p_emit = patch("pipeline.orchestrator._emit", new_callable=AsyncMock)
        p_imgs = patch("pipeline.orchestrator.imgs", fake_imgs)
        p_gate_img = patch("pipeline.orchestrator._gate_imagenes_reales")
        p_gate_tts = patch("pipeline.orchestrator._gate_voz_real")
        p_gate_qa = patch("pipeline.orchestrator._gate_qa_final")
        p_tts = patch("pipeline.orchestrator.tts_step", fake_tts)
        p_dev = patch("pipeline.orchestrator._record_duration_deviations")
        p_video = patch("pipeline.orchestrator.video", fake_video)
        p_arch = patch("pipeline.orchestrator._archive_library")
        p_broker = patch("pipeline.orchestrator.broker", fake_broker)
        p_out = patch("pipeline.orchestrator.OUTPUT_DIR", self.tmp)

        patches = [
            p_db, p_emit, p_imgs, p_gate_img, p_gate_tts, p_gate_qa,
            p_tts, p_dev, p_video, p_arch, p_broker, p_out
        ]
        return patches

    async def test_orchestrator_video_disabled_fallback_kenburns(self):
        from pipeline import orchestrator

        patches = self._setup_common_patches()
        # un addCleanup(p.stop) POR patch (orden reverso, independiente):
        # la versión lambda-lista abortaba la cadena al primer stop que
        # lanzara, dejando patches ACTIVOS (p.ej. database.get_scenes) que
        # envenenaban las baterías siguientes (golden fixture QA).
        for p in reversed(patches):
            p.start()
            self.addCleanup(p.stop)

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
        # un addCleanup(p.stop) POR patch (orden reverso, independiente):
        # la versión lambda-lista abortaba la cadena al primer stop que
        # lanzara, dejando patches ACTIVOS (p.ej. database.get_scenes) que
        # envenenaban las baterías siguientes (golden fixture QA).
        for p in reversed(patches):
            p.start()
            self.addCleanup(p.stop)

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
        # un addCleanup(p.stop) POR patch (orden reverso, independiente):
        # la versión lambda-lista abortaba la cadena al primer stop que
        # lanzara, dejando patches ACTIVOS (p.ej. database.get_scenes) que
        # envenenaban las baterías siguientes (golden fixture QA).
        for p in reversed(patches):
            p.start()
            self.addCleanup(p.stop)

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
        # un addCleanup(p.stop) POR patch (orden reverso, independiente):
        # la versión lambda-lista abortaba la cadena al primer stop que
        # lanzara, dejando patches ACTIVOS (p.ej. database.get_scenes) que
        # envenenaban las baterías siguientes (golden fixture QA).
        for p in reversed(patches):
            p.start()
            self.addCleanup(p.stop)

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
