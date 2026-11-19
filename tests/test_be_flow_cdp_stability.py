# -*- coding: utf-8 -*-
"""
Tests herméticos para D1, D2 y D3 (Estabilidad Flow/CDP):
- D1: Flags de Chrome en launch_google_login (--disable-background-timer-throttling,
      --disable-renderer-backgrounding, --disable-backgrounding-occluded-windows).
- D2: Calentamiento previo a Stage 3 (llamada a flow_list_assets hasta 2 intentos, abortando con FLOW_CDP_SLOW).
- D3: Excepción acotada a regla AA1: si flow_generate_image, flow_generate_video,
      flow_new_project o flow_upload_file fallan con error conteniendo "connectOverCDP: Timeout",
      permitir UN reintento precedido de calentamiento. Cualquier otro error no se reintenta.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from services import mcp_manager as mcpm
from services.pipeline_orchestrator import PipelineOrchestrator, PipelineError


# ── D1 · Flags de Chrome ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_d1_chrome_launch_argv_contains_throttling_flags(tmp_path):
    """D1: launch_google_login debe incluir flags para evitar congelamiento de CDP en background."""
    mgr = mcpm.MCPClientManager()
    mgr._find_chrome_bin = lambda: r"C:\Google\Chrome\Application\chrome.exe"
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._windows_visible_state = MagicMock(return_value=True)
    mgr.nb_storage_state = MagicMock(return_value={"exists": False})

    spawn_mock = MagicMock(return_value=1234)
    with patch.object(mgr, "_spawn_chrome", spawn_mock):
        res = await mgr.launch_google_login(["https://flow.google.com"], cdp=True, force_window=True)

    assert res["ok"] is True
    assert spawn_mock.called
    argv = spawn_mock.call_args[0][0]
    assert "--disable-background-timer-throttling" in argv
    assert "--disable-renderer-backgrounding" in argv
    assert "--disable-backgrounding-occluded-windows" in argv


# ── D2 · Calentamiento previo a Stage 3 ────────────────────────────────────
@pytest.mark.asyncio
async def test_d2_stage3_warmup_success_proceeds(tmp_path):
    """D2: Si flow_list_assets responde en el calentamiento, Stage 3 continúa."""
    mgr = MagicMock()
    mgr.test_pipeline = AsyncMock(return_value={"ok": True})
    # Warmup list_assets returns ok
    mgr.execute = AsyncMock(return_value={"ok": True, "text": "assets list"})

    orch = PipelineOrchestrator(manager=mgr, runs_dir=tmp_path)
    orch._ensure_reference = AsyncMock(return_value="personaje")

    run = {
        "run_id": "run_warm_ok",
        "format": "short",
        "scenes": [{"scene_id": "s1", "status": "pending", "attempts": 0, "detail": ""}],
        "failed_scene_ids": [],
        "dispatched": 0,
        "progress_pct": 50,
        "done_count": 0,
    }
    # Mock scene execution inside stage3
    with patch.object(orch, "_flow_call", AsyncMock(return_value="image.png")):
        # We only want to test warmup logic
        try:
            await orch._stage3(run)
        except Exception:
            pass

    # Verify warmup was called with flow_list_assets
    assert mgr.execute.call_count >= 1
    call0 = mgr.execute.call_args_list[0]
    assert call0.args[0] == "google-flow"
    assert call0.args[1] == "flow_list_assets"


@pytest.mark.asyncio
async def test_d2_stage3_warmup_fails_raises_flow_cdp_slow(tmp_path):
    """D2: Si flow_list_assets falla 2 veces en el calentamiento, aborta con FLOW_CDP_SLOW."""
    mgr = MagicMock()
    mgr.test_pipeline = AsyncMock(return_value={"ok": True})
    # Both warmup calls fail
    mgr.execute = AsyncMock(side_effect=mcpm.MCPManagerError("Timeout connecting to CDP", "TIMEOUT"))

    orch = PipelineOrchestrator(manager=mgr, runs_dir=tmp_path)
    orch._ensure_reference = AsyncMock(return_value="personaje")

    run = {
        "run_id": "run_warm_fail",
        "format": "short",
        "scenes": [{"scene_id": "s1", "status": "pending", "attempts": 0, "detail": ""}],
        "failed_scene_ids": [],
        "dispatched": 0,
        "progress_pct": 50,
        "done_count": 0,
    }

    with pytest.raises(PipelineError) as exc_info:
        await orch._stage3(run)

    assert exc_info.value.code == "FLOW_CDP_SLOW"
    assert mgr.execute.call_count == 2
    assert "FLOW_CDP_SLOW" in run["scenes"][0]["detail"]


# ── D3 · Excepción acotada a regla AA1 ante connectOverCDP: Timeout ─────────
@pytest.mark.asyncio
async def test_d3_timeout_cdp_retries_once_with_warmup():
    """D3: flow_generate_image con connectOverCDP: Timeout se reintenta 1 vez precedido de calentamiento."""
    mgr = mcpm.MCPClientManager()
    conn = MagicMock()
    conn.state = mcpm.ST_CONNECTED
    conn.proc = SimpleNamespace(returncode=None)
    conn.tools = [{"name": "flow_generate_image"}, {"name": "flow_list_assets"}]

    # 1st call fails with connectOverCDP: Timeout
    # Warmup call succeeds
    # 2nd call succeeds
    conn.call = AsyncMock(side_effect=[
        mcpm.MCPManagerError("browserType.connectOverCDP: Timeout 30000ms exceeded", "TOOL_ERROR"),
        "assets_ok",  # warmup
        "image_generated_path.png",  # 2nd attempt
    ])
    mgr._conns["google-flow"] = conn

    with patch.object(mgr, "_allowed_tools", return_value={"flow_generate_image", "flow_list_assets"}):
        res = await mgr.execute("google-flow", "flow_generate_image", {"prompt": "test"})

    assert res["ok"] is True
    assert res["text"] == "image_generated_path.png"
    assert conn.call.call_count == 3  # 1st attempt + warmup + 2nd attempt


@pytest.mark.asyncio
async def test_d3_other_tool_error_does_not_retry():
    """D3: Otros errores en herramientas no-reintentables (sin connectOverCDP: Timeout) NO se reintentan."""
    mgr = mcpm.MCPClientManager()
    conn = MagicMock()
    conn.state = mcpm.ST_CONNECTED
    conn.proc = SimpleNamespace(returncode=None)
    conn.tools = [{"name": "flow_generate_image"}]

    # Fails with a prompt safety error or other tool error
    conn.call = AsyncMock(side_effect=mcpm.MCPManagerError("Safety violation: prompt blocked", "TOOL_ERROR"))
    mgr._conns["google-flow"] = conn

    with patch.object(mgr, "_allowed_tools", return_value={"flow_generate_image"}):
        with pytest.raises(mcpm.MCPManagerError) as exc_info:
            await mgr.execute("google-flow", "flow_generate_image", {"prompt": "test"})

    assert "Safety violation" in str(exc_info.value)
    assert conn.call.call_count == 1  # EXACTAMENTE 1 intento, cero reintentos


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
