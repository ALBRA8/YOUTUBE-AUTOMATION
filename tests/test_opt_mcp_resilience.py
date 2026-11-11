# -*- coding: utf-8 -*-
"""Test hermético de resiliencia y reconexión automática en mcp_manager.py."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from services import mcp_manager as mcpm


def test_eof_in_read_loop_wakes_pending_futures_immediately():
    """Si el proceso MCP cierra stdout (EOF), los futures pendientes deben fallar inmediatamente con PROCESS_DEAD."""
    conn = mcpm._Conn("google-flow")
    mock_proc = MagicMock()
    mock_stdout = AsyncMock()
    # Simular que stdout devuelve EOF inmediatamente
    mock_stdout.readline.return_value = b""
    mock_proc.stdout = mock_stdout
    conn.proc = mock_proc

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        fut = loop.create_future()
        conn._pending[1] = fut

        # Ejecutar el _read_loop
        loop.run_until_complete(conn._read_loop())

        # El future DEBE estar resuelto con excepción PROCESS_DEAD de inmediato
        assert fut.done()
        exc = fut.exception()
        assert isinstance(exc, mcpm.MCPManagerError)
        assert exc.code == "PROCESS_DEAD"
    finally:
        loop.close()


def test_execute_auto_reconnects_on_transient_process_dead():
    """execute() debe reintentar reconectar si el primer intento sufre un PROCESS_DEAD transitorio."""
    mgr = mcpm.MCPClientManager()

    # Conn 1: falla con PROCESS_DEAD
    conn1 = MagicMock()
    conn1.state = mcpm.ST_CONNECTED
    conn1.proc.returncode = None
    conn1.tools = [{"name": "flow_generate_image"}]
    conn1.call = AsyncMock(side_effect=mcpm.MCPManagerError("pipe roto", "PROCESS_DEAD"))
    conn1.close = AsyncMock()

    # Conn 2: tiene éxito tras la reconexión
    conn2 = MagicMock()
    conn2.state = mcpm.ST_CONNECTED
    conn2.proc.returncode = None
    conn2.tools = [{"name": "flow_generate_image"}]
    conn2.call = AsyncMock(return_value="imagen_ok")
    conn2.close = AsyncMock()

    async def fake_connect(service):
        mgr._conns[service] = conn2

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        mgr._conns["google-flow"] = conn1
        with patch.object(mgr, "connect", side_effect=fake_connect):
            res = loop.run_until_complete(
                mgr.execute("google-flow", "flow_generate_image", {"prompt": "test"}, auto_connect=True)
            )
            assert res["ok"] is True
            assert res["text"] == "imagen_ok"
            # conn1 debió cerrarse
            conn1.close.assert_awaited_once()
            # conn2 debió llamarse
            conn2.call.assert_awaited_once()
    finally:
        loop.close()
