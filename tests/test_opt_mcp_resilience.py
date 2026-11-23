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


def test_execute_auto_reconnects_on_transient_process_dead_only_for_read_tools():
    """AA1: execute() debe reintentar reconectar SOLO si es herramienta de lectura (flow_list_assets)."""
    mgr = mcpm.MCPClientManager()

    # Conn 1: falla con PROCESS_DEAD
    conn1 = MagicMock()
    conn1.state = mcpm.ST_CONNECTED
    conn1.proc.returncode = None
    conn1.tools = [{"name": "flow_list_assets"}]
    conn1.call = AsyncMock(side_effect=mcpm.MCPManagerError("pipe roto", "PROCESS_DEAD"))
    conn1.close = AsyncMock()

    # Conn 2: tiene éxito tras la reconexión
    conn2 = MagicMock()
    conn2.state = mcpm.ST_CONNECTED
    conn2.proc.returncode = None
    conn2.tools = [{"name": "flow_list_assets"}]
    conn2.call = AsyncMock(return_value="assets_ok")
    conn2.close = AsyncMock()

    async def fake_connect(service):
        mgr._conns[service] = conn2

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        mgr._conns["google-flow"] = conn1
        with patch.object(mgr, "connect", side_effect=fake_connect):
            res = loop.run_until_complete(
                mgr.execute("google-flow", "flow_list_assets", {}, auto_connect=True)
            )
            assert res["ok"] is True
            assert res["text"] == "assets_ok"
            # conn1 debió cerrarse
            conn1.close.assert_awaited_once()
            # conn2 debió llamarse
            conn2.call.assert_awaited_once()
    finally:
        loop.close()


def test_execute_never_retries_mutating_flow_tools_on_process_dead():
    """AA1: NUNCA reintentar flow_generate_image, flow_generate_video, flow_new_project ni flow_upload_file.
    Debe lanzar PROCESS_DEAD con 'la herramienta pudo ejecutarse; verifica en Flow antes de reintentar'."""
    mutating_tools = [
        "flow_generate_image",
        "flow_generate_video",
        "flow_new_project",
        "flow_upload_file",
    ]

    for tool_name in mutating_tools:
        mgr = mcpm.MCPClientManager()
        conn1 = MagicMock()
        conn1.state = mcpm.ST_CONNECTED
        conn1.proc.returncode = None
        conn1.tools = [{"name": tool_name}]
        # Doble que muere a mitad de llamada lanzando PROCESS_DEAD
        conn1.call = AsyncMock(side_effect=mcpm.MCPManagerError("subproceso cerrado a mitad", "PROCESS_DEAD"))
        conn1.close = AsyncMock()

        connect_called = False

        async def fake_connect(service):
            nonlocal connect_called
            connect_called = True

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            mgr._conns["google-flow"] = conn1
            with patch.object(mgr, "connect", side_effect=fake_connect):
                try:
                    loop.run_until_complete(
                        mgr.execute("google-flow", tool_name, {"prompt": "foo"}, auto_connect=True)
                    )
                    assert False, f"Se esperaba MCPManagerError para {tool_name}"
                except mcpm.MCPManagerError as exc:
                    assert exc.code == "PROCESS_DEAD"
                    assert str(exc) == "la herramienta pudo ejecutarse; verifica en Flow antes de reintentar"
                
                # Verificación estricta: NUNCA debió intentar reconectar / reintentar
                assert not connect_called, f"connect() no debió llamarse para reintentar {tool_name}"
                conn1.close.assert_awaited_once()
        finally:
            loop.close()

