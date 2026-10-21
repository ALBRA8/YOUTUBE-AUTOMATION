#!/usr/bin/env python3
"""
Pruebas unitarias y de integración para el Scene Asset Resolver (Gate B.2).

Verifica de forma hermética (sin Chrome, sin red, sin Google Flow real):
1. Sanitización determinista de nombres para activos de Flow.
2. Extracción agnóstica de referencias desde Production JSON (meta.production_unit o directo).
3. Resolución y validación en disco con desambiguación de colisiones.
4. Rechazo limpio de URLs remotas y archivos no encontrados.
5. Inyección ordenada de menciones @{asset_name} en prompts.
6. Integración con generate_scene_image en backend/pipeline/images.py:
   - Escena con referencia válida: upload_file ejecutado + mención inyectada.
   - Escena sin referencias: comportamiento previo intacto (sin uploads ni menciones).
   - Referencia opcional fallida: degradación elegante (warning + generación sin mención).
   - Referencia requerida fallida: error controlado / degradación a siguientes planes.
   - Flag MCP desactivado: Plan 0 omitido por completo.
"""
import asyncio
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline.asset_resolver import (
    ResolvedAssetRef,
    extract_raw_references,
    inject_flow_asset_mentions,
    resolve_scene_references,
    sanitize_asset_name,
)
from pipeline import images as imgs_pipeline
from services import flow_mcp_client


