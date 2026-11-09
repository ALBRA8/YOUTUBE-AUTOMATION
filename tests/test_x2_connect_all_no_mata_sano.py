# -*- coding: utf-8 -*-
"""X2 · connect_all_google NO mata un Chrome sano.

Reorden verificado con dobles (hermético):
  1. Primero comprueba _cdp_up y _windows_visible_state.
  2. SOLO si Chrome está caído o es zombi (puerto abierto sin ventana visible)
     purga con kill_profile_processes, sanea el perfil y relanza.
  3. Un Chrome sano (arriba + ventana visible) NUNCA se mata ni se relanza.

La ruta verificada POST /api/mcp/google-sso/launch (force_window) no cambia
(guardia estática aparte: test_w3_rutas_verificadas.py).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.mcp_manager import MCPClientManager, ST_CONNECTED, ST_ERROR


@pytest.fixture
def manager():
    mgr = MCPClientManager()
    # Dobles: ninguna I/O de disco ni subprocesos reales
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"actions": []})
    mgr.nb_storage_state = MagicMock(return_value={"exists": True, "size_bytes": 500})
    mgr.connect = AsyncMock(side_effect=lambda s: {"service": s, "state": ST_CONNECTED})
    return mgr


@pytest.mark.asyncio
async def test_x2_sano_y_visible_no_se_mata_ni_se_relanza(manager):
    """Chrome arriba con ventana visible → kill_profile_processes NO se llama,
    no hay heal y NO se relanza (launch_google_login intacto)."""
    manager._cdp_up = AsyncMock(return_value=True)
    manager._windows_visible_state = MagicMock(return_value=True)
    manager.launch_google_login = AsyncMock(return_value={"ok": True})

    res = await manager.connect_all_google(cdp_timeout_s=1.0)

    manager.kill_profile_processes.assert_not_called()
    manager.heal_chrome_profile.assert_not_called()
    manager.launch_google_login.assert_not_called()
    assert res["chrome_up"] is True
    assert res["ok"] is True
    assert res["chrome_error"] is None
    assert res["heal_actions"] == []


@pytest.mark.asyncio
async def test_x2_caido_se_purga_y_se_relanza_con_force_window(manager):
    """Chrome caído → purga + saneo y relanzamiento con force_window=True."""
    # Primer chequeo: caído; el sondeo posterior lo ve arriba
    manager._cdp_up = AsyncMock(side_effect=[False, True])
    manager._windows_visible_state = MagicMock(return_value=True)  # no consultado si no está arriba
    manager.launch_google_login = AsyncMock(return_value={"ok": True, "pid": 111})
    manager.heal_chrome_profile = MagicMock(return_value={"actions": ["perfil saneado"]})

    res = await manager.connect_all_google(cdp_timeout_s=2.0)

    manager.kill_profile_processes.assert_called_once()
    manager.heal_chrome_profile.assert_called_once()
    manager.launch_google_login.assert_awaited_once()
    _, kwargs = manager.launch_google_login.call_args
    assert kwargs.get("force_window") is True
    assert kwargs.get("cdp") is True
    assert res["chrome_up"] is True
    assert res["ok"] is True
    assert "perfil saneado" in res["heal_actions"]


@pytest.mark.asyncio
async def test_x2_zombi_se_purga_y_se_relanza_con_force_window(manager):
    """Zombi: puerto CDP abierto pero sin ventana visible → purga + relanza forzado."""
    manager._cdp_up = AsyncMock(return_value=True)
    manager._windows_visible_state = MagicMock(return_value=False)
    manager.launch_google_login = AsyncMock(return_value={"ok": True, "pid": 222})

    res = await manager.connect_all_google(cdp_timeout_s=1.0)

    manager.kill_profile_processes.assert_called_once()
    manager.launch_google_login.assert_awaited_once()
    _, kwargs = manager.launch_google_login.call_args
    assert kwargs.get("force_window") is True
    assert res["chrome_up"] is True
    assert res["ok"] is True


@pytest.mark.asyncio
async def test_x2_caido_que_nunca_sube_mantiene_diagnostico_honesto(manager):
    """Caído y que nunca sube → chrome_up False, motivo explícito, ok False (W1 intacto)."""
    manager._cdp_up = AsyncMock(return_value=False)
    manager.launch_google_login = AsyncMock(return_value={"ok": True})

    res = await manager.connect_all_google(cdp_timeout_s=0.2)

    manager.kill_profile_processes.assert_called_once()
    assert res["chrome_up"] is False
    assert res["ok"] is False
    assert "Chrome no respondió en el puerto CDP" in res["chrome_error"]
    assert res["flow"]["state"] == ST_ERROR
