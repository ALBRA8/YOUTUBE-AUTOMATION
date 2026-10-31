"""
Tests INT-071-fix: ventana visible de Chrome en Windows (Chrome fantasma)
- _windows_visible_state: True (≥1 ventana) / False (todos MainWindowHandle=0)
  / None (no-Windows o PowerShell falló → NUNCA se mata nada)
- launch_google_login: zombie con already_up=True → purga taskkill + Singleton*
  borrados + relanzamiento limpio; ventana viva → se conserva; force_window
  fuerza la reparación; estado desconocido → no toca nada
- _spawn_chrome en win32: .bat desacoplado (DETACHED_PROCESS) con
  --start-maximized, quoting de user-data-dir y URLs con espacios, fallback
  os.startfile
- _spawn_chrome argv: --new-window + --start-maximized (sustituye geometría fija)
- Endpoint REST POST /api/mcp/google-sso/launch (force_window default True)

Hermeticidad: cero red, cero Chrome, cero PowerShell — todo con mocks.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from services import mcp_manager as mcpm
from main import app

client = TestClient(app)


# ── 1 · _windows_visible_state: detección de zombie (MainWindowHandle) ──
def test_visible_state_non_windows_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    mgr = mcpm.MCPClientManager()
    assert mgr._windows_visible_state("/tmp/FlowImageChrome") is None


def test_visible_state_all_zombies_returns_false(monkeypatch, tmp_path):
    """Procesos vivos del perfil pero TODOS con hwnd=0 → zombie fantasma."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = SimpleNamespace(returncode=0,
                           stdout=json.dumps([{"pid": 101, "hwnd": 0},
                                              {"pid": 102, "hwnd": 0}]),
                           stderr="")
    with patch.object(mcpm.subprocess, "run", return_value=fake) as run_mock:
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is False
    cmd = run_mock.call_args[0][0][-1]
    assert tmp_path.name in cmd          # filtra CommandLine por el perfil
    assert "MainWindowHandle" in cmd     # y pregunta la ventana real
    assert "chrome.exe" in cmd


def test_visible_state_single_object_json_returns_true(monkeypatch, tmp_path):
    """ConvertTo-Json de UNA fila devuelve objeto, no lista → igual válido."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = SimpleNamespace(returncode=0,
                           stdout=json.dumps({"pid": 101, "hwnd": 4864}),
                           stderr="")
    with patch.object(mcpm.subprocess, "run", return_value=fake):
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is True


def test_visible_state_one_visible_window_returns_true(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = SimpleNamespace(returncode=0,
                           stdout=json.dumps([{"pid": 101, "hwnd": 0},
                                              {"pid": 102, "hwnd": 9999}]),
                           stderr="")
    with patch.object(mcpm.subprocess, "run", return_value=fake):
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is True


def test_visible_state_ps_error_returns_none_never_kills(monkeypatch, tmp_path):
    """PowerShell roto → None → el llamador NUNCA purga (fail-open)."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = SimpleNamespace(returncode=1, stdout="", stderr="boom")
    with patch.object(mcpm.subprocess, "run", return_value=fake):
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is None


def test_visible_state_ps_exception_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    with patch.object(mcpm.subprocess, "run",
                      side_effect=__import__("subprocess").TimeoutExpired(
                          cmd="powershell", timeout=10)):
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is None


# ── 2 · launch_google_login: reparación del fantasma con CDP arriba ─────
def _mgr_ghost(visible, force=False):
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._windows_visible_state = MagicMock(return_value=visible)
    mgr.kill_profile_processes = MagicMock(return_value=[111, 222])
    mgr._find_chrome_bin = lambda: r"C:\Google\Chrome\Application\chrome.exe"
    mgr._spawn_chrome = MagicMock(return_value=999)
    return mgr


def test_launch_repairs_ghost_when_already_up(tmp_path):
    """CDP responde pero no hay ventana (zombie) → purga + relanza limpia."""
    mgr = _mgr_ghost(visible=False)
    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg",
                          side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
            res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["ok"] is True
    assert res["already_up"] is False          # se reutiliza el spawn de abajo
    assert res["relaunched"] is True
    assert res["window_state"] is False
    assert res["killed_pids"] == [111, 222]
    assert res["pid"] == 999
    argv = mgr._spawn_chrome.call_args[0][0]
    assert any(a.startswith("--remote-debugging-port=") for a in argv)
    assert "--new-window" in argv and "--start-maximized" in argv


def test_launch_keeps_alive_window_without_force(tmp_path):
    """Ventana visible real → NO se mata nada, se reutiliza la instancia."""
    mgr = _mgr_ghost(visible=True)
    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg",
                          side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
            res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["ok"] is True
    assert res["already_up"] is True
    assert res["relaunched"] is False
    assert res["window_state"] is True
    assert res["killed_pids"] == []
    mgr.kill_profile_processes.assert_not_called()
    mgr._spawn_chrome.assert_not_called()


def test_launch_force_window_repairs_even_if_visible(tmp_path):
    """Botón «Abrir Ventana de Chrome» → purga y relanza SIEMPRE."""
    mgr = _mgr_ghost(visible=True)
    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg",
                          side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
            res = asyncio.run(mgr.launch_google_login(
                ["https://flow.google.com/"], cdp=True, force_window=True))
    assert res["relaunched"] is True
    assert res["killed_pids"] == [111, 222]
    assert res["pid"] == 999
    mgr.kill_profile_processes.assert_called()


