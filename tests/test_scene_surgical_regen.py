#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-039 · Tarjetas de Escenas con Regeneración Quirúrgica

Valida la regeneración de tomas individuales de Google Flow y el soporte
de retry forzado en el orquestador:
1. retry_scenes con force=True permite reintentar una toma individual ya 'done'
   sin relanzar el resto del video ni disparar NO_FAILED_SCENES.
2. retry_scenes con force=False preserva la guardia estricta NO_FAILED_SCENES.
3. retry_scenes con force=True y escena inexistente dispara NO_TARGET_SCENES.
4. Endpoint REST /api/pipeline/retry-scenes acepta {"force": true, "scene_ids": [...]}.
5. Endpoint REST /api/scenes/{scene_id}/regenerate-flow regenera y actualiza
   la imagen de la escena en SQLite con 200 OK y 404 en escena inexistente.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
import main  # noqa: E402

OK, FAIL = 0, 0


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


class FakeManager:
    """Mock determinista de MCPClientManager para pruebas herméticas."""
    def __init__(self):
        self.calls = []

    async def test_pipeline(self, target, notebook_id=None):
        return {"ok": True, "state": "connected", "auth": "connected"}

    async def execute(self, target, tool, args, timeout=None, notebook_id=None):
        self.calls.append((target, tool, args))
        if tool == "flow_generate_image":
            return {"text": f"Saved image to /tmp/fake_flow_{len(self.calls)}.png"}
        if tool == "flow_generate_video":
            return {"text": f"Saved video to /tmp/fake_flow_{len(self.calls)}.mp4"}
        if tool == "flow_upload_file":
            return {"text": "Uploaded asset fake_asset"}
        return {"text": "ok"}


def _setup_test_run(orch: po.PipelineOrchestrator) -> str:
    """Crea una corrida con 3 escenas, todas en status 'done'."""
    run = orch.create_run("historia de prueba", "short", "documentary")
    rid = run["run_id"]
    rd = orch._run_dir(rid)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "context.md").write_text("Contexto verificable de prueba", encoding="utf-8")
    run["stage"] = po.ST_DONE
    run["progress_pct"] = 100
    run["reference_asset"] = "personaje"
    run["done_count"] = 3
    run["dispatched"] = 3
    run["scenes"] = [
        {"scene_id": "s1", "title": "Intro", "narration": "Narr 1", "image_prompt": "Prompt 1", "status": "done", "attempts": 1, "video_file": "/tmp/s1.mp4", "detail": ""},
        {"scene_id": "s2", "title": "Nudo", "narration": "Narr 2", "image_prompt": "Prompt 2", "status": "done", "attempts": 1, "video_file": "/tmp/s2.mp4", "detail": ""},
        {"scene_id": "s3", "title": "Desenlace", "narration": "Narr 3", "image_prompt": "Prompt 3", "status": "done", "attempts": 1, "video_file": "/tmp/s3.mp4", "detail": ""},
    ]
    orch._save(run)
    return rid


async def test_orchestrator_force_retry():
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=FakeManager(), runs_dir=Path(td))
        rid = _setup_test_run(orch)

        # 1) Sin force: intentar retry de escena 'done' debe fallar con NO_FAILED_SCENES
        try:
            await orch.retry_scenes(rid, ["s2"], force=False)
            check("retry_scenes sin force sobre escena 'done' lanza error", False)
        except po.PipelineError as e:
            check("retry_scenes sin force sobre escena 'done' lanza error", True)
            check("error es NO_FAILED_SCENES", e.code == "NO_FAILED_SCENES", e.code)

        # 2) Con force: retry quirúrgico SOLO de s2
        updated = await orch.retry_scenes(rid, ["s2"], force=True)
        check("retry_scenes con force=True completa 100%", updated["progress_pct"] == 100)
        check("done_count permanece consistente en 3", updated["done_count"] == 3, str(updated["done_count"]))

        s1 = next(s for s in updated["scenes"] if s["scene_id"] == "s1")
        s2 = next(s for s in updated["scenes"] if s["scene_id"] == "s2")
        s3 = next(s for s in updated["scenes"] if s["scene_id"] == "s3")

        check("s2 attempts incrementado a 2", s2["attempts"] == 2, str(s2["attempts"]))
        check("s1 attempts permanece en 1 (no re-ejecutado)", s1["attempts"] == 1, str(s1["attempts"]))
        check("s3 attempts permanece en 1 (no re-ejecutado)", s3["attempts"] == 1, str(s3["attempts"]))
        check("s2 status es done", s2["status"] == "done")

        # 3) Con force pero id inexistente
        try:
            await orch.retry_scenes(rid, ["s99"], force=True)
            check("escena inexistente lanza NO_TARGET_SCENES", False)
        except po.PipelineError as e:
            check("escena inexistente lanza NO_TARGET_SCENES", e.code == "NO_TARGET_SCENES", e.code)


