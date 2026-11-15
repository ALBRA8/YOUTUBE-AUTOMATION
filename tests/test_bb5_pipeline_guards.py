#!/usr/bin/env python3
"""
Tests herméticos para BB5:
1. pipeline_orchestrator: abortar con BLUEPRINT_DEMO si res2["engine"] == "local-demo"
   y PIPELINE_ALLOW_DEMO != "1".
2. pipeline_orchestrator & API: parámetro opcional max_scenes (1-12) recorta el blueprint
   a N escenas antes de la etapa 3 conservando la última como cierre.
3. mcp_manager: _sync_auth_json no escribe si cookies está vacío o no contiene
   SID ni __Secure-1PSID; escritura atómica y sin excepciones genéricas.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402


class MockManagerBB5:
    """Mock hermético de MCPManager para etapa 1 y 3."""
    def __init__(self, tools=None):
        self.tools = tools if tools is not None else [{"name": "notebook_query"}]
        self.executed_calls = []

    async def status(self):
        return {
            "notebooklm": {"state": "connected", "auth": "connected", "detail": "ok"},
            "google-flow": {"state": "connected", "auth": "connected", "detail": "ok", "browser_up": True},
        }

    async def test_pipeline(self, service: str, notebook_id=None):
        return {"service": service, "ok": True, "error": None}

    async def tools_catalog(self, service: str, auto_connect=True):
        return {"tools": self.tools}

    async def execute(self, service: str, tool: str, arguments: dict, timeout=None, **kwargs):
        self.executed_calls.append((service, tool, arguments))
        if tool == "notebook_query":
            return {"ok": True, "text": json.dumps({"status": "success", "answer": "Contexto mock"})}
        if tool == "flow_upload_file":
            return {"ok": True, "text": json.dumps({"asset_id": "asset_ref_1"})}
        if tool == "flow_generate_video":
            return {"ok": True, "text": json.dumps({"video_file": "vid_mock.mp4"})}
        return {"ok": True, "text": "{}"}


def test_bb5_stage2_blueprint_demo_aborts_when_not_allowed(monkeypatch):
    """BB5.1: si engine es local-demo y PIPELINE_ALLOW_DEMO != '1', abortar con BLUEPRINT_DEMO."""
    with tempfile.TemporaryDirectory() as td:
        runs_dir = Path(td)
        mgr = MockManagerBB5()
        orch = po.PipelineOrchestrator(
            manager=mgr,
            runs_dir=runs_dir,
        )

        async def mock_from_idea(*args, **kwargs):
            return {
                "title": "Historia Demo",
                "engine": "local-demo",
                "scenes": [
                    {"title": "E1", "narration": "N1", "image_prompt": "P1"},
                    {"title": "E2", "narration": "N2", "image_prompt": "P2"},
                ]
            }

        monkeypatch.setattr(po.script_gen, "from_idea", mock_from_idea)
        monkeypatch.setattr(po.script_gen, "build_result", lambda raw: raw)
        monkeypatch.delenv("PIPELINE_ALLOW_DEMO", raising=False)

        run = orch.create_run(idea="Prueba demo", notebook_id="nb_mock")
        import asyncio
        asyncio.run(orch._run(run["run_id"]))

        st = orch.get_status(run["run_id"])
        assert st["stage"] == "error"
        assert st["error_code"] == "BLUEPRINT_DEMO"
        assert "Gemini no respondió (¿GEMINI_API_KEY inválida?): el guion salió del generador demo y no se despacha a Flow" in st["error_detail"]

        step2 = [s for s in st["steps"] if s["stage"] == "stage2_blueprint"][0]
        assert step2["state"] == "failed"
        assert "[BLUEPRINT_DEMO]" in step2["detail"]


def test_bb5_stage2_blueprint_demo_allowed_when_env_set(monkeypatch):
    """BB5.1: si PIPELINE_ALLOW_DEMO == '1', se permite continuar con local-demo."""
    with tempfile.TemporaryDirectory() as td:
        runs_dir = Path(td)
        mgr = MockManagerBB5()
        orch = po.PipelineOrchestrator(
            manager=mgr,
            runs_dir=runs_dir,
        )

        async def mock_from_idea(*args, **kwargs):
            return {
                "title": "Historia Demo",
                "engine": "local-demo",
                "scenes": [
                    {"title": "E1", "narration": "N1", "image_prompt": "P1"},
                ]
            }

        async def mock_stage3(run):
            run["done_count"] = 1
            for sc in run["scenes"]:
                sc["status"] = "ok"

        monkeypatch.setattr(po.script_gen, "from_idea", mock_from_idea)
        monkeypatch.setattr(po.script_gen, "build_result", lambda raw: raw)
        monkeypatch.setattr(orch, "_stage3", mock_stage3)
        monkeypatch.setenv("PIPELINE_ALLOW_DEMO", "1")

        run = orch.create_run(idea="Prueba demo permitida", notebook_id="nb_mock")
        import asyncio
        asyncio.run(orch._run(run["run_id"]))

        st = orch.get_status(run["run_id"])
        assert st["stage"] == "done"
        assert st["error_code"] == ""


def test_bb5_max_scenes_trimming(monkeypatch):
    """BB5.2: max_scenes recorta el blueprint a N escenas conservando la última como cierre."""
    with tempfile.TemporaryDirectory() as td:
        runs_dir = Path(td)
        mgr = MockManagerBB5()
        orch = po.PipelineOrchestrator(
            manager=mgr,
            runs_dir=runs_dir,
        )

        async def mock_from_idea(*args, **kwargs):
            return {
                "title": "Historia 7 escenas",
                "engine": "gemini-2.5-flash",
                "scenes": [
                    {"title": f"Escena {i}", "narration": f"N{i}", "image_prompt": f"P{i}"}
                    for i in range(1, 8)
                ]
            }

        async def mock_stage3(run):
            run["done_count"] = len(run["scenes"])
            for sc in run["scenes"]:
                sc["status"] = "ok"

        monkeypatch.setattr(po.script_gen, "from_idea", mock_from_idea)
        monkeypatch.setattr(po.script_gen, "build_result", lambda raw: raw)
        monkeypatch.setattr(orch, "_stage3", mock_stage3)

        # 1. max_scenes = 3 de 7 escenas -> conserva 1, 2 y 7 (reindexadas a s1, s2, s3)
        run = orch.create_run(idea="Prueba recorte", notebook_id="nb_mock", max_scenes=3)
        import asyncio
        asyncio.run(orch._run(run["run_id"]))

        st = orch.get_status(run["run_id"])
        scenes = st["scenes"]
        assert len(scenes) == 3
        assert scenes[0]["title"] == "Escena 1"
        assert scenes[0]["scene_id"] == "s1"
        assert scenes[1]["title"] == "Escena 2"
        assert scenes[1]["scene_id"] == "s2"
        assert scenes[2]["title"] == "Escena 7"  # Última escena como cierre
        assert scenes[2]["scene_id"] == "s3"

        # 2. max_scenes = 1 de 7 escenas -> conserva solo la escena 7 (cierre)
        run1 = orch.create_run(idea="Prueba recorte a 1", notebook_id="nb_mock", max_scenes=1)
        asyncio.run(orch._run(run1["run_id"]))
        st1 = orch.get_status(run1["run_id"])
        assert len(st1["scenes"]) == 1
        assert st1["scenes"][0]["title"] == "Escena 7"
        assert st1["scenes"][0]["scene_id"] == "s1"

        # 3. max_scenes no definido -> se conservan las 7
        run_all = orch.create_run(idea="Prueba sin recorte", notebook_id="nb_mock")
        asyncio.run(orch._run(run_all["run_id"]))
        st_all = orch.get_status(run_all["run_id"])
        assert len(st_all["scenes"]) == 7


def test_bb5_max_scenes_validation():
    """BB5.2: validación estricta de max_scenes (1-12)."""
    mgr = MockManagerBB5()
    orch = po.PipelineOrchestrator(manager=mgr)

    with pytest.raises(po.PipelineError) as exc0:
        orch.create_run(idea="Inválido 0", max_scenes=0)
    assert exc0.value.code == "INVALID_MAX_SCENES"

    with pytest.raises(po.PipelineError) as exc13:
        orch.create_run(idea="Inválido 13", max_scenes=13)
    assert exc13.value.code == "INVALID_MAX_SCENES"

    with pytest.raises(po.PipelineError) as exc_str:
        orch.create_run(idea="Inválido no-entero", max_scenes="cinco")
    assert exc_str.value.code == "INVALID_MAX_SCENES"


def test_bb5_sync_auth_json_validation_and_atomicity():
    """BB5.3: _sync_auth_json no escribe si vacío o sin cookie de sesión, escribe atómico con chmod."""
    client_mgr = mcpm.MCPClientManager()

    with tempfile.TemporaryDirectory() as td:
        auth_file = Path(td) / "auth.json"

        # 1. Lista de cookies vacía -> no escribe
        res = client_mgr._sync_auth_json([], target_path=auth_file)
        assert res is False
        assert not auth_file.exists()

        # 2. Cookies sin SID ni __Secure-1PSID -> no escribe
        irrelevant_cookies = [
            {"name": "theme", "value": "dark"},
            {"name": "pref", "value": "es"},
        ]
        res = client_mgr._sync_auth_json(irrelevant_cookies, target_path=auth_file)
        assert res is False
        assert not auth_file.exists()

        # 3. Cookies válidas con SID -> escribe atómicamente
        valid_cookies = [
            {"name": "theme", "value": "dark"},
            {"name": "SID", "value": "mock_sid_value"},
        ]
        res = client_mgr._sync_auth_json(valid_cookies, target_path=auth_file)
        assert res is True
        assert auth_file.exists()

        data = json.loads(auth_file.read_text(encoding="utf-8"))
        assert data["cookies"]["SID"] == "mock_sid_value"
        assert data["cookies"]["theme"] == "dark"

        # 4. Segunda escritura con __Secure-1PSID preservando csrf_token previo
        data["csrf_token"] = "token_previo_123"
        auth_file.write_text(json.dumps(data), encoding="utf-8")

        new_cookies = [
            {"name": "__Secure-1PSID", "value": "mock_secure_sid"},
        ]
        res2 = client_mgr._sync_auth_json(new_cookies, target_path=auth_file)
        assert res2 is True
        data2 = json.loads(auth_file.read_text(encoding="utf-8"))
        assert data2["cookies"]["__Secure-1PSID"] == "mock_secure_sid"
        assert data2["csrf_token"] == "token_previo_123"


if __name__ == "__main__":
    import sys
    # Batería standalone (tests/run_all.py): plugin pytest para resumen parseable
    class _Resumen:
        def __init__(self) -> None:
            self.ok = self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
