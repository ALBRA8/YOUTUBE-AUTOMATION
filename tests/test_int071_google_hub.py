"""
Tests para INT-071: Google One-Tap Hub — «[G] Continuar con Google»
- Extracción de cuenta (pura): _account_from_email / account_from_html /
  account_from_targets (estrategias CDP /json/list y SignOutOptions)
- google_sso_start: abre AccountChooser + NotebookLM y arranca el watchdog
- _sso_watchdog: detección cookie __Secure-1PSID/SID → captura + conexión
  (con NO_GOOGLE_COOKIES vuelve a watching; timeout honesto)
- google_sso_status: fase, cuenta y pills por servicio (Flow/NotebookLM/Workspace)
- google_sso_logout: cancela watcher, desconecta MCP, archiva storage (.bak)
- Endpoints REST: POST /api/mcp/google-sso · GET /api/mcp/google-sso/status ·
  POST /api/mcp/google-sso/logout (los 3 aditivos, los viejos intactos)

Hermeticidad: cero red, cero Chrome, cero Playwright — todo con AsyncMock.
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from services import mcp_manager as mcpm
from main import app

client = TestClient(app)

ACCOUNT = {"email": "johan.bravo2023@gmail.com",
           "name": "Johan Bravo2023", "initial": "J"}


# ── 1 · Extracción de cuenta (funciones puras) ─────────────────────────
def test_account_from_email_derives_name_and_initial():
    acc = mcpm._account_from_email("johan.bravo2023@gmail.com")
    assert acc["email"] == "johan.bravo2023@gmail.com"
    assert acc["name"] == "Johan Bravo2023"
    assert acc["initial"] == "J"


def test_account_from_html_signout_options_data_email():
    html = ('<html><div class="account" data-email="albragroup8@gmail.com">'
            '<img aria-label="ALBRA GROUP"> Cerrar sesión de albragroup8@gmail.com</div></html>')
    acc = mcpm.account_from_html(html)
    assert acc and acc["email"] == "albragroup8@gmail.com"
    assert acc["initial"] == "A"


def test_account_from_html_fallback_plain_regex():
    html = "<html><body>Sesión iniciada como johanbravo2023@gmail.com — cuenta</body></html>"
    acc = mcpm.account_from_html(html)
    assert acc and acc["email"] == "johanbravo2023@gmail.com"


def test_account_from_html_junk_and_empty():
    assert mcpm.account_from_html("") is None
    assert mcpm.account_from_html("nada de emails aquí") is None
    assert mcpm.account_from_html("user@example.com y foo@domain.com") is None


def test_account_from_targets_authuser_param():
    targets = [{"url": "https://labs.google/fx/tools/flow?authuser=johan.bravo2023@gmail.com",
                "title": "Flow"}]
    assert mcpm.account_from_targets(targets)["email"] == "johan.bravo2023@gmail.com"


def test_account_from_targets_title_and_empty():
    targets = [{"url": "https://notebooklm.google.com/", "title": "NotebookLM - albragroup8@gmail.com"}]
    assert mcpm.account_from_targets(targets)["email"] == "albragroup8@gmail.com"
    assert mcpm.account_from_targets([]) is None
    assert mcpm.account_from_targets([{"url": "https://google.com", "title": "x"}]) is None


# ── 2 · google_sso_start: AccountChooser + watchdog ────────────────────
def test_google_sso_start_launches_accountchooser_and_watching():
    mgr = mcpm.MCPClientManager()
    captured = {}

    async def fake_launch(urls, cdp=True):
        captured["urls"] = urls
        captured["cdp"] = cdp
        return {"ok": True, "already_up": False, "cdp_port": 9333,
                "heal_actions": [], "notebooklm_storage": {"exists": False}}

    mgr.launch_google_login = AsyncMock(side_effect=fake_launch)
    mgr._sso_watchdog = AsyncMock()  # el watchdog real no corre en el test

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None:
            "https://accounts.google.com/AccountChooser?service=lso&continue=https://labs.google/fx/tools/flow"
            if k == "GOOGLE_SSO_URL" else d):
        res = asyncio.run(mgr.google_sso_start())

    assert res["ok"] is True and res["watching"] is True and res["phase"] == "watching"
    assert captured["cdp"] is True
    assert "AccountChooser" in captured["urls"][0]
    assert "labs.google/fx/tools/flow" in captured["urls"][0]
    assert captured["urls"][1] == "https://notebooklm.google.com/"
    assert mgr._sso["phase"] == "watching"
    assert mgr._sso["task"] is not None  # watchdog arrancado (mock)


# ── 3 · _sso_watchdog: detección → conexión ────────────────────────────
def test_sso_watchdog_connects_when_cookie_detected():
    mgr = mcpm.MCPClientManager()
    mgr._cdp_has_google_auth = AsyncMock(return_value=(True, "Sesión activa"))
    mgr.capture_google_session = AsyncMock(return_value={"ok": True, "cookies": 42})
    mgr.connect = AsyncMock(side_effect=lambda svc, **kw: {"service": svc, "state": mcpm.ST_CONNECTED})
    mgr.google_account_info = AsyncMock(return_value=dict(ACCOUNT))
    mgr._sso["phase"] = "watching"        # estado previo que deja google_sso_start
    mgr._sso["started_at"] = time.time()

    asyncio.run(mgr._sso_watchdog())

    assert mgr._sso["phase"] == "connected"
    assert mgr._sso["account"]["email"] == ACCOUNT["email"]
    mgr.connect.assert_any_await("google-flow")
    mgr.connect.assert_any_await("notebooklm")
    mgr.capture_google_session.assert_awaited_once()


def test_sso_watchdog_no_cookies_keeps_watching_then_timeout():
    mgr = mcpm.MCPClientManager()
    calls = {"auth": 0}

    async def fake_auth(port):
        calls["auth"] += 1
        return True, "ok"

    mgr._cdp_has_google_auth = AsyncMock(side_effect=fake_auth)

    def fake_capture():
        raise mcpm.MCPManagerError("sin cookies todavía", "NO_GOOGLE_COOKIES")

    mgr.capture_google_session = AsyncMock(side_effect=fake_capture)
    mgr.connect = AsyncMock()
    mgr.google_account_info = AsyncMock()
    mgr._sso["phase"] = "watching"        # estado previo que deja google_sso_start
    mgr._sso["started_at"] = time.time() - 10_000  # timeout ya vencido

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None:
            60 if k == "GOOGLE_SSO_TIMEOUT_S" else d):
        asyncio.run(mgr._sso_watchdog())

    # NO_GOOGLE_COOKIES → reintenta (no conecta), y al vencer el plazo → timeout
    mgr.connect.assert_not_awaited()
    assert calls["auth"] >= 1
    assert mgr._sso["phase"] == "timeout"


def test_sso_finish_connect_mcp_error_does_not_break_connection():
    mgr = mcpm.MCPClientManager()
    mgr.capture_google_session = AsyncMock(return_value={"ok": True, "cookies": 10})
    mgr.connect = AsyncMock(side_effect=RuntimeError("node no encontrado"))
    mgr.google_account_info = AsyncMock(return_value=dict(ACCOUNT))

    done = asyncio.run(mgr._sso_finish_connect(9333))

    assert done is True
    assert mgr._sso["phase"] == "connected"          # sesión capturada manda
    assert "node no encontrado" in mgr._sso["flow_error"]


# ── 4 · google_sso_status ──────────────────────────────────────────────
def _fake_conn(service, tools=()):
    return SimpleNamespace(service=service, state=mcpm.ST_CONNECTED,
                           auth="ok", auth_detail="", proc=None,
                           connected_at=time.time(), server_info={"name": "fake"},
                           tools=[{"name": t} for t in tools],
                           last_error="", stderr_tail=[])


async def test_sso_status_connected_when_auth_and_mcp_up():
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._cdp_has_google_auth = AsyncMock(return_value=(True, "Sesión activa"))
    mgr.nb_storage_state = MagicMock(return_value={"exists": True, "size_bytes": 15079,
                                                   "active": "/x/storage_state.json",
                                                   "paths": [], "mtime": 0.0})
    mgr._conns = {"google-flow": _fake_conn("google-flow"),
                  "notebooklm": _fake_conn("notebooklm", tools=["a", "b", "c"])}

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None:
            9333 if "PORT" in k else (Path("/tmp/fake") if "PROFILE" in k else d)):
        js = await mgr.google_sso_status()

    assert js["sso_phase"] == "connected"        # alias honesto (watcher idle)
    assert js["session_auth"] is True
    assert js["services"]["flow"]["state"] == "connected"
    assert js["services"]["notebooklm"]["state"] == "connected"
    assert js["services"]["notebooklm"]["tools"] == 3
    assert js["services"]["workspace"]["state"] == "connected"
    assert js["poll_s"] >= 1
    assert "task" not in js                       # el task del watcher NUNCA se serializa


async def test_sso_status_watching_phase_wins():
    mgr = mcpm.MCPClientManager()
    mgr._cdp_up = AsyncMock(return_value=True)
    mgr._cdp_has_google_auth = AsyncMock(return_value=(False, "sin cookies"))
    mgr.nb_storage_state = MagicMock(return_value={"exists": False, "size_bytes": 0,
                                                   "active": "", "paths": [], "mtime": 0.0})
    mgr._sso["phase"] = "watching"

    with patch.object(mcpm, "_cfg", side_effect=lambda k, d=None:
            9333 if "PORT" in k else (Path("/tmp/fake") if "PROFILE" in k else d)):
        js = await mgr.google_sso_status()

    assert js["sso_phase"] == "watching"
    assert js["services"]["flow"]["state"] == "disconnected"
    assert js["services"]["workspace"]["state"] == "disconnected"


# ── 5 · google_sso_logout ──────────────────────────────────────────────
def test_sso_logout_cancels_disconnects_and_archives_storage(tmp_path):
    mgr = mcpm.MCPClientManager()
    f1 = tmp_path / "storage_state.json"
    f2 = tmp_path / "nested" / "storage_state.json"
    f2.parent.mkdir(parents=True)
    f1.write_text('{"cookies": []}', encoding="utf-8")
    f2.write_text('{"cookies": []}', encoding="utf-8")
    mgr._nb_storage_paths = lambda: [f1, f2]
    mgr.disconnect = AsyncMock(return_value={"ok": True})
    mgr.kill_profile_processes = MagicMock(return_value=[111, 222])
    mgr._sso["account"] = dict(ACCOUNT)
    mgr._sso["phase"] = "connected"

    async def run():
        mgr._sso["task"] = asyncio.create_task(asyncio.sleep(60))  # watcher vivo
        await asyncio.sleep(0)
        return await mgr.google_sso_logout()

    res = asyncio.run(run())

    assert res["ok"] is True
    assert any("vigilancia" in a for a in res["actions"])
    assert any("google-flow desconectado" == a for a in res["actions"])
    assert any(".bak-" in a for a in res["actions"])
    assert not f1.exists() and not f2.exists()
    assert list(tmp_path.glob("**/*.bak-*")) and len(list(tmp_path.glob("**/*.bak-*"))) == 2
    assert mgr._sso["phase"] == "idle" and mgr._sso["account"] is None


# ── 6 · Endpoints REST (aditivos; los viejos intactos) ─────────────────
def test_api_google_sso_start_endpoint():
    with patch.object(mcpm.manager, "google_sso_start", new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True, "watching": True, "phase": "watching",
                             "cdp_port": 9333, "pages": ["https://accounts.google.com/AccountChooser?service=lso&continue=https://labs.google/fx/tools/flow",
                                                          "https://notebooklm.google.com/"],
                             "already_up": False, "heal_actions": [],
                             "notebooklm_storage": {"exists": False}}
        resp = client.post("/api/mcp/google-sso")
        assert resp.status_code == 200
        data = resp.json()
        assert data["watching"] is True
        assert "AccountChooser" in data["pages"][0]


def test_api_google_sso_status_endpoint():
    with patch.object(mcpm.manager, "google_sso_status", new_callable=AsyncMock) as mock:
        mock.return_value = {"cdp_port": 9333, "chrome_up": True,
                             "sso_phase": "connected", "session_auth": True,
                             "account": dict(ACCOUNT),
                             "services": {"flow": {"state": "connected", "auth": "ok"},
                                          "notebooklm": {"state": "connected", "auth": "ok", "tools": 32},
                                          "workspace": {"state": "connected", "note": "misma sesión"}},
                             "poll_s": 2}
        resp = client.get("/api/mcp/google-sso/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sso_phase"] == "connected"
        assert data["account"]["email"] == ACCOUNT["email"]
        assert data["services"]["notebooklm"]["tools"] == 32


def test_api_google_sso_logout_endpoint():
    with patch.object(mcpm.manager, "google_sso_logout", new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True, "actions": ["google-flow desconectado"]}
        resp = client.post("/api/mcp/google-sso/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


def test_legacy_endpoints_still_registered():
    """Regresión INT-025/043: nada del Hub rompe las rutas existentes."""
    routes = {r.path for r in app.routes}
    for legacy in ("/api/mcp/login-google", "/api/mcp/connect-all-google",
                   "/api/mcp/capture-google-session", "/api/mcp/launch-auth-browser",
                   "/api/mcp/repair-profile", "/api/mcp/launch-clean-login"):
        assert legacy in routes, f"endpoint legacy {legacy} desapareció"


# ── 7 · Contrato de config ─────────────────────────────────────────────
def test_config_sso_defaults():
    from importlib import reload
    import config as cfg
    reload(cfg)
    assert "AccountChooser" in cfg.GOOGLE_SSO_URL
    assert "labs.google/fx/tools/flow" in cfg.GOOGLE_SSO_URL
    assert cfg.GOOGLE_SSO_POLL_S == 2
    assert cfg.GOOGLE_SSO_TIMEOUT_S >= 60
