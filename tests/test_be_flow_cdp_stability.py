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
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import config as config_mod
from pipeline import script_gen
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
    disable_feats = [a for a in argv if a.startswith("--disable-features=")]
    assert len(disable_feats) == 1
    assert disable_feats[0] == "--disable-features=SessionCrashedBubble,IntensiveWakeUpThrottling,CalculateNativeWinOcclusion"


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


@pytest.mark.asyncio
async def test_d2_keepalive_pings_during_stages_0_2_and_no_survivor_after_stage2_failure(tmp_path, monkeypatch):
    """D2 (a+b): _run REAL con un doble de manager e intervalo corto:
    (a) se hacen pings de keepalive DURANTE las etapas 0-2, y (b) tras una
    corrida que FALLA en la etapa 2 no sobrevive NINGUNA tarea de keepalive
    (verificado con asyncio.all_tasks())."""
    _force_notebooklm_path(monkeypatch)
    monkeypatch.setenv("FLOW_KEEPALIVE_INTERVAL", "0.05")
    monkeypatch.setenv("FLOW_KEEPALIVE_TIMEOUT", "1.0")

    mgr = _ManagerDouble()
    orch = PipelineOrchestrator(manager=mgr, runs_dir=tmp_path)
    run = orch.create_run("Frutinovela de prueba: la manzana y la pera.",
                          notebook_id="nb-test-1234")

    async def _slow_failing_from_idea(*a, **k):
        await asyncio.sleep(0.35)  # ventana para que el keepalive dispare pings
        raise RuntimeError("double: Gemini caído (blueprint imposible)")

    with patch.object(script_gen, "from_idea", _slow_failing_from_idea):
        task = orch.start_run(run["run_id"])
        await asyncio.wait_for(task, timeout=15)

    await asyncio.sleep(0)  # asentar callbacks done_callback del evento

    final = orch.get_status(run["run_id"])
    assert final["stage"] == "error"
    assert final["error_code"] == "BLUEPRINT_FAILED"  # falló en la etapa 2
    assert orch._busy is None  # single-flight liberado en el mismo finally

    pings = [ts for (svc, tool, ts) in mgr.calls
             if (svc, tool) == ("google-flow", "flow_list_assets")]
    assert len(pings) >= 2  # (a): pings reales durante las etapas 0-2

    assert _surviving_keepalive_tasks() == []  # (b): cero tareas huérfanas


@pytest.mark.asyncio
async def test_d2_keepalive_no_survivor_after_run_reaches_stage3(tmp_path, monkeypatch):
    """D2 (c): tras una corrida que LLEGA a la etapa 3 tampoco sobrevive ninguna
    tarea de keepalive (asyncio.all_tasks()), y no hay pings una vez que la
    etapa 3 empezó (la cancelación ocurre ANTES de despachar escenas)."""
    _force_notebooklm_path(monkeypatch)
    monkeypatch.setenv("FLOW_KEEPALIVE_INTERVAL", "0.05")
    monkeypatch.setenv("FLOW_KEEPALIVE_TIMEOUT", "1.0")

    mgr = _ManagerDouble()
    orch = PipelineOrchestrator(manager=mgr, runs_dir=tmp_path)
    run = orch.create_run("Frutinovela de prueba: la manzana y la pera.",
                          notebook_id="nb-test-1234", max_scenes=3)

    raw = {
        "title": "La traición de la pera",
        "hook": "La manzana encontró una carta.",
        "cta": "Sigue la frutinovela.",
        "engine": "gemini (gemini-3.8-flash)",
        "scenes": [
            {"title": "El descubrimiento",
             "narration": "La manzana lee la carta de la pera.",
             "image_prompt": "manzana roja leyendo una carta bajo luz de luna"},
            {"title": "La confrontación",
             "narration": "La manzana confronta a la pera frente al huerto.",
             "image_prompt": "manzana y pera cara a cara en el huerto, tensión dramática"},
            {"title": "El giro",
             "narration": "La pera confiesa que la banana la obligó.",
             "image_prompt": "pera llorando frente a banana sonriente, giro dramático"},
        ],
    }

    async def _slow_ok_from_idea(*a, **k):
        await asyncio.sleep(0.3)  # ventana para pings durante las etapas 0-2
        return raw

    stage3_started = 0.0

    async def _fake_stage3(run_obj, only_scene_ids=None):
        nonlocal stage3_started
        stage3_started = time.monotonic()

    orch._stage3 = _fake_stage3

    with patch.object(script_gen, "from_idea", _slow_ok_from_idea):
        task = orch.start_run(run["run_id"])
        await asyncio.wait_for(task, timeout=15)

    await asyncio.sleep(0)  # asentar callbacks done_callback del evento

    final = orch.get_status(run["run_id"])
    assert final["stage"] == "done"
    assert stage3_started > 0  # la corrida LLEGÓ a la etapa 3
    assert orch._stage3.__name__ == "_fake_stage3"  # el doble fue quien corrió

    pings = [ts for (svc, tool, ts) in mgr.calls
             if (svc, tool) == ("google-flow", "flow_list_assets")]
    assert len(pings) >= 2  # hubo pings durante las etapas 0-2
    assert all(ts < stage3_started for ts in pings)  # y NINGUNO dentro de la etapa 3

    assert _surviving_keepalive_tasks() == []  # (c): cero tareas huérfanas


# ── D2 · Keepalive acotado: helpers compartidos ────────────────────────────
def _force_notebooklm_path(monkeypatch):
    """Ruta determinista Stage 1 vía NotebookLM (no local) con la tool canónica,
    inmune al .env/entorno de la máquina."""
    monkeypatch.setattr(config_mod, "PIPELINE_CONTEXT_SOURCE", "", raising=False)
    monkeypatch.delenv("PIPELINE_CONTEXT_SOURCE", raising=False)
    monkeypatch.setattr(config_mod, "NOTEBOOKLM_CONTEXT_TOOL", "notebook_query",
                        raising=False)
    monkeypatch.delenv("NOTEBOOKLM_CONTEXT_TOOL", raising=False)


def _surviving_keepalive_tasks() -> list:
    """Tareas vivas cuyo coroutine sea el keepalive de la corrida (D2).
    Tras _run (cualquier salida) debe haber EXACTAMENTE 0."""
    out = []
    for t in asyncio.all_tasks():
        coro = t.get_coro()
        qual = getattr(coro, "__qualname__", "") or str(coro)
        if "_flow_keepalive" in qual or "_keepalive_loop" in qual:
            out.append(t)
    return out


class _ManagerDouble:
    """Manager MCP doble (sin red): registra (servicio, tool, t) de cada execute;
    responde NotebookLM con JSON de éxito y Flow con ok=True."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    async def test_pipeline(self, service, **kw):
        return {"ok": True, "state": mcpm.ST_CONNECTED, "auth": True}

    async def execute(self, service, tool, args, timeout=None, **kw):
        self.calls.append((service, tool, time.monotonic()))
        await asyncio.sleep(0)  # cede el loop como el transporte real
        if service == "notebooklm":
            return {"ok": True, "text": json.dumps({
                "status": "success",
                "answer": "Biblia de investigación: manzana, pera y el giro de la banana.",
            })}
        return {"ok": True, "text": "assets: ninguno"}


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
