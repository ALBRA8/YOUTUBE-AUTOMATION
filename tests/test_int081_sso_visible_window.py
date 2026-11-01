"""
Tests INT-081: «Continuar con Google» GARANTIZA ventana visible (SSO Hub)

Síntoma (PC del usuario, Windows): POST /api/mcp/google-sso devolvía el toast
de éxito pero NUNCA se abría ventana de Chrome en el escritorio.

Cadena de causas corregida y congelada aquí:
 1. google_sso_start() llama a launch_google_login con force_window=True
    (antes no lo forzaba → si CDP 9333 respondía, solo mandaba PUT /json/new
    a un fantasma sin MainWindowHandle y no se veía NADA).
 2. launch_google_login(force_window=True) purga zombis del perfil
    (kill_profile_processes), limpia Singleton* (heal_chrome_profile) y fuerza
    already_up=False → spawn de Chrome interactivo SIEMPRE, sin sondear.
 3. window_state None en Windows (PowerShell colgado, timeout) también purga:
    jamás se confía en un proceso sin ventana confirmada.
 4. _windows_visible_state: sondeo ligero ≤3 s (antes 10 s congelando el
    event-loop) con WQL SELECT + PowerShell -NonInteractive.
 5. Respuesta del SSO con evidencia: relaunched / window_state / killed_pids.

Hermeticidad total: cero red, cero Chrome, cero PowerShell, cero Windows.
"""
import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "backend"))
from services import mcp_manager as mcpm
from main import app

client = TestClient(app)


# ── 1 · google_sso_start exige ventana (requerimiento principal) ─────────
def test_google_sso_start_forces_window():
    """El botón «Continuar con Google» DEBE lanzar el Chrome con
    force_window=True — la ventana gráfica queda garantizada."""
    mgr = mcpm.MCPClientManager()
    captured = {}

    async def fake_launch(urls=None, cdp=True, force_window=False):
        captured["urls"] = urls
        captured["cdp"] = cdp
        captured["force_window"] = force_window
        return {"ok": True, "already_up": False, "cdp_port": 9333,
                "heal_actions": [], "notebooklm_storage": {"exists": False},
                "relaunched": True, "window_state": None, "killed_pids": []}

    mgr.launch_google_login = AsyncMock(side_effect=fake_launch)
    mgr._sso_watchdog = AsyncMock()

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None:
            "https://accounts.google.com/AccountChooser?continue=https://labs.google/fx/tools/flow"
            if k == "GOOGLE_SSO_URL" else d):
        res = asyncio.run(mgr.google_sso_start())

    assert captured["force_window"] is True, \
        "google_sso_start debe forzar ventana interactiva SIEMPRE"
    assert captured["cdp"] is True
    assert res["ok"] is True and res["phase"] == "watching"
    # evidencia de purga propagada en la respuesta
    assert res["relaunched"] is True
    assert res["killed_pids"] == []
    assert "window_state" in res


