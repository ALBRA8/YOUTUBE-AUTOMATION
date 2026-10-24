"""Batería INT-036 · Auto-Heal Corrupted Chrome Profile & Strict Cookie-Based Auth.

Verifica los 3 pilares arquitecturales del mandato INT-036:
1. Saneamiento automático de perfiles dañados (Local State.bad, Preferences exit_type, lockfile).
2. URL directa de autenticación Google (accounts.google.com/ServiceLogin?continue=...flow) en Tab 1.
3. Verificación estricta de cookies Google (SID / __Secure-1PSID) en CDP 9333 antes de marcar AUTENTICADO.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402

FAIL = 0
TOTAL = 0


def check(desc: str, ok: bool, detail: object = None) -> None:
    global FAIL, TOTAL
    TOTAL += 1
    if ok:
        print(f"  ✓ {desc}")
    else:
        FAIL += 1
        print(f"  ✗ {desc} — {detail}")


def test_auto_heal_profile():
    print("\n── 1. Auto-Heal Chrome Profile ──")
    with tempfile.TemporaryDirectory(prefix="heal_test_") as td:
        prof = Path(td)
        # Fabricar profile dañado con Local State.bad, lockfile y Preferences Crashed
        (prof / "Local State.bad").write_text("corrupted", encoding="utf-8")
        (prof / "lockfile").write_text("", encoding="utf-8")
        (prof / "SingletonLock").write_text("123", encoding="utf-8")
        (prof / "SingletonCookie").write_text("456", encoding="utf-8")
        (prof / "SingletonSocket").write_text("789", encoding="utf-8")

        default_dir = prof / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)
        pref_file = default_dir / "Preferences"
        pref_file.write_text(json.dumps({
            "profile": {"exit_type": "Crashed", "exited_cleanly": False},
            "exit_type": "Crashed"
        }), encoding="utf-8")

        # Ejecutar saneamiento
        res = mcpm.MCPClientManager.heal_chrome_profile(prof)
        check("heal_chrome_profile reporta ok", res.get("ok") is True)
        check("Local State.bad fue eliminado", not (prof / "Local State.bad").exists())
        check("lockfile fue eliminado", not (prof / "lockfile").exists())
        check("SingletonLock fue eliminado", not (prof / "SingletonLock").exists())
        check("SingletonCookie fue eliminado", not (prof / "SingletonCookie").exists())
        check("SingletonSocket fue eliminado", not (prof / "SingletonSocket").exists())

        # Verificar que Preferences quedó saneado
        repaired_prefs = json.loads(pref_file.read_text(encoding="utf-8"))
        prof_obj = repaired_prefs.get("profile", {})
        check("Preferences exit_type saneado a Normal", prof_obj.get("exit_type") == "Normal")
        check("Preferences exited_cleanly saneado a True", prof_obj.get("exited_cleanly") is True)
        check("Root exit_type saneado a Normal", repaired_prefs.get("exit_type") == "Normal")

        # Probar Preferences completamente corrupto (JSON inválido)
        pref_file.write_text("{invalid json corrupt", encoding="utf-8")
        res2 = mcpm.MCPClientManager.heal_chrome_profile(prof)
        check("heal recupera JSON corrupto", res2.get("ok") is True)
        repaired2 = json.loads(pref_file.read_text(encoding="utf-8"))
        check("Preferences re-generado con exit_type Normal",
              repaired2.get("profile", {}).get("exit_type") == "Normal")


def test_auth_landing_urls():
    print("\n── 2. Force Real Google Login Page First ──")
    pages = config.GOOGLE_LOGIN_PAGES
    check("GOOGLE_LOGIN_PAGES configurado con al menos 2 pestañas", len(pages) >= 2, pages)
    tab1 = pages[0]
    check("Tab 1 apunta a ServiceLogin de Google con continue hacia Flow",
          "accounts.google.com" in tab1 and "continue=" in tab1 and "flow" in tab1, tab1)
    tab2 = pages[1]
    check("Tab 2 apunta a NotebookLM", "notebooklm.google.com" in tab2, tab2)


async def test_strict_cookie_auth():
    print("\n── 3. Strict Cookie-Based Auth Verification ──")
    m = mcpm.MCPClientManager()

    # (a) Chrome activo en CDP pero SIN cookies de Google
    async def fake_up_true(port):
        return True
    m._cdp_up = fake_up_true

    async def fake_cookies_empty(port, timeout=4.0):
        return []
    m._cdp_fetch_cookies_raw = fake_cookies_empty

    auth_ok, detail = await m._cdp_has_google_auth(9333)
    check("Sin cookies en CDP → auth_ok False", auth_ok is False)
    check("Mensaje describe falta de sesión/cookies", "sesión no iniciada" in detail.lower() or "falta cookie" in detail.lower(), detail)

    # (b) Chrome activo en CDP con cookies ajenas (no Google)
    async def fake_cookies_other(port, timeout=4.0):
        return [{"name": "random_sess", "value": "xyz", "domain": "example.com"}]
    m._cdp_fetch_cookies_raw = fake_cookies_other

    auth_ok, detail = await m._cdp_has_google_auth(9333)
    check("Cookies ajenas sin SID de Google → auth_ok False", auth_ok is False)
    check("Detalle indica falta de cookies de autenticación", "falta cookie" in detail.lower(), detail)

    # (c) Preflight sobre google-flow sin cookies → degrada a auth_required (NUNCA falso ok)
    conn = mcpm._Conn("google-flow")
    conn.tools = [{"name": "flow_list_assets"}]
    await m._preflight(conn, None)
    check("Preflight de Flow sin cookies → auth_required", conn.auth == "auth_required", conn.auth)
    check("Preflight de Flow sin cookies → state ST_AUTH_REQUIRED", conn.state == mcpm.ST_AUTH_REQUIRED)

    # (d) Chrome activo con cookie __Secure-1PSID en .google.com
    async def fake_cookies_auth(port, timeout=4.0):
        return [
            {"name": "__Secure-1PSID", "value": "test_token_123", "domain": ".google.com"},
            {"name": "SID", "value": "test_sid_456", "domain": ".google.com"}
        ]
    m._cdp_fetch_cookies_raw = fake_cookies_auth

    auth_ok, detail = await m._cdp_has_google_auth(9333)
    check("Cookie __Secure-1PSID en .google.com → auth_ok True", auth_ok is True)
    check("Detalle indica sesión activa", "sesión activa" in detail.lower(), detail)

    # Preflight de Flow con cookies válidas
    async def fake_call(tool, args, timeout=None):
        return "Project test: 2 assets"
    conn.call = fake_call
    conn.state = mcpm.ST_CONNECTED
    await m._preflight(conn, None)
    check("Preflight de Flow con cookies válidas → auth ok", conn.auth == "ok", conn.auth)


def main() -> int:
    test_auto_heal_profile()
    test_auth_landing_urls()
    asyncio.run(test_strict_cookie_auth())
    print(f"\n{'='*50}\nTOTAL: {TOTAL} tests | FALLOS: {FAIL}\n{'='*50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
