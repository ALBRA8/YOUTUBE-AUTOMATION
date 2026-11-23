# -*- coding: utf-8 -*-
"""W1 · connect_all_google robusto con relanzamiento forzado y sondeo configurable.

Tests herméticos con dobles:
(a) Chrome nunca sube → chrome_up False y mensaje explícito (nunca ok=True);
(b) Sube tras sondeo (simulado) → continúa y conecta servicios;
(c) Zombi con puerto CDP abierto pero sin ventana visible → relanza con force_window=True.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.mcp_manager import MCPClientManager, ST_CONNECTED, ST_ERROR


@pytest.fixture
def manager():
    mgr = MCPClientManager()
    # Desactivar I/O de disco / subprocesos reales
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"actions": []})
    mgr.nb_storage_state = MagicMock(return_value={"exists": True, "size_bytes": 500})
    return mgr


@pytest.mark.asyncio
async def test_w1_chrome_nunca_sube_devuelve_chrome_up_false_y_mensaje(manager):
    """(a) Chrome nunca sube → chrome_up False, ok False y mensaje explícito."""
    manager._cdp_up = AsyncMock(return_value=False)
    manager._windows_visible_state = MagicMock(return_value=None)
    manager.launch_google_login = AsyncMock(return_value={"ok": True, "pid": 1234})
    manager.connect = AsyncMock(side_effect=lambda s: {"service": s, "state": ST_CONNECTED})

    # Timeout corto para test hermético veloz
    res = await manager.connect_all_google(cdp_timeout_s=0.2)

    assert res["chrome_up"] is False
    assert res["ok"] is False
    assert res["chrome_error"] is not None
    assert "Chrome no respondió en el puerto CDP" in res["chrome_error"]
    assert res["flow"]["state"] == ST_ERROR
    assert res["flow_error"] is not None


@pytest.mark.asyncio
async def test_w1_chrome_sube_tras_sondeo_continua_y_conecta(manager):
    """(b) Chrome sube tras sondeo → continúa y conecta servicios exitosamente."""
    # Simular que al principio no está arriba, y al segundo sondeo sube
    calls = 0

    async def mock_cdp_up(port):
        nonlocal calls
        calls += 1
        return calls >= 3

    manager._cdp_up = mock_cdp_up
    manager._windows_visible_state = MagicMock(return_value=True)
    manager.launch_google_login = AsyncMock(return_value={"ok": True, "pid": 5678})
    manager.connect = AsyncMock(side_effect=lambda s: {"service": s, "state": ST_CONNECTED})

    res = await manager.connect_all_google(cdp_timeout_s=2.0)

    assert res["chrome_up"] is True
    assert res["ok"] is True
    assert res["chrome_error"] is None
    assert res["flow"]["state"] == ST_CONNECTED
    assert res["notebooklm"]["state"] == ST_CONNECTED


@pytest.mark.asyncio
async def test_w1_zombie_puerto_abierto_sin_ventana_usa_ruta_forzada(manager):
    """(c) Zombi con puerto abierto pero sin ventana gráfica → usa la ruta forzada (force_window=True)."""
    # CDP dice True
    manager._cdp_up = AsyncMock(return_value=True)
    # Pero _windows_visible_state dice False (ventana no visible / zombie)
    manager._windows_visible_state = MagicMock(return_value=False)
    manager.launch_google_login = AsyncMock(return_value={"ok": True, "pid": 9999})
    manager.connect = AsyncMock(side_effect=lambda s: {"service": s, "state": ST_CONNECTED})

    res = await manager.connect_all_google(cdp_timeout_s=1.0)

    # Debe haber llamado a launch_google_login con force_window=True
    manager.launch_google_login.assert_awaited_once()
    _, kwargs = manager.launch_google_login.call_args
    assert kwargs.get("force_window") is True
    assert kwargs.get("cdp") is True
    assert res["chrome_up"] is True
    assert res["ok"] is True
