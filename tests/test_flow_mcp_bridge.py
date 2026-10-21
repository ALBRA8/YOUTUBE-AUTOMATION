#!/usr/bin/env python3
"""
Pruebas automatizadas del Puente GoogleFlowMCP × YOUTUBE-AUTOMATION.

Cubre de forma hermética y aislada (sin abrir Chrome, sin red, sin generar en Flow real):
  1. Configuración por defecto y banderas de disponibilidad (FLOW_MCP_ENABLED=0).
  2. Detección de binarios y resiliencia ante rutas ausentes.
  3. Verificación de archivos binarios (rechazo de archivos inexistentes, vacíos o corruptos).
  4. Parsing de la respuesta real de tools/GoogleFlowMCP/src/mcp.js (cabecera 'Generated N...:\n').
  5. Ciclo de vida del subproceso MCP Stdio: handshake secuencial JSON-RPC 2.0.
  6. Manejo tipado de errores (FlowMCPAuthError, FlowMCPTimeoutError, FlowMCPResponseError).
  7. Integración en backend/pipeline/images.py:
     - Flag OFF: comportamiento previo intacto (Plan 0 no interviene).
     - Flag ON + éxito: archivo aceptado y estilo 'flow_mcp' registrado.
     - Flag ON + fallo/timeout/auth/corrupción: degradación segura (fallback) a planes siguientes.
  8. Preservación estricta de F5.1 (extension/injector.js y manifest intactos).
"""
import asyncio
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Asegurar backend en sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
from pipeline import images as imgs_pipeline
from services import flow_mcp_client