def test_sso_start_with_orphan_on_9333_purges_heals_and_spawns():
    """Escenario real del bug: puerto 9333 ocupado por un huérfano SIN ventana.
    → se purgan sus procesos, se limpian los Singleton* y se hace spawn de un
    Chrome NUEVO interactivo (already_up forzado a False, sin PUT /json/new)."""
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)          # huérfano respondiendo CDP
    mgr._windows_visible_state = MagicMock(return_value=False)  # sin MainWindowHandle
    mgr.kill_profile_processes = MagicMock(return_value=[3131, 3132])
    mgr.heal_chrome_profile = MagicMock(
        return_value={"ok": True, "actions": ["SingletonLock eliminado"]})
    mgr._find_chrome_bin = lambda: r"C:\Google\Chrome\Application\chrome.exe"
    mgr._spawn_chrome = MagicMock(return_value=555)
    mgr._sso_watchdog = AsyncMock()

    with __import__("tempfile").TemporaryDirectory() as td, \
         patch.object(mcpm, "_cfg",
                      side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
        res = asyncio.run(mgr.google_sso_start())

    # purga del huérfano + locks limpiados + spawn interactivo
    mgr.kill_profile_processes.assert_called()
    assert res["relaunched"] is True
    assert res["already_up"] is False          # obligado a spawn nuevo
    assert res["killed_pids"] == [3131, 3132]
    assert res["window_state"] is None         # force → sin sondeo previo
    assert res["heal_actions"] == ["SingletonLock eliminado"]
    mgr._spawn_chrome.assert_called_once()
    argv = mgr._spawn_chrome.call_args[0][0]
    assert any(a.startswith("--remote-debugging-port=") for a in argv)
    assert "--new-window" in argv and "--start-maximized" in argv
    assert res["pid"] == 555
    assert res["phase"] == "watching"          # el watchdog SSO sigue vivo


def test_sso_start_orphan_unknown_window_state_still_purges():
    """PowerShell colgado (window_state imposible de saber) NO es excusa:
    con force_window la purga y el spawn ocurren igual — nunca un fantasma."""
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._windows_visible_state = MagicMock(return_value=None)  # PS colgado (post-spawn)
    mgr.kill_profile_processes = MagicMock(return_value=[42])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
    mgr._find_chrome_bin = lambda: "chrome.exe"
    mgr._spawn_chrome = MagicMock(return_value=9)
    mgr._sso_watchdog = AsyncMock()

    with __import__("tempfile").TemporaryDirectory() as td, \
         patch.object(mcpm, "_cfg",
                      side_effect=lambda k, d=None: td if "PROFILE" in k or k == "NOTEBOOKLM_HOME" else d):
        res = asyncio.run(mgr.google_sso_start())

    assert res["relaunched"] is True and res["pid"] == 9
    assert res["killed_pids"] == [42]
    assert res["window_state"] is None          # PRE-spawn: jamás sondeado con force
    mgr._spawn_chrome.assert_called_once()


# ── 2 · Endpoint REST intacto + respuesta con evidencia ──────────────────
def test_api_google_sso_endpoint_still_works():
    """POST /api/mcp/google-sso sigue vivo y delega en google_sso_start."""
    with patch.object(mcpm.manager, "google_sso_start",
                      new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True, "watching": True, "phase": "watching"}
        resp = client.post("/api/mcp/google-sso")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock.assert_awaited_once()


def test_launch_endpoint_and_sso_share_force_window_guarantee():
    """Tanto «Continuar con Google» (google-sso) como «Abrir Ventana»
    (google-sso/launch sin body) fuerzan ventana → un solo contrato."""
    with patch.object(mcpm.manager, "launch_google_login",
                      new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True}
        client.post("/api/mcp/google-sso/launch")
    assert mock.await_args.kwargs["force_window"] is True


# ── 3 · Windows: None también purga (fail-safe contra fantasmas) ─────────
def test_windows_none_window_state_purges_without_force(tmp_path, monkeypatch):
    """En Windows, PowerShell roto/colgado (None) NO reutiliza la instancia:
    se purga y relanza. En no-Windows None es estructural → no purga."""
    for platform, expected_purge in (("win32", True), ("linux", False)):
        monkeypatch.setattr(sys, "platform", platform)
        mgr = mcpm.MCPClientManager()
        mgr._cdp_up = AsyncMock(return_value=True)
        mgr._windows_visible_state = MagicMock(return_value=None)
        mgr.kill_profile_processes = MagicMock(return_value=[7, 8])
        mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
        mgr._find_chrome_bin = lambda: "chrome.exe"
        mgr._spawn_chrome = MagicMock(return_value=10)
        res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"],
                                                  cdp=True))
        if expected_purge:
            assert res["relaunched"] is True and res["pid"] == 10
            mgr.kill_profile_processes.assert_called()
        else:
            assert res["already_up"] is True and res["relaunched"] is False
            mgr.kill_profile_processes.assert_not_called()
            mgr._spawn_chrome.assert_not_called()


