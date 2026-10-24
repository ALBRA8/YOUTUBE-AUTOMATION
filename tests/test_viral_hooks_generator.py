"""
Batería de Pruebas: Generador A/B de Hooks Virales (0-3s)
ClonaKit / Anai Gap Feature #1

Verifica:
  1. Generador de hooks en script_gen (Variantes A, B, C con ángulos psicológicos).
  2. Integración en build_result (retención de variantes en el guion).
  3. Endpoint REST POST /api/pipeline/generate-hooks.
  4. Endpoint REST POST /api/projects/{pid}/select-hook y sincronización de Escena 1.
"""
import sys
import unittest
import asyncio
from pathlib import Path

# Inyectar backend en path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from pipeline import script_gen
import database as db
from main import app
from fastapi.testclient import TestClient


class TestViralHooksGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_local_fallback_hooks_structure(self):
        """Verifica que el generador local genere 3 variantes bien estructuradas."""
        hooks = script_gen._local_fallback_hooks("Curiosidades del Espacio", niche="Ciencia")
        self.assertEqual(len(hooks), 3)

        # Variante A: Curiosidad
        self.assertEqual(hooks[0]["id"], "A")
        self.assertEqual(hooks[0]["type"], "Curiosidad")
        self.assertTrue(len(hooks[0]["hook"]) > 10)
        self.assertIn("Curiosidades del Espacio", hooks[0]["hook"])
        self.assertTrue(len(hooks[0]["visual_cue"]) > 5)
        self.assertIn("%", hooks[0]["estimated_retention"])

        # Variante B: Contradicción
        self.assertEqual(hooks[1]["id"], "B")
        self.assertEqual(hooks[1]["type"], "Contradicción")
        self.assertTrue(len(hooks[1]["hook"]) > 10)

        # Variante C: Dato Chocante
        self.assertEqual(hooks[2]["id"], "C")
        self.assertEqual(hooks[2]["type"], "Dato Chocante")
        self.assertTrue(len(hooks[2]["hook"]) > 10)

    def test_generate_viral_hooks_async(self):
        """Verifica la función async pública generate_viral_hooks."""
        hooks = asyncio.run(script_gen.generate_viral_hooks("Inteligencia Artificial"))
        self.assertIsInstance(hooks, list)
        self.assertGreaterEqual(len(hooks), 3)
        for h in hooks:
            self.assertIn("id", h)
            self.assertIn("type", h)
            self.assertIn("label", h)
            self.assertIn("hook", h)
            self.assertIn("visual_cue", h)
            self.assertIn("estimated_retention", h)

    def test_build_result_includes_hook_variants(self):
        """build_result debe garantizar que hook_variants exista en el guion."""
        raw = {
            "title": "Misterios Submarinos",
            "scenes": [
                {"title": "Escena 1", "narration": "Texto inicial", "image_prompt": "underwater shot"}
            ]
        }
        res = script_gen.build_result(raw)
        self.assertIn("hook_variants", res)
        self.assertEqual(len(res["hook_variants"]), 3)
        self.assertIn("selected_hook_id", res)
        self.assertEqual(res["selected_hook_id"], "A")
        self.assertTrue(len(res["hook"]) > 0)

    def test_api_generate_hooks_success(self):
        """POST /api/pipeline/generate-hooks debe responder 200 con la lista de hooks."""
        resp = self.client.post("/api/pipeline/generate-hooks", json={
            "topic": "Historia Secreta",
            "niche": "Misterio",
            "count": 3
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("topic"), "Historia Secreta")
        self.assertEqual(len(data.get("hooks", [])), 3)
        self.assertEqual(data["hooks"][0]["id"], "A")

    def test_api_generate_hooks_validation_error(self):
        """POST /api/pipeline/generate-hooks sin topic debe retornar 400."""
        resp = self.client.post("/api/pipeline/generate-hooks", json={})
        self.assertEqual(resp.status_code, 400)

    def test_api_select_hook_updates_project_and_scenes(self):
        """POST /api/projects/{pid}/select-hook debe actualizar project y Escena 1."""
        # 1. Crear proyecto de prueba en SQLite
        proj = db.create_project(
            title="Prueba Hooks A/B",
            mode="idea",
            status="draft",
            meta={"hook_variants": [{"id": "B", "hook": "Hook Variante B", "type": "Contradicción"}]}
        )
        pid = proj["id"]

        # 2. Asignar escenas iniciales
        scenes = [
            {"title": "Intro", "narration": "Narración vieja", "image_prompt": "prompt 1"},
            {"title": "Cuerpo", "narration": "Narración 2", "image_prompt": "prompt 2"}
        ]
        db.replace_scenes(pid, scenes)

        # 3. Aplicar Hook Variante B
        resp = self.client.post(f"/api/projects/{pid}/select-hook", json={
            "hook_id": "B",
            "hook_text": "Todo lo que sabías sobre este tema es falso."
        })
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()
        self.assertTrue(res_data.get("ok"))
        self.assertEqual(res_data.get("selected_hook_id"), "B")

        # 4. Verificar en base de datos
        updated_proj = db.get_project(pid)
        self.assertEqual(updated_proj["meta"]["selected_hook_id"], "B")
        self.assertEqual(updated_proj["meta"]["hook"], "Todo lo que sabías sobre este tema es falso.")

        updated_scenes = db.get_scenes(pid)
        self.assertEqual(updated_scenes[0]["narration"], "Todo lo que sabías sobre este tema es falso.")

        # Cleanup
        db.delete_project(pid)


if __name__ == "__main__":
    unittest.main()
