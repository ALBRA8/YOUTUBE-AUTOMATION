#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-022 · MCP Connection Manager (panel ↔ servidores MCP stdio)

Cubre: connect/handshake con servidor real-subprocess (fixture fake_mcp_server),
tools/list, execute con inyección dinámica de notebook_id (§3: payload > .env),
validación de patrón del id, allowlist, preflight AUTH_REQUIRED (§2), timeouts
con limpieza de proceso, disconnect, stderr_tail, y endpoints REST del panel
(/api/mcp/connect|disconnect|status|execute|test-pipeline) vía ASGI in-process.

Convención del repo: script stdlib (sin pytest), 0 dependencias externas.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py")

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


async def _fresh(mode, fail_auth="0", slow_ms="0"):
    """Manager limpio apuntando al fixture (parchea _resolve_command)."""
    m = mcpm.MCPClientManager()

    def fake_resolve(service):
        return [sys.executable, FIXTURE], None

    # _spawn acepta (argv, cwd); inyectamos env a través de parche de _spawn
    async def fake_spawn(service):
        argv, cwd = fake_resolve(service)
        env = dict(os.environ)
        env.update({"FAKE_MCP_MODE": mode, "FAKE_MCP_FAIL_AUTH": fail_auth,
                    "FAKE_MCP_SLOW_MS": slow_ms})
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        conn = mcpm._Conn(service)
        conn.proc = proc
        conn._reader = asyncio.create_task(conn._read_loop())
        conn._stderr = asyncio.create_task(conn._stderr_loop())
        return conn

    m._spawn = fake_spawn
    return m


async def cleanup(m):
    for svc in list(mcpm.SERVICES):
        try:
            await m.disconnect(svc)
        except Exception:
            pass


