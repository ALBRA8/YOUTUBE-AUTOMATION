#!/usr/bin/env python3
"""
Tests herméticos para BB1 y BB2:
- BB1: fallback a notebook_query cuando la tool configurada no está expuesta pero notebook_query sí.
- BB2: interpretación de la respuesta de notebook_query:
  * Si es JSON: extraer 'answer'. Si status != 'success' o answer está vacío,
    fallar con CONTEXT_EMPTY y mensaje literal:
    'el cuaderno no tiene fuentes o no respondió: sube fuentes en NotebookLM'.
  * Si no es JSON: comportamiento actual (texto plano se usa verbatim).
"""
import json
import logging
import sys
import tempfile
from pathlib import Path
import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402


class MockManager:
    def __init__(self, tools=None, nlm_response=None, nlm_error=None):
        self.tools = tools if tools is not None else [{"name": "notebook_query"}]
        self.nlm_response = nlm_response
        self.nlm_error = nlm_error
        self.executed_calls = []

    async def status(self):
        return {
            "notebooklm": {"state": "connected", "auth": "connected", "detail": "ok"},
            "google-flow": {"state": "connected", "auth": "connected", "detail": "ok", "browser_up": True},
        }

    async def test_pipeline(self, service: str, notebook_id=None):
        return {
            "service": service,
            "ok": True,
            "state": "connected",
            "auth": "ok",
            "detail": "ok",
        }

    async def tools_catalog(self, service: str, auto_connect: bool = True):
        return {
            "service": service,
            "server_info": {"name": "test-mock"},
            "tools": self.tools,
        }

    async def execute(self, service: str, tool: str, arguments=None, timeout=None, notebook_id=None, auto_connect=True):
        self.executed_calls.append((service, tool, arguments))
        if service == "notebooklm":
            if self.nlm_error:
                raise self.nlm_error
            if self.nlm_response is not None:
                return self.nlm_response
            return {"ok": True, "text": "default plain context"}
        if tool == "flow_upload_file":
            return {"ok": True, "text": 'Uploaded and named "ref".'}
        if tool == "flow_generate_image":
            return {"ok": True, "text": "Generated 1 image(s):\n/tmp/fake.png"}
        if tool == "flow_generate_video":
            return {"ok": True, "text": "Generated video:\n/tmp/fake.mp4"}
        return {"ok": True, "text": "ok"}


async def _fake_blueprint(*args, **kwargs):
    return {
        "title": "Historia de prueba", "hook": "Inicio",
        "cta": "Fin", "engine": "fake",
        "scenes": [
            {"title": "E1", "narration": "Voz 1", "image_prompt": "Prompt 1"},
        ],
    }


@pytest.fixture(autouse=True)
def patch_script_gen(monkeypatch):
    monkeypatch.setattr(po.script_gen, "from_idea", _fake_blueprint)