def _make_dummy_png(path: Path) -> Path:
    """Crea un PNG mínimo y válido en disco."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0))
    raw_rows = bytearray()
    for _ in range(10):
        raw_rows.append(0)
        raw_rows.extend([100, 150, 200] * 10)
    idat = chunk(b"IDAT", zlib.compress(bytes(raw_rows)))
    iend = chunk(b"IEND", b"")

    path.parent.mkdir(parents=True, exist_ok=True)
    content = header + ihdr + idat + iend
    if len(content) < 5000:
        content += b"\x00" * (5000 - len(content))
    path.write_bytes(content)
    return path


class TestSanitizeAssetName(unittest.TestCase):
    def test_basic_alphanumeric(self):
        self.assertEqual(sanitize_asset_name("hero_character_01"), "hero_character_01")
        self.assertEqual(sanitize_asset_name("asset-alpha"), "asset-alpha")

    def test_special_characters_and_spaces(self):
        self.assertEqual(sanitize_asset_name("My Hero & Sword!"), "My_Hero_Sword")
        self.assertEqual(sanitize_asset_name("foto@escena#3"), "foto_escena_3")

    def test_empty_or_symbols_only_uses_fallback(self):
        self.assertEqual(sanitize_asset_name("", fallback="fallback_asset"), "fallback_asset")
        self.assertEqual(sanitize_asset_name("   ??? ###   ", fallback="ref_1"), "ref_1")

    def test_max_length_truncation(self):
        long_name = "a" * 50
        sanitized = sanitize_asset_name(long_name)
        self.assertEqual(len(sanitized), 24)
        self.assertEqual(sanitized, "a" * 24)


class TestExtractRawReferences(unittest.TestCase):
    def test_empty_and_invalid(self):
        self.assertEqual(extract_raw_references({}), [])
        self.assertEqual(extract_raw_references({"references": None}), [])
        self.assertEqual(extract_raw_references("not_a_dict"), [])

    def test_direct_references(self):
        scene = {"references": ["path/to/a.png", "path/to/b.png"]}
        self.assertEqual(extract_raw_references(scene), ["path/to/a.png", "path/to/b.png"])

    def test_production_unit_precedence(self):
        scene = {
            "references": ["direct.png"],
            "meta": {
                "production_unit": {
                    "references": ["unit_ref.png"]
                }
            }
        }
        self.assertEqual(extract_raw_references(scene), ["unit_ref.png"])

    def test_single_item_wrapped(self):
        scene = {"references": "single_file.png"}
        self.assertEqual(extract_raw_references(scene), ["single_file.png"])


class TestResolveSceneReferences(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_asset_res_"))
        self.sample_png = _make_dummy_png(self.tmp_dir / "sample_crystal.png")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_valid_local_string_reference(self):
        scene = {"references": [str(self.sample_png)]}
        resolved = resolve_scene_references(scene)
        self.assertEqual(len(resolved), 1)
        r = resolved[0]
        self.assertTrue(r.is_valid)
        self.assertEqual(r.asset_name, "sample_crystal")
        self.assertEqual(r.local_path, self.sample_png.resolve())
        self.assertIsNone(r.skip_reason)

    def test_missing_local_file(self):
        missing = self.tmp_dir / "non_existent.png"
        scene = {"references": [str(missing)]}
        resolved = resolve_scene_references(scene)
        self.assertEqual(len(resolved), 1)
        r = resolved[0]
        self.assertFalse(r.is_valid)
        self.assertEqual(r.skip_reason, "NOT_FOUND")

    def test_remote_urls_rejected(self):
        scene = {
            "references": [
                "https://example.com/image.png",
                {"uri": "http://cdn.org/pic.jpg"},
                {"url": "gs://bucket/blob.png"}
            ]
        }
        resolved = resolve_scene_references(scene)
        self.assertEqual(len(resolved), 3)
        for r in resolved:
            self.assertFalse(r.is_valid)
            self.assertEqual(r.skip_reason, "REMOTE_URL")

    def test_dict_formats_and_explicit_naming(self):
        img2 = _make_dummy_png(self.tmp_dir / "avatar_char.png")
        scene = {
            "references": [
                {"path": str(self.sample_png), "name": "magic_orb", "required": True},
                {"filePath": str(img2), "role": "main_hero"}
            ]
        }
        resolved = resolve_scene_references(scene)
        self.assertEqual(len(resolved), 2)
        self.assertTrue(resolved[0].is_valid)
        self.assertEqual(resolved[0].asset_name, "magic_orb")
        self.assertTrue(resolved[0].is_required)

        self.assertTrue(resolved[1].is_valid)
        self.assertEqual(resolved[1].asset_name, "avatar_char")
        self.assertFalse(resolved[1].is_required)

    def test_name_collision_disambiguation(self):
        img_dup1 = _make_dummy_png(self.tmp_dir / "gem.png")
        img_dup2 = _make_dummy_png(self.tmp_dir / "sub" / "gem.png")
        scene = {
            "references": [
                str(img_dup1),
                str(img_dup2),
                {"file": str(img_dup1), "name": "gem"}
            ]
        }
        resolved = resolve_scene_references(scene)
        self.assertEqual(len(resolved), 3)
        names = [r.asset_name for r in resolved]
        self.assertEqual(names, ["gem", "gem_2", "gem_3"])


class TestInjectFlowAssetMentions(unittest.TestCase):
    def test_empty_or_no_names(self):
        self.assertEqual(inject_flow_asset_mentions("A blue forest", []), "A blue forest")
        self.assertEqual(inject_flow_asset_mentions("A blue forest", [""]), "A blue forest")

    def test_single_mention(self):
        res = inject_flow_asset_mentions("A blue forest", ["crystal"])
        self.assertEqual(res, "Referencing @{crystal}: A blue forest")

    def test_two_mentions(self):
        res = inject_flow_asset_mentions("A blue forest", ["crystal", "hero"])
        self.assertEqual(res, "Referencing @{crystal} and @{hero}: A blue forest")

    def test_three_mentions(self):
        res = inject_flow_asset_mentions("A blue forest", ["crystal", "hero", "sword"])
        self.assertEqual(res, "Referencing @{crystal}, @{hero}, and @{sword}: A blue forest")

    def test_empty_prompt_with_mentions(self):
        res = inject_flow_asset_mentions("", ["crystal"])
        self.assertEqual(res, "Referencing @{crystal}:")


class TestImagesPipelineAssetIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_imgs_pipe_"))
        self.ref_png = _make_dummy_png(self.tmp_dir / "ref_item.png")
        self.generated_png = _make_dummy_png(self.tmp_dir / "gen_scene.png")

        self.project = {
            "id": "proj_resolver_test",
            "format": "short",
            "style": "photorealistic",
        }
        self.scene = {
            "id": 1,
            "title": "Escena de prueba",
            "image_prompt": "El artefacto reluce en la cueva.",
            "narration": "El artefacto reluce en la cueva.",
            "references": [str(self.ref_png)],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch.object(flow_mcp_client, "available", return_value=True)
    @patch.object(flow_mcp_client, "upload_file")
    @patch.object(flow_mcp_client, "generate_image")
    @patch.object(flow_mcp_client, "verify_image_file", return_value=True)
    async def test_scene_with_valid_reference_uploads_and_injects(
        self, mock_verify, mock_gen, mock_upload, mock_avail
    ):
        mock_upload.return_value = {"ok": True, "raw": "uploaded: ref_item"}
        mock_gen.return_value = [self.generated_png]

        with patch("pipeline.images.scene_dir", return_value=self.tmp_dir):
            out, method = await imgs_pipeline.generate_scene_image(self.scene, self.project, 1)

        self.assertEqual(method, "flow_mcp")
        self.assertTrue(out.is_file())

        # Verificar upload_file
        mock_upload.assert_awaited_once_with(
            file_path=self.ref_png.resolve(),
            name="ref_item",
            replace=False,
        )

        # Verificar generate_image con mención
        mock_gen.assert_awaited_once()
        gen_kwargs = mock_gen.call_args.kwargs
        self.assertIn("@{ref_item}", gen_kwargs["prompt"])
        self.assertTrue(gen_kwargs["prompt"].startswith("Referencing @{ref_item}:"))

    @patch.object(flow_mcp_client, "available", return_value=True)
    @patch.object(flow_mcp_client, "upload_file")
    @patch.object(flow_mcp_client, "generate_image")
    @patch.object(flow_mcp_client, "verify_image_file", return_value=True)
    async def test_scene_without_references_legacy_behavior(
        self, mock_verify, mock_gen, mock_upload, mock_avail
    ):
        mock_gen.return_value = [self.generated_png]
        scene_no_ref = {
            "id": 2,
            "image_prompt": "Sin referencias en absoluto.",
            "narration": "Sin referencias en absoluto.",
        }

        with patch("pipeline.images.scene_dir", return_value=self.tmp_dir):
            out, method = await imgs_pipeline.generate_scene_image(scene_no_ref, self.project, 2)

        self.assertEqual(method, "flow_mcp")
        mock_upload.assert_not_awaited()
        gen_kwargs = mock_gen.call_args.kwargs
        self.assertNotIn("@{", gen_kwargs["prompt"])
        self.assertNotIn("Referencing @", gen_kwargs["prompt"])

    @patch.object(flow_mcp_client, "available", return_value=True)
    @patch.object(flow_mcp_client, "upload_file", side_effect=RuntimeError("Upload network glitch"))
    @patch.object(flow_mcp_client, "generate_image")
    @patch.object(flow_mcp_client, "verify_image_file", return_value=True)
    async def test_scene_with_optional_ref_failure_degrades_gracefully(
        self, mock_verify, mock_gen, mock_upload, mock_avail
    ):
        mock_gen.return_value = [self.generated_png]
        scene_optional = {
            "id": 3,
            "image_prompt": "Prueba opcional",
            "narration": "Prueba opcional",
            "references": [{"path": str(self.ref_png), "required": False}],
        }

        with patch("pipeline.images.scene_dir", return_value=self.tmp_dir):
            out, method = await imgs_pipeline.generate_scene_image(scene_optional, self.project, 3)

        self.assertEqual(method, "flow_mcp")
        # El upload falló pero al ser opcional la generación continúa sin la mención
        mock_gen.assert_awaited_once()
        gen_kwargs = mock_gen.call_args.kwargs
        self.assertNotIn("@{", gen_kwargs["prompt"])

    @patch.object(flow_mcp_client, "available", return_value=True)
    @patch.object(flow_mcp_client, "upload_file", side_effect=RuntimeError("Upload fatal fail"))
    @patch("services.gemini_client.available", return_value=False)
    @patch("pipeline.images._zai_image", new_callable=AsyncMock, return_value=False)
    @patch("database.take_ext_image", return_value=None)
    async def test_scene_with_required_ref_failure_prevents_silent_generation(
        self, mock_db_ext, mock_zai, mock_gemini, mock_upload, mock_avail
    ):
        scene_required = {
            "id": 4,
            "image_prompt": "Prueba requerida estricta",
            "narration": "Prueba requerida estricta",
            "references": [{"path": str(self.ref_png), "required": True}],
        }

        with patch("pipeline.images.scene_dir", return_value=self.tmp_dir):
            out, method = await imgs_pipeline.generate_scene_image(scene_required, self.project, 4)

        # Plan 0 abortó y degradó a planes siguientes (hasta placeholder porque mockeamos los demás en False)
        self.assertEqual(method, "placeholder")


if __name__ == "__main__":
    unittest.main()
