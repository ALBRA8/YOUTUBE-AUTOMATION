"""
Tests para INT-043: Solución Definitiva de Conexión Google en 1 Clic
- Inclusión de --new-window y --start-maximized (foco al frente, INT-071-fix)
  en argv de Chrome
- Spawn interactivo visible en Windows
- Método unificado connect_all_google()
- Endpoint REST POST /api/mcp/connect-all-google
"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from services import mcp_manager as mcpm
from main import app

client = TestClient(app)


def test_launch_google_login_includes_new_window_and_geometry():
    """Verifica que launch_google_login agregue --new-window + --start-maximized
    (INT-071-fix: foco al frente; sustituye a la geometría fija 1280x800)."""
    mgr = mcpm.MCPClientManager()
    captured_argv = []

    def fake_spawn(argv):
        captured_argv.extend(argv)
        return 9999

    mgr._spawn_chrome = fake_spawn
    mgr._find_chrome_bin = lambda: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    mgr._cdp_up = AsyncMock(return_value=False)

    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None: td if "PROFILE" in k else d):
            res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
            assert res["ok"] is True
            assert "--new-window" in captured_argv
            assert "--start-maximized" in captured_argv
            assert not any(a.startswith("--window-size=") for a in captured_argv)
            assert not any(a.startswith("--window-position=") for a in captured_argv)
            assert any(a.startswith("--remote-debugging-port=") for a in captured_argv)


def test_connect_all_google_orchestration():
    """Verifica el flujo integral de connect_all_google."""
    mgr = mcpm.MCPClientManager()
    mgr.kill_profile_processes = MagicMock(return_value=[111, 222])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": ["repaired"]})
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr.nb_storage_state = MagicMock(return_value={"exists": True, "size_bytes": 15000})
    mgr.connect = AsyncMock(side_effect=lambda svc, **kw: {
        "service": svc,
        "state": mcpm.ST_CONNECTED,
        "auth": "ok"
    })

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None: "C:\\FakeProfile" if "PROFILE" in k else (9333 if "PORT" in k else d)):
        res = asyncio.run(mgr.connect_all_google())
        assert res["ok"] is True
        assert res["chrome_up"] is True
        assert res["flow"]["state"] == mcpm.ST_CONNECTED
        assert res["notebooklm"]["state"] == mcpm.ST_CONNECTED
        assert any("zombis" in a for a in res["heal_actions"])


def test_api_connect_all_google():
    """Verifica el endpoint REST /api/mcp/connect-all-google."""
    with patch.object(mcpm.manager, "connect_all_google", new_callable=AsyncMock) as mock_all:
        mock_all.return_value = {
            "ok": True,
            "chrome_up": True,
            "cdp_port": 9333,
            "flow": {"state": "connected", "auth": "ok"},
            "notebooklm": {"state": "connected", "auth": "ok"},
            "heal_actions": []
        }
        resp = client.post("/api/mcp/connect-all-google")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["flow"]["state"] == "connected"
        assert data["notebooklm"]["state"] == "connected"