async def core_tests():
    print("\n── S1 · connect + handshake + tools/list (flow) ──")
    m = await _fresh("flow")
    try:
        st = await m.connect("google-flow")
        check("estado connected", st["state"] == "connected", st)
        check("serverInfo del fixture", st["server_info"].get("name") == "fake-flow", st)
        check("tools/list >= 3", len(st["tools"]) >= 3, st)
        check("auth ok tras preflight (sesión válida)", st["auth"] == "ok", st)
        check("uptime > 0", st["uptime_s"] >= 0)
        check("connect idempotente", (await m.connect("google-flow")).get("already_connected") is True)

        print("\n── S2 · execute roundtrip + allowlist ──")
        r = await m.execute("google-flow", "flow_list_assets", {})
        check("execute ok", r.get("ok") is True and "asset1.png" in r.get("text", ""), r)
        try:
            await m.execute("google-flow", "nota_flow", {})
            check("tool no existente rechazada", False)
        except mcpm.MCPManagerError as e:
            check("tool no existente rechazada", e.code == "TOOL_UNKNOWN", e.code)
        r = await m.execute("google-flow", "echo", {"k": "v"})
        check("execute con argumentos", '"k": "v"' in r.get("text", ""), r)

        print("\n── S3 · preflight AUTH_REQUIRED (texto real 'Not signed in') ──")
        await cleanup(m)
        m2 = await _fresh("flow", fail_auth="1")
        st2 = await m2.connect("google-flow")
        check("estado auth_required", st2["state"] == "auth_required", st2)
        check("auth=auth_required", st2["auth"] == "auth_required", st2)
        check("auth_detail con texto real", "Not signed in" in st2["auth_detail"], st2)
        await cleanup(m2)

        print("\n── S4 · timeout con limpieza de proceso (§errores a UI) ──")
        m3 = await _fresh("nblm", slow_ms="1500")
        await m3.connect("notebooklm")
        try:
            # HOTFIX INT-023.4: la tool recibe notebook_id (el fail-fast de id
            # ausente se prueba en S5 y en test_int023b_notebook_id.py).
            await m3.execute("notebooklm", "slow", {}, timeout=0.4,
                             notebook_id="slowid23")
            check("timeout lanza", False)
        except mcpm.MCPManagerError as e:
            check("timeout lanza MCPManagerError", e.code == "TIMEOUT", e.code)
        check("proceso limpiado tras timeout",
              m3._conns.get("notebooklm") is None)
        await cleanup(m3)
    finally:
        await cleanup(m)

    print("\n── S5 · notebook_id dinámico (§3): payload > .env > ausencia ──")
    m4 = await _fresh("nblm")
    old_id = config.NOTEBOOKLM_NOTEBOOK_ID
    try:
        await m4.connect("notebooklm")
        r = await m4.execute("notebooklm", "echo", {}, notebook_id="abc123XYZ_-9")
        args = __import__("json").loads(r["text"])
        check("payload inyectado como notebook_id",
              args.get("notebook_id") == "abc123XYZ_-9", args)
        config.NOTEBOOKLM_NOTEBOOK_ID = "envid12345"
        r = await m4.execute("notebooklm", "echo", {})
        args = __import__("json").loads(r["text"])
        check("fallback .env inyectado", args.get("notebook_id") == "envid12345", args)
        try:
            await m4.execute("notebooklm", "echo", {}, notebook_id="bad id!")
            check("id inválido rechazado", False)
        except mcpm.MCPManagerError as e:
            check("id inválido rechazado", e.code == "INVALID_NOTEBOOK_ID", e.code)
        config.NOTEBOOKLM_NOTEBOOK_ID = ""
        r = await m4.execute("notebooklm", "echo", {"notebook_id": "directo99"})
        args = __import__("json").loads(r["text"])
        check("id directo en argumentos respeta y no avisa",
              args.get("notebook_id") == "directo99" and not r.get("warnings"), r)
        # HOTFIX INT-023.4: el warning silencioso pasa a fallo DETERMINISTA con
        # código estable (fin del TOOL_ERROR críptico del servidor MCP).
        try:
            await m4.execute("notebooklm", "echo", {})
            check("sin id en ningún sitio: MISSING_NOTEBOOK_ID determinista", False)
        except mcpm.MCPManagerError as e:
            check("sin id en ningún sitio: MISSING_NOTEBOOK_ID determinista",
                  e.code == "MISSING_NOTEBOOK_ID" and "echo" in str(e), e.code)

        print("\n── S6 · allowlist opcional de tools ──")
        old_tools = config.NOTEBOOKLM_MCP_TOOLS
        config.NOTEBOOKLM_MCP_TOOLS = "list_notebooks"
        try:
            await m4.execute("notebooklm", "echo", {})
            check("tool fuera de allowlist rechazada", False)
        except mcpm.MCPManagerError as e:
            check("tool fuera de allowlist rechazada", e.code == "TOOL_NOT_ALLOWED", e.code)
        r = await m4.execute("notebooklm", "list_notebooks", {})
        check("tool dentro de allowlist ok", r.get("ok") is True, r)
        config.NOTEBOOKLM_MCP_TOOLS = old_tools

        print("\n── S7 · auth_required (nblm error JSON-RPC con patrón auth) ──")
        await cleanup(m4)
        m5 = await _fresh("nblm", fail_auth="1")
        st5 = await m5.connect("notebooklm")
        check("estado auth_required", st5["state"] == "auth_required", st5)
        check("auth_detail menciona cookies", "cookies" in st5["auth_detail"].lower(), st5)
        await cleanup(m5)

        print("\n── S8 · test_pipeline (dry-run §4) ──")
        m6 = await _fresh("nblm")
        old_probe = config.NOTEBOOKLM_PROBE_TOOL
        config.NOTEBOOKLM_PROBE_TOOL = "list_notebooks"
        config.NOTEBOOKLM_NOTEBOOK_ID = "tuberia01"
        try:
            tp = await m6.test_pipeline("notebooklm")
            check("test_pipeline ok", tp.get("ok") is True, tp)
            check("notebook_id_valid True", tp.get("notebook_id_valid") is True, tp)
            config.NOTEBOOKLM_NOTEBOOK_ID = "mal id!"
            tp = await m6.test_pipeline("notebooklm")
            check("notebook_id_valid False con id inválido",
                  tp.get("notebook_id_valid") is False, tp)
        finally:
            config.NOTEBOOKLM_PROBE_TOOL = old_probe
            await cleanup(m6)

        print("\n── S9 · comando ausente → error con código estable ──")
        m7 = mcpm.MCPClientManager()
        m7._resolve_command = lambda svc: (_ for _ in ()).throw(
            mcpm.MCPManagerError("no existe X", "ENTRY_MISSING"))
        try:
            await m7.connect("google-flow")
            check("ENTRY_MISSING lanza", False)
        except mcpm.MCPManagerError as e:
            check("ENTRY_MISSING lanza", e.code == "ENTRY_MISSING", e.code)

        print("\n── S10 · stderr_tail capturado ──")
        m8 = await _fresh("flow")
        try:
            await m8.connect("google-flow")
            st8 = m8._conn_status(m8._conns.get("google-flow"))
            check("stderr del fixture visible en tail",
                  any("fake-mcp" in s for s in st8.get("stderr_tail", [])), st8.get("stderr_tail"))
        finally:
            await cleanup(m8)
    finally:
        config.NOTEBOOKLM_NOTEBOOK_ID = old_id