# ── 4 · _windows_visible_state: sondeo ligero e inofensivo ───────────────
def test_visible_state_probe_is_lightweight(monkeypatch, tmp_path):
    """≤3 s de timeout, PowerShell -NonInteractive y filtrado WQL por perfil."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = SimpleNamespace(returncode=0,
                           stdout=json.dumps([{"pid": 5, "hwnd": 99}]),
                           stderr="")
    with patch.object(mcpm.subprocess, "run", return_value=fake) as run_mock:
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is True
    assert run_mock.call_args.kwargs["timeout"] <= 3.0
    argv = run_mock.call_args[0][0]
    assert "-NonInteractive" in argv and "-NoProfile" in argv
    ps = argv[-1]
    assert tmp_path.name in ps          # filtra CommandLine por el perfil
    assert "MainWindowHandle" in ps     # pregunta la ventana real
    assert "SELECT ProcessId, CommandLine" in ps   # WQL ligera


def test_visible_state_timeout_returns_none(monkeypatch, tmp_path):
    """Timeout del sondeo → None (desconocido); nunca cuelga más de 3 s."""
    monkeypatch.setattr(sys, "platform", "win32")
    with patch.object(mcpm.subprocess, "run",
                      side_effect=__import__("subprocess").TimeoutExpired(
                          cmd="powershell", timeout=3.0)):
        mgr = mcpm.MCPClientManager()
        assert mgr._windows_visible_state(tmp_path) is None


# ── 5 · _spawn_chrome: Popen directo (la ventana SÍ aparece) ─────────────
def test_spawn_chrome_windows_uses_plain_popen(monkeypatch):
    """Popen directo con CREATE_NEW_PROCESS_GROUP — nada de cmd.exe/.bat/
    DETACHED_PROCESS (que aislaba el proceso de WinSta0 y la ventana no
    salía en el escritorio)."""
    monkeypatch.setattr(sys, "platform", "win32")
    popen = MagicMock(return_value=SimpleNamespace(pid=4321))
    with patch.object(mcpm.subprocess, "Popen", popen):
        mgr = mcpm.MCPClientManager()
        pid = mgr._spawn_chrome(["chrome.exe", "--new-window",
                                 "--start-maximized", "https://accounts.google.com/"])
    assert pid == 4321
    args, kwargs = popen.call_args
    assert args[0][0] == "chrome.exe"
    assert kwargs["creationflags"] == getattr(
        mcpm.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    assert not (kwargs["creationflags"] &
                getattr(mcpm.subprocess, "DETACHED_PROCESS", 0x8))
    assert kwargs["stderr"] == mcpm.subprocess.DEVNULL


def test_spawn_chrome_windows_startfile_fallback(monkeypatch):
    """Si Popen falla, os.startfile (ShellExecuteEx → escritorio interactivo)
    recibe TODOS los argumentos con el user-data-dir correctamente cotizado."""
    monkeypatch.setattr(sys, "platform", "win32")
    with patch.object(mcpm.subprocess, "Popen", side_effect=OSError("boom")), \
         patch.object(mcpm.os, "startfile", create=True) as startfile:
        mgr = mcpm.MCPClientManager()
        pid = mgr._spawn_chrome(["chrome.exe",
                                 "--user-data-dir=C:/Mi Carpeta/Flow",
                                 "--start-maximized", "https://x.com/"])
    assert pid == 0
    assert startfile.call_args[0][0] == "chrome.exe"
    args_str = startfile.call_args[1]["arguments"]
    assert '--user-data-dir="C:/Mi Carpeta/Flow"' in args_str
    assert "--start-maximized" in args_str


# ── 6 · No-Windows: spawn clásico intacto (start_new_session) ────────────
def test_spawn_chrome_posix_unchanged(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    popen = MagicMock(return_value=SimpleNamespace(pid=88))
    with patch.object(mcpm.subprocess, "Popen", popen) as p:
        mgr = mcpm.MCPClientManager()
        assert mgr._spawn_chrome(["google-chrome", "--start-maximized"]) == 88
    assert p.call_args.kwargs["start_new_session"] is True
    assert "creationflags" not in p.call_args.kwargs


# ── 7 · INT-081b: confirmación post-spawn (lección BROWSER-FACTORY) ──────
def test_spawn_confirmed_when_cdp_comes_up(monkeypatch):
    """Tras lanzar Chrome, se espera ≤3 s a que el CDP responda y, en
    Windows, se sondea la ventana real → evidencia en la respuesta."""
    monkeypatch.setattr(sys, "platform", "win32")
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(side_effect=[False, True])   # 1ª: pre-check; 2ª: confirm
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
    mgr._windows_visible_state = MagicMock(return_value=True)
    mgr._find_chrome_bin = lambda: "chrome.exe"
    mgr._spawn_chrome = MagicMock(return_value=777)
    res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["spawn_confirmed"] is True
    assert res["window_state_after_spawn"] is True
    assert res["pid"] == 777


def test_spawn_confirmed_false_when_cdp_never_comes_up(monkeypatch):
    """Chrome lanzado pero CDP muerto tras 3 s → spawn_confirmed=False
    (el toast ya NO puede mentir: el campo delata el fantasma nuevo)."""
    monkeypatch.setattr(sys, "platform", "win32")
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=False)
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
    mgr._windows_visible_state = MagicMock(
        side_effect=AssertionError("sin CDP no hay sondeo de ventana"))
    mgr._find_chrome_bin = lambda: "chrome.exe"
    mgr._spawn_chrome = MagicMock(return_value=778)
    res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["spawn_confirmed"] is False
    assert res["window_state_after_spawn"] is None
    assert res["pid"] == 778


def test_spawn_confirmed_none_when_reusing_existing_cdp(monkeypatch):
    """Reutilización legacy (CDP arriba + ventana viva + sin force): no hubo
    spawn → spawn_confirmed None, sin esperas ni sondeos extra."""
    monkeypatch.setattr(sys, "platform", "linux")
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._windows_visible_state = MagicMock(return_value=True)
    mgr.kill_profile_processes = MagicMock(return_value=[])
    mgr.heal_chrome_profile = MagicMock(return_value={"ok": True, "actions": []})
    mgr._spawn_chrome = MagicMock(side_effect=AssertionError("no debe haber spawn"))
    res = asyncio.run(mgr.launch_google_login(["https://flow.google.com/"], cdp=True))
    assert res["already_up"] is True
    assert res["spawn_confirmed"] is None
    assert res["window_state_after_spawn"] is None
    mgr._windows_visible_state.assert_called_once()   # solo el sondeo pre-existente


def test_sso_start_propagates_spawn_confirmation():
    """La respuesta de «Continuar con Google» incluye spawn_confirmed y
    window_state_after_spawn para diagnosticar sin tocar logs."""
    mgr = mcpm.MCPClientManager()

    async def fake_launch(urls=None, cdp=True, force_window=False):
        return {"ok": True, "already_up": False, "cdp_port": 9333,
                "heal_actions": [], "notebooklm_storage": {"exists": False},
                "relaunched": True, "window_state": None, "killed_pids": [],
                "pid": 555, "spawn_confirmed": True,
                "window_state_after_spawn": True}

    mgr.launch_google_login = AsyncMock(side_effect=fake_launch)
    mgr._sso_watchdog = AsyncMock()
    res = asyncio.run(mgr.google_sso_start())
    assert res["spawn_confirmed"] is True
    assert res["window_state_after_spawn"] is True
    assert res["pid"] == 555