@pytest.mark.asyncio
async def test_bb1_fallback_to_notebook_query_when_configured_tool_missing(monkeypatch, caplog):
    """BB1: si el servidor no expone la tool configurada (ej. chat_ask) pero sí notebook_query,
    usar notebook_query y loguear aviso."""
    monkeypatch.setattr(config, "NOTEBOOKLM_CONTEXT_TOOL", "chat_ask")
    mgr = MockManager(
        tools=[{"name": "notebook_query"}, {"name": "notebook_list"}],
        nlm_response={"ok": True, "text": json.dumps({"status": "success", "answer": "Contexto extraído"})},
    )
    tmp = tempfile.mkdtemp(prefix="bb1_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    with caplog.at_level(logging.WARNING):
        run = orch.create_run("idea", notebook_id="nb-123")
        await orch.start_run(run["run_id"])
        await orch.wait(run["run_id"])

    executed_tools = [call[1] for call in mgr.executed_calls if call[0] == "notebooklm"]
    assert "notebook_query" in executed_tools
    assert "chat_ask" not in executed_tools
    assert any("notebook_query" in rec.message and "chat_ask" in rec.message for rec in caplog.records)
    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_DONE


@pytest.mark.asyncio
async def test_bb1_fallback_on_tool_unknown_exception(monkeypatch, caplog):
    """BB1: si execute falla con TOOL_UNKNOWN para la tool configurada, reintenta con notebook_query."""
    monkeypatch.setattr(config, "NOTEBOOKLM_CONTEXT_TOOL", "custom_legacy_tool")

    class FallbackMgr(MockManager):
        async def execute(self, service, tool, arguments=None, timeout=None, notebook_id=None, auto_connect=True):
            if service == "notebooklm" and tool == "custom_legacy_tool":
                self.executed_calls.append((service, tool, arguments))
                raise mcpm.MCPManagerError("el servidor no expone 'custom_legacy_tool'", "TOOL_UNKNOWN")
            return await super().execute(service, tool, arguments, timeout, notebook_id, auto_connect)

    # tools=[] para simular que tools_catalog no tenía la lista de antemano
    mgr = FallbackMgr(
        tools=[],
        nlm_response={"ok": True, "text": json.dumps({"status": "success", "answer": "Contexto tras fallback"})},
    )
    tmp = tempfile.mkdtemp(prefix="bb1_fb_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    with caplog.at_level(logging.WARNING):
        run = orch.create_run("idea", notebook_id="nb-123")
        await orch.start_run(run["run_id"])
        await orch.wait(run["run_id"])

    executed_tools = [call[1] for call in mgr.executed_calls if call[0] == "notebooklm"]
    assert executed_tools == ["custom_legacy_tool", "notebook_query"]
    assert any("fallback a 'notebook_query'" in rec.message or "notebook_query" in rec.message for rec in caplog.records)
    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_DONE


@pytest.mark.asyncio
async def test_bb2_json_response_with_content():
    """BB2: respuesta JSON con status 'success' y 'answer' poblado -> usa 'answer' y pasa Stage 1."""
    content = "Biblia de investigación: El fruto prohibido y sus secretos."
    mgr = MockManager(
        tools=[{"name": "notebook_query"}],
        nlm_response={
            "ok": True,
            "text": json.dumps({"status": "success", "answer": content, "conversation_id": "conv-1"}),
        },
    )
    tmp = tempfile.mkdtemp(prefix="bb2_ok_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    run = orch.create_run("idea", notebook_id="nb-123")
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"])

    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_DONE
    assert snap["context_chars"] == len(content)
    saved_context = (Path(tmp) / "runs" / run["run_id"] / "context.md").read_text(encoding="utf-8")
    assert saved_context == content


@pytest.mark.asyncio
async def test_bb2_json_response_empty_answer():
    """BB2: respuesta JSON con 'answer' vacío -> falla con CONTEXT_EMPTY y mensaje literal."""
    mgr = MockManager(
        tools=[{"name": "notebook_query"}],
        nlm_response={
            "ok": True,
            "text": json.dumps({"status": "success", "answer": "", "conversation_id": "conv-1"}),
        },
    )
    tmp = tempfile.mkdtemp(prefix="bb2_empty_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    run = orch.create_run("idea", notebook_id="nb-123")
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"])

    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_ERROR
    assert snap["error_code"] == "CONTEXT_EMPTY"
    assert snap["error_detail"] == "el cuaderno no tiene fuentes o no respondió: sube fuentes en NotebookLM"


@pytest.mark.asyncio
async def test_bb2_json_response_error_status():
    """BB2: respuesta JSON con status != 'success' -> falla con CONTEXT_EMPTY y mensaje literal."""
    mgr = MockManager(
        tools=[{"name": "notebook_query"}],
        nlm_response={
            "ok": True,
            "text": json.dumps({"status": "error", "error": "Quota or internal failure"}),
        },
    )
    tmp = tempfile.mkdtemp(prefix="bb2_err_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    run = orch.create_run("idea", notebook_id="nb-123")
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"])

    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_ERROR
    assert snap["error_code"] == "CONTEXT_EMPTY"
    assert snap["error_detail"] == "el cuaderno no tiene fuentes o no respondió: sube fuentes en NotebookLM"


@pytest.mark.asyncio
async def test_bb2_plain_text_response():
    """BB2: respuesta en texto plano (no JSON) -> comportamiento actual (se usa tal cual)."""
    plain_text = "Esta es una biblia en texto plano sin estructura JSON."
    mgr = MockManager(
        tools=[{"name": "notebook_query"}],
        nlm_response={"ok": True, "text": plain_text},
    )
    tmp = tempfile.mkdtemp(prefix="bb2_plain_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    run = orch.create_run("idea", notebook_id="nb-123")
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"])

    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_DONE
    assert snap["context_chars"] == len(plain_text)
    saved_context = (Path(tmp) / "runs" / run["run_id"] / "context.md").read_text(encoding="utf-8")
    assert saved_context == plain_text


@pytest.mark.asyncio
async def test_bb2_plain_text_empty():
    """BB2: texto plano vacío -> comportamiento actual (falla con mensaje tradicional)."""
    mgr = MockManager(
        tools=[{"name": "notebook_query"}],
        nlm_response={"ok": True, "text": ""},
    )
    tmp = tempfile.mkdtemp(prefix="bb2_plain_empty_")
    orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(tmp) / "runs")

    run = orch.create_run("idea", notebook_id="nb-123")
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"])

    snap = orch.get_status(run["run_id"])
    assert snap["stage"] == po.ST_ERROR
    assert snap["error_code"] == "CONTEXT_EMPTY"
    assert "devolvió texto vacío" in snap["error_detail"]


if __name__ == "__main__":
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
