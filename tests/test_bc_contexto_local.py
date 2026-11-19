#!/usr/bin/env python3
"""
Tests herméticos para Contexto Local de Respaldo (BC):
1. auth-error con archivo → continúa en modo local (context_source: "local").
2. auth-error sin archivo → falla con mensaje "Sin sesión de NotebookLM y sin contexto local del nicho".
3. nicho_id con "../" o inválido es rechazado.
4. PIPELINE_CONTEXT_SOURCE=local salta NotebookLM por completo.
5. Éxito normal: context_source = "notebooklm" sin cambios.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402


class MockManagerBC:
    """Mock hermético de MCPClientManager para etapa 1 y 3."""
    def __init__(self, execute_result=None, execute_exc=None, tools=None):
        self.execute_result = execute_result
        self.execute_exc = execute_exc
        self.tools = tools if tools is not None else [{"name": "notebook_query"}]
        self.execute_calls = []

    async def status(self):
        return {
            "notebooklm": {"state": "connected", "auth": "connected", "detail": "ok"},
            "google-flow": {"state": "connected", "auth": "connected", "detail": "ok", "browser_up": True},
        }

    async def test_pipeline(self, service: str, notebook_id=None):
        return {"service": service, "ok": True, "error": None}

    async def tools_catalog(self, service: str, auto_connect=True):
        return {"tools": self.tools}

    async def execute(self, service, tool, args, timeout=60.0, notebook_id=None):
        self.execute_calls.append({"service": service, "tool": tool, "args": args})
        if self.execute_exc:
            raise self.execute_exc
        return self.execute_result or {"ok": True, "text": "Contexto mockeado de NotebookLM"}

    async def connect(self, service, notebook_id=None):
        return {"service": service, "state": mcpm.ST_CONNECTED, "tools": []}

    async def _exposed_tools(self, service):
        return {"notebook_query"}


@pytest.fixture
def temp_orchestrator():
    with tempfile.TemporaryDirectory() as td:
        runs_dir = Path(td) / "pipeline_runs"
        nichos_dir = Path(td) / "nichos"
        nichos_dir.mkdir(parents=True, exist_ok=True)

        orch = po.PipelineOrchestrator(runs_dir=runs_dir)
        with patch.object(config, "DATA_DIR", Path(td)):
            yield orch, Path(td)


def test_bc_nicho_id_traversal_rejected(temp_orchestrator):
    orch, td = temp_orchestrator

    # 1. Traversal con ../ rechazado
    with pytest.raises(po.PipelineError) as exc1:
        orch.create_run(idea="Test idea", nicho_id="../malicious")
    assert exc1.value.code == "INVALID_NICHO_ID"

    # 2. Caracteres inválidos
    with pytest.raises(po.PipelineError) as exc2:
        orch.create_run(idea="Test idea", nicho_id="Nicho_Con_Mayusculas!")
    assert exc2.value.code == "INVALID_NICHO_ID"


@pytest.mark.asyncio
async def test_bc_auth_error_with_local_file_continues(temp_orchestrator):
    orch, td = temp_orchestrator
    nicho_folder = td / "nichos" / "frutinovelas"
    nicho_folder.mkdir(parents=True, exist_ok=True)
    (nicho_folder / "contexto.md").write_text("# Contexto local de prueba", encoding="utf-8")

    # Simulamos que NotebookLM devuelve error de expiración de auth
    error_payload = {"status": "error", "error": "Authentication expired. Run notebooklm-mcp-auth"}
    mock_mgr = MockManagerBC(execute_result={"ok": True, "text": json.dumps(error_payload)})
    orch.manager = mock_mgr

    run = orch.create_run(
        idea="Idea de prueba",
        notebook_id="5b7728cb-3e1e-480f-ae82-786f61c0179b",
        nicho_id="frutinovelas"
    )

    # Mock stage 2 y 3 para concentrarnos en stage 1
    mock_raw = {"title": "Guion Test", "scenes": []}
    mock_blueprint = {
        "title": "Guion Test", "engine": "gemini-2.5",
        "scenes": [{"scene_id": "1", "image_prompt": "p", "narration": "n"}]
    }
    with patch("pipeline.script_gen.from_idea", AsyncMock(return_value=mock_raw)):
        with patch("pipeline.script_gen.build_result", return_value=mock_blueprint):
            with patch.object(orch, "_stage3", AsyncMock()):
                await orch._run(run["run_id"])

    loaded = orch.get_status(run["run_id"])
    assert loaded["stage"] == po.ST_DONE
    assert loaded["context_source"] == "local"
    assert loaded["context_chars"] == len("# Contexto local de prueba")

    saved_context = (orch._run_dir(run["run_id"]) / "context.md").read_text(encoding="utf-8")
    assert saved_context == "# Contexto local de prueba"


@pytest.mark.asyncio
async def test_bc_auth_error_without_local_file_fails(temp_orchestrator):
    orch, td = temp_orchestrator

    error_payload = {"status": "error", "error": "Authentication expired."}
    mock_mgr = MockManagerBC(execute_result={"ok": True, "text": json.dumps(error_payload)})
    orch.manager = mock_mgr

    run = orch.create_run(
        idea="Idea de prueba",
        notebook_id="5b7728cb-3e1e-480f-ae82-786f61c0179b",
        nicho_id="inexistente"
    )

    await orch._run(run["run_id"])

    loaded = orch.get_status(run["run_id"])
    assert loaded["stage"] == po.ST_ERROR
    assert loaded["error_code"] == "CONTEXT_EMPTY"
    assert "Sin sesión de NotebookLM y sin contexto local del nicho" in loaded["error_detail"]


@pytest.mark.asyncio
async def test_bc_pipeline_context_source_local_skips_notebooklm(temp_orchestrator):
    orch, td = temp_orchestrator
    nicho_folder = td / "nichos" / "frutinovelas"
    nicho_folder.mkdir(parents=True, exist_ok=True)
    (nicho_folder / "contexto.md").write_text("# Contexto forzado localmente", encoding="utf-8")

    mock_mgr = MockManagerBC()
    orch.manager = mock_mgr

    run = orch.create_run(
        idea="Idea de prueba",
        notebook_id="5b7728cb-3e1e-480f-ae82-786f61c0179b",
        nicho_id="frutinovelas"
    )

    mock_raw = {"title": "Guion Test", "scenes": []}
    mock_blueprint = {
        "title": "Guion Test", "engine": "gemini-2.5",
        "scenes": [{"scene_id": "1", "image_prompt": "p", "narration": "n"}]
    }

    with patch.dict(os.environ, {"PIPELINE_CONTEXT_SOURCE": "local"}):
        with patch("pipeline.script_gen.from_idea", AsyncMock(return_value=mock_raw)):
            with patch("pipeline.script_gen.build_result", return_value=mock_blueprint):
                with patch.object(orch, "_stage3", AsyncMock()):
                    await orch._run(run["run_id"])

    # Verificamos que NO se llamó a NotebookLM
    assert len(mock_mgr.execute_calls) == 0

    loaded = orch.get_status(run["run_id"])
    assert loaded["stage"] == po.ST_DONE
    assert loaded["context_source"] == "local"
    assert (orch._run_dir(run["run_id"]) / "context.md").read_text(encoding="utf-8") == "# Contexto forzado localmente"


@pytest.mark.asyncio
async def test_bc_normal_success_notebooklm(temp_orchestrator):
    orch, td = temp_orchestrator

    success_payload = {"status": "success", "answer": "Contexto auténtico de fuentes de NotebookLM"}
    mock_mgr = MockManagerBC(execute_result={"ok": True, "text": json.dumps(success_payload)})
    orch.manager = mock_mgr

    run = orch.create_run(idea="Idea de prueba", notebook_id="nb-12345")

    mock_raw = {"title": "Guion Test", "scenes": []}
    mock_blueprint = {
        "title": "Guion Test", "engine": "gemini-2.5",
        "scenes": [{"scene_id": "1", "image_prompt": "p", "narration": "n"}]
    }

    with patch("pipeline.script_gen.from_idea", AsyncMock(return_value=mock_raw)):
        with patch("pipeline.script_gen.build_result", return_value=mock_blueprint):
            with patch.object(orch, "_stage3", AsyncMock()):
                await orch._run(run["run_id"])

    # Verificamos que se llamó a NotebookLM y el context_source es "notebooklm"
    assert len(mock_mgr.execute_calls) == 1
    loaded = orch.get_status(run["run_id"])
    assert loaded["stage"] == po.ST_DONE
    assert loaded["context_source"] == "notebooklm"
    assert "Contexto auténtico" in (orch._run_dir(run["run_id"]) / "context.md").read_text(encoding="utf-8")


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