def test_launch_unknown_window_state_does_not_kill(tmp_path):
    """No-Windows / PS roto (None) sin force → comportamiento legacy intacto."""
    mgr = _mgr_ghost(visible=None)
    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg",
                          side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
            res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["already_up"] is True
    assert res["relaunched"] is False
    assert res["window_state"] is None
    mgr.kill_profile_processes.assert_not_called()


def test_launch_purges_orphans_before_spawn_when_cdp_down(tmp_path):
    """Rama clásica (CDP abajo): la purga preventiva se conserva."""
    mgr = _mgr_ghost(visible=None)
    mgr._cdp_up = AsyncMock(return_value=False)
    with tempfile.TemporaryDirectory() as td:
        with patch.object(mcpm, "_cfg",
                          side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
            res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["relaunched"] is False and res["killed_pids"] == []
    assert res["pid"] == 999
    mgr.kill_profile_processes.assert_called()   # purga preventiva del spawn


# ── 3 · _spawn_chrome en Windows: .bat desacoplado ──────────────────────
def test_spawn_chrome_writes_detached_bat(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    popen = MagicMock(return_value=SimpleNamespace(pid=4242))
    with patch.object(mcpm.subprocess, "Popen", popen):
        mgr = mcpm.MCPClientManager()
        pid = mgr._spawn_chrome(["chrome.exe", "--start-maximized",
                                 "--new-window", "https://flow.google.com/"])
    assert pid == 4242
    args, kwargs = popen.call_args
    assert args[0][:2] == ["cmd.exe", "/c"]
    bat = Path(args[0][2])
    assert bat.exists() and bat.suffix == ".bat"
    body = bat.read_text(encoding="utf-8")
    assert body.startswith("@echo off")
    assert 'start "" "chrome.exe"' in body
    assert "--start-maximized" in body
    assert kwargs["creationflags"] == (getattr(mcpm.subprocess, "DETACHED_PROCESS", 0x8) |
                                       getattr(mcpm.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    assert kwargs["stdout"] == mcpm.subprocess.DEVNULL
    bat.unlink()


def test_spawn_chrome_quotes_user_data_dir_and_spaced_url(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    popen = MagicMock(return_value=SimpleNamespace(pid=77))
    with patch.object(mcpm.subprocess, "Popen", popen):
        mgr = mcpm.MCPClientManager()
        mgr._spawn_chrome(["chrome.exe", f"--user-data-dir={tmp_path}",
                           "--start-maximized", "my page url"])
    bat = Path(popen.call_args[0][0][2])
    body = bat.read_text(encoding="utf-8")
    assert f'--user-data-dir="{tmp_path}"' in body
    assert '"my page url"' in body
    bat.unlink()


def test_spawn_chrome_fallback_startfile_on_failure(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with patch.object(mcpm.subprocess, "Popen", side_effect=OSError("no shell")), \
         patch.object(mcpm.os, "startfile", create=True) as startfile:
        mgr = mcpm.MCPClientManager()
        pid = mgr._spawn_chrome(["chrome.exe", "--start-maximized", "https://x.com"])
    assert pid == 0
    assert startfile.call_args[0][0] == "chrome.exe"
    assert "--start-maximized" in startfile.call_args[1]["arguments"]


# ── 4 · Endpoint REST POST /api/mcp/google-sso/launch ────────────────────
def test_api_google_sso_launch_endpoint_forces_window():
    with patch.object(mcpm.manager, "launch_google_login",
                      new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True, "already_up": False, "pid": 42,
                             "cdp_port": 9333, "relaunched": True,
                             "window_state": False, "killed_pids": [111],
                             "pages": ["https://flow.google.com/"],
                             "heal_actions": [],
                             "notebooklm_storage": {"exists": False}}
        resp = client.post("/api/mcp/google-sso/launch",
                           json={"force_window": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["relaunched"] is True
    assert mock.await_args.kwargs["force_window"] is True
    assert mock.await_args.kwargs["cdp"] is True


def test_api_google_sso_launch_default_force_and_no_body():
    """POST sin body → force_window=True (el botón pide ventana explícita)."""
    with patch.object(mcpm.manager, "launch_google_login",
                      new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True}
        resp = client.post("/api/mcp/google-sso/launch")
    assert resp.status_code == 200
    assert mock.await_args.kwargs["force_window"] is True


def test_api_google_sso_launch_allows_soft_mode():
    with patch.object(mcpm.manager, "launch_google_login",
                      new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True}
        client.post("/api/mcp/google-sso/launch", json={"force_window": False})
    assert mock.await_args.kwargs["force_window"] is False


def test_sso_launch_route_registered_and_legacy_intact():
    routes = {getattr(r, "path", None) for r in app.routes}
    assert "/api/mcp/google-sso/launch" in routes
    for legacy in ("/api/mcp/google-sso", "/api/mcp/google-sso/status",
                   "/api/mcp/google-sso/logout", "/api/mcp/login-google",
                   "/api/mcp/launch-auth-browser", "/api/mcp/launch-clean-login",
                   "/api/mcp/connect-all-google"):
        assert legacy in routes, f"endpoint legacy {legacy} desapareció"