def _create_valid_png(path: Path, width: int = 120, height: int = 120, min_bytes: int = 4096) -> Path:
    """Genera un archivo PNG 100% válido y verificable según RFC 2083 con tamaño > min_bytes."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # Filtro: None
        for x in range(width):
            raw_rows.extend([((x * 7) ^ (y * 13)) & 0xFF, (x + y) & 0xFF, (x * y) & 0xFF])

    compressed = zlib.compress(bytes(raw_rows))
    idat = chunk(b"IDAT", compressed)

    chunks = [ihdr, idat]
    current_size = len(header) + sum(len(c) for c in chunks) + 12
    if current_size < min_bytes:
        pad_size = min_bytes - current_size + 128
        chunks.append(chunk(b"tEXt", b"Comment\x00" + b"A" * pad_size))

    chunks.append(chunk(b"IEND", b""))
    path.write_bytes(header + b"".join(chunks))
    return path


class TestFlowMCPConfigAndAvailability(unittest.TestCase):
    def test_default_flag_is_disabled(self):
        """Verifica que por defecto el feature flag esté desactivado."""
        self.assertFalse(config.FLOW_MCP_ENABLED)
        self.assertFalse(flow_mcp_client.available())

    def test_available_when_flag_enabled_and_files_exist(self):
        """Verifica que available() sea True solo si el flag está ON y los archivos existen."""
        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch("services.flow_mcp_client.get_node_bin", return_value="node"):
                self.assertTrue(flow_mcp_client.available())

    def test_unavailable_when_node_missing(self):
        """Si node no está disponible, available() debe ser False aunque el flag esté ON."""
        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch("services.flow_mcp_client.get_node_bin", return_value=None):
                self.assertFalse(flow_mcp_client.available())

    def test_unavailable_when_script_missing(self):
        """Si el script mcp.js no existe, available() debe ser False."""
        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch.object(config, "FLOW_MCP_DIR", Path("/ruta/inexistente")):
                with patch("services.flow_mcp_client.get_node_bin", return_value="node"):
                    self.assertFalse(flow_mcp_client.available())


class TestFlowMCPFileVerificationAndParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.td = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_verify_non_existent_file(self):
        fake = self.td / "no_existe.png"
        self.assertFalse(flow_mcp_client.verify_image_file(fake))

    def test_verify_empty_file(self):
        empty = self.td / "empty.png"
        empty.write_bytes(b"")
        self.assertFalse(flow_mcp_client.verify_image_file(empty))

    def test_verify_too_small_file(self):
        small = self.td / "small.png"
        small.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.assertFalse(flow_mcp_client.verify_image_file(small, min_bytes=4096))

    def test_verify_corrupted_file_above_min_bytes(self):
        corrupt = self.td / "corrupt.png"
        corrupt.write_bytes(b"not a real png data" * 300)  # > 4KB de basura sin magic bytes
        self.assertFalse(flow_mcp_client.verify_image_file(corrupt))

    def test_verify_valid_png_file(self):
        valid = self.td / "valid.png"
        _create_valid_png(valid, 120, 120)
        self.assertGreater(valid.stat().st_size, 4096)
        self.assertTrue(flow_mcp_client.verify_image_file(valid))

    def test_parse_image_paths_real_format(self):
        valid = self.td / "img_real.png"
        _create_valid_png(valid, 120, 120)

        real_text = f"Generated 1 image(s) in 14s with 2 (1:1):\n{valid}"
        parsed = flow_mcp_client.parse_image_paths_from_text(real_text, verify=True)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].resolve(), valid.resolve())

    def test_parse_image_paths_multi_line_with_invalid(self):
        valid = self.td / "img_valid.png"
        _create_valid_png(valid, 120, 120)
        bad = self.td / "no_existe.png"

        text = f"Generated 2 image(s) in 25s with 2 (16:9):\n{valid}\n{bad}"
        parsed = flow_mcp_client.parse_image_paths_from_text(text, verify=True)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].resolve(), valid.resolve())

    def test_parse_empty_or_malformed_text(self):
        self.assertEqual(flow_mcp_client.parse_image_paths_from_text(""), [])
        self.assertEqual(flow_mcp_client.parse_image_paths_from_text("Error: algo falló"), [])
        self.assertEqual(flow_mcp_client.parse_image_paths_from_text(None), [])


class TestFlowMCPProcessLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_call_tool_when_unavailable_raises_error(self):
        with patch.object(flow_mcp_client, "available", return_value=False):
            with self.assertRaises(flow_mcp_client.FlowMCPError):
                await flow_mcp_client.call_tool("flow_list_assets", {})

    async def test_call_tool_handshake_and_success(self):
        """Simula el flujo stdio JSON-RPC secuencial de Node.js con éxito."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.is_closing = MagicMock(return_value=False)
        mock_proc.stdin.close = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        responses = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "OK RESULT"}]}}) + "\n",
        ]

        async def mock_readline():
            if responses:
                return responses.pop(0).encode("utf-8")
            return b""

        mock_proc.stdout.readline = AsyncMock(side_effect=mock_readline)
        mock_proc.stderr.read = AsyncMock(return_value=b"")

        with patch.object(flow_mcp_client, "available", return_value=True):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
                result = await flow_mcp_client.call_tool("flow_test", {"param": 1})
                self.assertEqual(result, "OK RESULT")
                self.assertEqual(mock_proc.stdin.write.call_count, 3)

    async def test_call_tool_auth_error_detection(self):
        """Detecta error de autenticación 'Not signed in' y levanta FlowMCPAuthError."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.is_closing = MagicMock(return_value=False)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        responses = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
            json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "result": {"isError": True, "content": [{"type": "text", "text": "Flow generation failed: Not signed in to Google in the Flow Chrome."}]}
            }) + "\n",
        ]
        mock_proc.stdout.readline = AsyncMock(side_effect=lambda: responses.pop(0).encode("utf-8"))
        mock_proc.stderr.read = AsyncMock(return_value=b"")

        with patch.object(flow_mcp_client, "available", return_value=True):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
                with self.assertRaises(flow_mcp_client.FlowMCPAuthError):
                    await flow_mcp_client.call_tool("flow_generate_image", {"prompt": "test"})

    async def test_call_tool_timeout_kills_process(self):
        """En caso de timeout, el proceso es forzado a kill y se levanta FlowMCPTimeoutError."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.is_closing = MagicMock(return_value=False)
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def hang_readline():
            await asyncio.sleep(5.0)
            return b""

        mock_proc.stdout.readline = AsyncMock(side_effect=hang_readline)
        mock_proc.stderr.read = AsyncMock(return_value=b"")

        with patch.object(flow_mcp_client, "available", return_value=True):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
                with self.assertRaises(flow_mcp_client.FlowMCPTimeoutError):
                    await flow_mcp_client.call_tool("flow_test", {}, timeout=0.1)
                mock_proc.kill.assert_called()


class TestImagesPipelineFallbackIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.td = Path(self.temp_dir.name)
        self.project_id = "test_pid_001"
        self.project = {"id": self.project_id, "style": "cinematic", "format": "short"}
        self.scene = {"image_prompt": "Un robot en una nave espacial"}

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_flag_disabled_pipeline_preserves_legacy_flow(self):
        """Con FLOW_MCP_ENABLED=False, flow_mcp no se llama y corre el pipeline anterior."""
        with patch.object(config, "FLOW_MCP_ENABLED", False):
            with patch.object(imgs_pipeline, "scene_dir", return_value=self.td):
                with patch("services.gemini_client.available", return_value=False):
                    with patch("pipeline.images._zai_image", AsyncMock(return_value=False)):
                        with patch("database.take_ext_image", return_value=None):
                            out, method = await imgs_pipeline.generate_scene_image(self.scene, self.project, 1)
                            self.assertEqual(method, "placeholder")
                            self.assertTrue(out.is_file())

    async def test_flag_enabled_success_produces_flow_mcp_method(self):
        """Con FLOW_MCP_ENABLED=True y éxito, se copia el archivo y se registra 'flow_mcp'."""
        valid_generated = self.td / "flow_out.png"
        _create_valid_png(valid_generated, 120, 120)

        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch.object(imgs_pipeline, "scene_dir", return_value=self.td):
                with patch("services.flow_mcp_client.available", return_value=True):
                    with patch("services.flow_mcp_client.generate_image", AsyncMock(return_value=[valid_generated])):
                        out, method = await imgs_pipeline.generate_scene_image(self.scene, self.project, 1)
                        self.assertEqual(method, "flow_mcp")
                        self.assertTrue(out.is_file())
                        self.assertGreater(out.stat().st_size, 4096)

    async def test_flag_enabled_failure_gracefully_falls_back(self):
        """Con FLOW_MCP_ENABLED=True pero fallo en MCP, se degrada limpiamente a Gemini/Placeholder."""
        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch.object(imgs_pipeline, "scene_dir", return_value=self.td):
                with patch("services.flow_mcp_client.available", return_value=True):
                    with patch("services.flow_mcp_client.generate_image", AsyncMock(side_effect=flow_mcp_client.FlowMCPAuthError("No login"))):
                        with patch("services.gemini_client.available", return_value=False):
                            with patch("pipeline.images._zai_image", AsyncMock(return_value=False)):
                                with patch("database.take_ext_image", return_value=None):
                                    out, method = await imgs_pipeline.generate_scene_image(self.scene, self.project, 1)
                                    self.assertEqual(method, "placeholder")
                                    self.assertTrue(out.is_file())

    async def test_flag_enabled_invalid_file_rejected_and_falls_back(self):
        """Si flow_generate_image devuelve un archivo vacío/corrupto, no se acepta como escena."""
        bad_file = self.td / "bad.png"
        bad_file.write_bytes(b"corrupt junk")

        with patch.object(config, "FLOW_MCP_ENABLED", True):
            with patch.object(imgs_pipeline, "scene_dir", return_value=self.td):
                with patch("services.flow_mcp_client.available", return_value=True):
                    with patch("services.flow_mcp_client.generate_image", AsyncMock(return_value=[bad_file])):
                        with patch("services.gemini_client.available", return_value=False):
                            with patch("pipeline.images._zai_image", AsyncMock(return_value=False)):
                                with patch("database.take_ext_image", return_value=None):
                                    out, method = await imgs_pipeline.generate_scene_image(self.scene, self.project, 1)
                                    self.assertEqual(method, "placeholder")
                                    self.assertTrue(out.is_file())


class TestF51PreservationAndNonRegressions(unittest.TestCase):
    def test_extension_injector_and_manifest_intact(self):
        """Verifica que extension/manifest.json siga en 2.6.0 y no se haya tocado injector.js."""
        mf_path = REPO_ROOT / "extension" / "manifest.json"
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
        self.assertEqual(mf.get("version"), "2.6.0")

        diff_res = subprocess.run(
            ["git", "diff", "HEAD", "--", "extension/injector.js"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        self.assertEqual(diff_res.stdout.strip(), "", "extension/injector.js no debe ser modificado")


def main():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