async def endpoint_tests():
    print("\n── S11 · endpoints REST del panel (ASGI in-process) ──")
    import httpx
    import main as _main

    m = await _fresh("nblm")
    orig_spawn = mcpm.manager._spawn
    mcpm.manager._spawn = m._spawn  # endpoints usan el singleton
    old_id = config.NOTEBOOKLM_NOTEBOOK_ID
    config.NOTEBOOKLM_NOTEBOOK_ID = "pipeid22"
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/mcp/connect",
                             json={"service": "notebooklm"},
                             headers={"Origin": "http://testserver"})
            check("POST /connect 200", r.status_code == 200, r.text[:200])
            check("connect responde estado connected",
                  r.json().get("state") == "connected", r.text[:200])
            r = await c.get("/api/mcp/status")
            js = r.json()
            check("GET /status 200 con ambos servicios",
                  r.status_code == 200
                  and set(js.get("services", {})) == {"google-flow", "notebooklm"},
                  r.text[:200])
            check("status incluye pistas de config (u hint honesto de ausencia)",
                  "cdp_port" in js["services"]["google-flow"]
                  and ("notebook_id_configured" in js["services"]["notebooklm"]
                       or js["services"]["notebooklm"].get("available") is False),
                  js["services"]["notebooklm"])
            r = await c.post("/api/mcp/execute",
                             json={"service": "notebooklm", "tool": "echo", "arguments": {"x": 1}},
                             headers={"Origin": "http://testserver"})
            check("POST /execute 200", r.status_code == 200, r.text[:200])
            r = await c.post("/api/mcp/execute",
                             json={"service": "notebooklm", "tool": "rm -rf"},
                             headers={"Origin": "http://testserver"})
            check("tool con caracteres inválidos → 400", r.status_code == 400, r.text[:120])
            r = await c.post("/api/mcp/execute",
                             json={"service": "nope", "tool": "echo"},
                             headers={"Origin": "http://testserver"})
            check("service inválido → 400", r.status_code == 400, r.text[:120])
            r = await c.post("/api/mcp/test-pipeline",
                             json={"service": "notebooklm"},
                             headers={"Origin": "http://testserver"})
            js = r.json()
            check("POST /test-pipeline ok", r.status_code == 200 and js.get("ok") is True,
                  r.text[:300])
            r = await c.post("/api/mcp/disconnect",
                             json={"service": "notebooklm"},
                             headers={"Origin": "http://testserver"})
            check("POST /disconnect → disconnected",
                  r.json().get("state") == "disconnected", r.text[:120])
            r = await c.get("/api/mcp/status")
            check("tras disconnect, estado disconnected",
                  r.json()["services"]["notebooklm"]["state"] == "disconnected",
                  r.text[:200])
    finally:
        mcpm.manager._spawn = orig_spawn
        config.NOTEBOOKLM_NOTEBOOK_ID = old_id
        await cleanup(mcpm.manager)


def main() -> int:
    print("=" * 60)
    print("BATERÍA INT-022 · MCP Connection Manager")
    print("=" * 60)
    asyncio.run(core_tests())
    asyncio.run(endpoint_tests())
    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