def test_api_endpoints():
    client = TestClient(main.app)

    # 1) Endpoint /api/pipeline/retry-scenes con force
    with tempfile.TemporaryDirectory() as td:
        fake_mgr = FakeManager()
        custom_orch = po.PipelineOrchestrator(manager=fake_mgr, runs_dir=Path(td))
        rid = _setup_test_run(custom_orch)

        with patch("services.pipeline_orchestrator.orchestrator", custom_orch), \
             patch("main._pipe.orchestrator", custom_orch):
            res = client.post("/api/pipeline/retry-scenes", json={"run_id": rid, "scene_ids": ["s3"], "force": True})
            check("POST /api/pipeline/retry-scenes con force responde 200", res.status_code == 200, str(res.status_code))
            data = res.json()
            s3 = next(s for s in data["scenes"] if s["scene_id"] == "s3")
            check("s3 re-despachada y attempts=2", s3["attempts"] == 2, str(s3["attempts"]))

    # 2) Endpoint /api/scenes/{scene_id}/regenerate-flow
    # Configurar proyecto y escena en SQLite
    pid = db.new_id()
    sc_id = db.new_id()
    db.create_project(id=pid, title="Proyecto Quirurgico", style="cinematic", format="short")
    with db.connect() as con:
        con.execute(
            "INSERT INTO scenes (id, project_id, idx, title, narration, image_prompt, image_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sc_id, pid, 0, "Escena 1", "Texto narrativo", "Prompt visual", "/tmp/old_image.png")
        )

    # Mock de imgs_pipeline.generate_scene_image
    async def fake_gen_image(sc, pr, idx, ref=None):
        return Path("/tmp/new_flow_image.png"), "flow"

    with patch("pipeline.images.generate_scene_image", side_effect=fake_gen_image):
        res = client.post(f"/api/scenes/{sc_id}/regenerate-flow", json={"project_id": pid})
        check("POST /api/scenes/{id}/regenerate-flow responde 200", res.status_code == 200, str(res.status_code))
        body = res.json()
        check("respuesta ok es True", body.get("ok") is True)
        check("method es flow", body.get("method") == "flow")
        check("image url presente", f"/api/scenes/{sc_id}/image" in body.get("image", ""))

        # Verificar que la DB se actualizo
        sc = db.get_scene_for_project(pid, sc_id)
        check("DB image_path actualizado con la nueva ruta", sc["image_path"] == str(Path("/tmp/new_flow_image.png")))

    # 3) Error 404 en escena inexistente
    res_404 = client.post(f"/api/scenes/{db.new_id()}/regenerate-flow", json={"project_id": pid})
    check("POST /api/scenes/inexistente responde 404", res_404.status_code == 404, str(res_404.status_code))


def main_test():
    print("=" * 60)
    print("BATERÍA INT-039 · Tarjetas de Escenas con Regeneración Quirúrgica")
    print("=" * 60)

    print("\n── S1 · Orquestador: retry quirúrgico forzado (force=True) ──")
    asyncio.run(test_orchestrator_force_retry())

    print("\n── S2 · Endpoints REST: pipeline retry forzado y scene flow regen ──")
    test_api_endpoints()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())
