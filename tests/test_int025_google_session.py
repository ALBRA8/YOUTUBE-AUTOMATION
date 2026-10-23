#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-025 · Sesión Google unificada + notebook auto-dropdown

Escenario objetivo: UN solo login manual humano cubre ambos servidores MCP.
  · 🔑 launch_google_login(): Chrome REAL con user-data-dir compartido
    (GOOGLE_PROFILE_GLOBAL) + CDP en GOOGLE_LOGIN_CDP_PORT (= FLOW_CDP_PORT
    por defecto) → GoogleFlowMCP hace connectOverCDP a ESE Chrome.
  · 📥 capture_google_session(): cookies .google.com del MISMO Chrome vía
    CDP (Playwright, import diferido) → storage_state.json de notebooklm-py
    (estructura verificada del wheel 0.8.5: <home>/profiles/<profile>/
    storage_state.json con fallback legacy <home>/storage_state.json).
  · Estado consultable (google_login_status / GET /api/mcp/login-google).
  · UI v2.24.0: card «🔑 Sesión Google unificada» + dropdown de notebooks
    que se AUTORELLENA al conectar notebooklm (fin del copy-paste de UUIDs).

Regresión cubierta (todo hermético: cero Chrome, cero red, cero Playwright):
  S1 config · S2 _find_chrome_bin · S3 launch_google_login (argv/detach/reuse)
  S4 rutas storage_state · S5 capture (filtros, layouts, errores estables)
  S6 status · S7 inyección env del perfil global en _spawn (google-flow)
  S8 endpoints HTTP (200/502 con códigos estables) · S9 contrato UI.

Convención del repo: script stdlib (sin pytest), 0 dependencias externas
(salvo httpx para el transporte ASGI, igual que INT-023.4/024).
"""
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _cfg_overrides(**kw):
    """Parchea claves de config para el test y devuelve el restaurador."""
    old = {k: getattr(config, k, None) for k in kw}
    for k, v in kw.items():
        setattr(config, k, v)
    def restore():
        for k, v in old.items():
            setattr(config, k, v)
    return restore


# ───────────────────────────── S1 · config ──
def config_tests():
    print("\n── S1 · config INT-025 (defaults coherentes) ──")
    check("GOOGLE_PROFILE_GLOBAL bajo DATA_DIR por defecto",
          str(config.GOOGLE_PROFILE_GLOBAL).startswith(str(config.DATA_DIR))
          and config.GOOGLE_PROFILE_GLOBAL.name == "google_profile_global",
          config.GOOGLE_PROFILE_GLOBAL)
    check("GOOGLE_LOGIN_URL apunta a accounts.google.com",
          "accounts.google.com" in config.GOOGLE_LOGIN_URL,
          config.GOOGLE_LOGIN_URL)
    check("GOOGLE_LOGIN_CDP_PORT == FLOW_CDP_PORT (perfil compartido con Flow)",
          config.GOOGLE_LOGIN_CDP_PORT == config.FLOW_CDP_PORT,
          (config.GOOGLE_LOGIN_CDP_PORT, config.FLOW_CDP_PORT))
    check("MCP_LOGIN_CHROME_BIN default vacío (autodetección)",
          config.MCP_LOGIN_CHROME_BIN == "")
    check("NOTEBOOKLM_PROFILE default vacío (perfil default)",
          config.NOTEBOOKLM_PROFILE == "")


# ─────────────────────────── S2 · _find_chrome_bin ──
def chrome_bin_tests():
    print("\n── S2 · _find_chrome_bin: override → which → CHROME_NOT_FOUND ──")
    m = mcpm.MCPClientManager()
    tmp = Path(tempfile.mkdtemp(prefix="int025_bin_"))
    fake_bin = tmp / "chrome-fake"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(fake_bin, 0o755)
    r = _cfg_overrides(MCP_LOGIN_CHROME_BIN=str(fake_bin))
    try:
        check("override válido se respeta", m._find_chrome_bin() == str(fake_bin))
    finally:
        r()
    r = _cfg_overrides(MCP_LOGIN_CHROME_BIN=str(tmp / "no-existe.exe"))
    try:
        try:
            m._find_chrome_bin()
            check("override inexistente → CHROME_NOT_FOUND", False)
        except mcpm.MCPManagerError as e:
            check("override inexistente → CHROME_NOT_FOUND", e.code == "CHROME_NOT_FOUND")
    finally:
        r()
    orig_which = mcpm.shutil.which
    try:
        mcpm.shutil.which = lambda name: None
        r = _cfg_overrides(MCP_LOGIN_CHROME_BIN="")
        try:
            try:
                m._find_chrome_bin()
                check("sin binarios → CHROME_NOT_FOUND", False)
            except mcpm.MCPManagerError as e:
                check("sin binarios → CHROME_NOT_FOUND",
                      e.code == "CHROME_NOT_FOUND" and "MCP_LOGIN_CHROME_BIN" in str(e))
        finally:
            r()
        mcpm.shutil.which = lambda name: f"/usr/bin/{name}" if name == "google-chrome" else None
        check("which encuentra google-chrome",
              m._find_chrome_bin() == "/usr/bin/google-chrome")
    finally:
        mcpm.shutil.which = orig_which


# ─────────────────────── S3 · launch_google_login ──
async def launch_tests():
    print("\n── S3 · launch_google_login: argv, detach y reutilización ──")
    tmp = Path(tempfile.mkdtemp(prefix="int025_prof_"))
    prof = tmp / "google_profile_global"
    fake_bin = tmp / "chrome-fake"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(fake_bin, 0o755)
    m = mcpm.MCPClientManager()
    r = _cfg_overrides(GOOGLE_PROFILE_GLOBAL=str(prof),
                       MCP_LOGIN_CHROME_BIN=str(fake_bin),
                       GOOGLE_LOGIN_CDP_PORT=9777,
                       GOOGLE_LOGIN_URL="https://accounts.google.com/testlogin")
    orig_up = m._cdp_up
    orig_spawn = m._spawn_chrome
    spawned = []
    try:
        async def up_false(port):
            return False
        m._cdp_up = up_false
        def spawn(argv):
            spawned.append(list(argv))
            return 424242
        m._spawn_chrome = spawn
        js = await m.launch_google_login()
        check("lanza ok con pid", js.get("ok") and js.get("pid") == 424242, js)
        check("crea el directorio del perfil global", prof.is_dir(), prof)
        check("1 y solo 1 spawn", len(spawned) == 1, spawned)
        argv = spawned[0] if spawned else []
        check("argv usa el binario resuelto", argv[:1] == [str(fake_bin)], argv)
        check("argv fija --user-data-dir del perfil global",
              f"--user-data-dir={prof}" in argv, argv)
        check("argv fija --remote-debugging-port=GOOGLE_LOGIN_CDP_PORT",
              "--remote-debugging-port=9777" in argv, argv)
        check("argv NO es headful-forzado (login humano ve la ventana)",
              "--headless" not in argv and "--no-first-run" in argv, argv)
        check("argv abre la URL de login", "https://accounts.google.com/testlogin" in argv, argv)
        check("respuesta incluye storage de notebooklm",
              "notebooklm_storage" in js and js["cdp_port"] == 9777, js)

        # INT-026 · «Vincular Sesión Google (Login Único)": multi-pestaña
        spawned.clear()
        js_multi = await m.launch_google_login(
            ["https://flow.google.com/", "https://notebooklm.google.com/"])
        argv2 = spawned[0] if spawned else []
        check("multi-pestaña: flow.google.com + notebooklm en el argv",
              "https://flow.google.com/" in argv2
              and "https://notebooklm.google.com/" in argv2
              and argv2.index("https://flow.google.com/") > argv2.index("--disable-session-crashed-bubble"),
              argv2)
        check("respuesta ecoa las pestañas (pages)",
              js_multi.get("pages") == ["https://flow.google.com/",
                                        "https://notebooklm.google.com/"]
              and js_multi.get("login_url") == "https://flow.google.com/", js_multi)

        async def up_true(port):
            return True
        m._cdp_up = up_true
        js2 = await m.launch_google_login()
        check("CDP ya arriba → already_up y NO relanza",
              js2.get("already_up") is True and js2.get("pid") is None
              and len(spawned) == 1, (js2, len(spawned)))
    finally:
        m._cdp_up = orig_up
        m._spawn_chrome = orig_spawn
        r()

    # sin binario disponible → error estable
    m2 = mcpm.MCPClientManager()
    r2 = _cfg_overrides(GOOGLE_PROFILE_GLOBAL=str(tmp / "p2"),
                        MCP_LOGIN_CHROME_BIN="")
    orig_up2, orig_which = m2._cdp_up, mcpm.shutil.which
    try:
        async def up_false2(port):
            return False
        m2._cdp_up = up_false2
        mcpm.shutil.which = lambda name: None
        try:
            await m2.launch_google_login()
            check("sin Chrome en la máquina → CHROME_NOT_FOUND", False)
        except mcpm.MCPManagerError as e:
            check("sin Chrome en la máquina → CHROME_NOT_FOUND",
                  e.code == "CHROME_NOT_FOUND", e.code)
    finally:
        m2._cdp_up = orig_up2
        mcpm.shutil.which = orig_which
        r2()


# ───────────────────────── S4 · rutas storage_state ──
def storage_paths_tests():
    print("\n── S4 · _nb_storage_paths: estructura verificada del wheel 0.8.5 ──")
    tmp = Path(tempfile.mkdtemp(prefix="int025_home_"))
    home = tmp / "nblm-home"
    m = mcpm.MCPClientManager()
    r = _cfg_overrides(NOTEBOOKLM_HOME=str(home), NOTEBOOKLM_PROFILE="")
    try:
        ps = m._nb_storage_paths()
        check("perfil default → profiles/default + legacy root",
              ps[0] == home / "profiles" / "default" / "storage_state.json"
              and ps[1] == home / "storage_state.json", [str(p) for p in ps])
        st = m.nb_storage_state()
        check("sin archivos → exists False y active vacío",
              st["exists"] is False and st["active"] == "", st)
        home.mkdir(parents=True, exist_ok=True)
        legacy = home / "storage_state.json"
        legacy.write_text("{}", encoding="utf-8")
        st2 = m.nb_storage_state()
        check("legacy preexistente → active=legacy y exists True",
              st2["exists"] and st2["active"] == str(legacy), st2)
    finally:
        r()
    r = _cfg_overrides(NOTEBOOKLM_HOME=str(home), NOTEBOOKLM_PROFILE="work")
    try:
        ps = m._nb_storage_paths()
        check("NOTEBOOKLM_PROFILE respeta el nombre de perfil",
              ps[0] == home / "profiles" / "work" / "storage_state.json",
              [str(p) for p in ps])
    finally:
        r()
    r = _cfg_overrides(NOTEBOOKLM_HOME="", NOTEBOOKLM_PROFILE="")
    try:
        ps = m._nb_storage_paths()
        check("home vacío → ~/.notebooklm",
              ps[0].parent.parent.parent == Path.home() / ".notebooklm",
              [str(p) for p in ps])
    finally:
        r()


# ─────────────────── S5 · capture_google_session ──
async def capture_tests():
    print("\n── S5 · capture: filtros, layouts y errores estables ──")
    tmp = Path(tempfile.mkdtemp(prefix="int025_cap_"))
    home = tmp / "nblm-home"
    m = mcpm.MCPClientManager()
    cookies_raw = [
        {"name": "SID", "value": "v1", "domain": ".google.com", "path": "/"},
        {"name": "HSID", "value": "v2", "domain": ".google.com", "path": "/"},
        {"name": "SAPISID", "value": "v3", "domain": ".youtube.com", "path": "/"},
        {"name": "otra", "value": "x", "domain": ".example.com", "path": "/"},      # ajena
        {"name": "", "value": "y", "domain": ".google.com", "path": "/"},           # sin name
        {"name": "SID", "value": "dup", "domain": ".google.com", "path": "/"},      # dup
        {"name": "GV", "value": "z", "domain": ".gstatic.com", "path": "/"},
    ]
    r = _cfg_overrides(NOTEBOOKLM_HOME=str(home), NOTEBOOKLM_PROFILE="",
                       GOOGLE_LOGIN_CDP_PORT=9777)
    orig_up, orig_fetch = m._cdp_up, m._cdp_fetch_google_cookies_impl
    try:
        # (a) CDP abajo → CHROME_NOT_UP ANTES de tocar Playwright
        async def up_false(port):
            return False
        m._cdp_up = up_false
        try:
            await m.capture_google_session()
            check("CDP abajo → CHROME_NOT_UP", False)
        except mcpm.MCPManagerError as e:
            check("CDP abajo → CHROME_NOT_UP", e.code == "CHROME_NOT_UP", e.code)
        check("no se escribió nada sin CDP",
              not (home / "storage_state.json").exists())

        # (b) Playwright ausente → PLAYWRIGHT_MISSING
        async def up_true(port):
            return True
        m._cdp_up = up_true
        async def import_error(port):
            raise ImportError("No module named 'playwright'")
        m._cdp_fetch_google_cookies_impl = import_error
        try:
            await m.capture_google_session()
            check("Playwright ausente → PLAYWRIGHT_MISSING", False)
        except mcpm.MCPManagerError as e:
            check("Playwright ausente → PLAYWRIGHT_MISSING",
                  e.code == "PLAYWRIGHT_MISSING" and "playwright" in str(e).lower())

        # (c) 0 cookies google → NO_GOOGLE_COOKIES
        async def no_google(port):
            return [{"name": "x", "value": "y", "domain": ".example.com", "path": "/"}]
        m._cdp_fetch_google_cookies_impl = no_google
        try:
            await m.capture_google_session()
            check("0 cookies google → NO_GOOGLE_COOKIES", False)
        except mcpm.MCPManagerError as e:
            check("0 cookies google → NO_GOOGLE_COOKIES", e.code == "NO_GOOGLE_COOKIES")

        # (d) captura feliz sin layout previo → escribe en AMBAS rutas
        async def ok_fetch(port):
            return cookies_raw
        m._cdp_fetch_google_cookies_impl = ok_fetch
        js = await m.capture_google_session()
        modern = home / "profiles" / "default" / "storage_state.json"
        legacy = home / "storage_state.json"
        check("ok con nº de cookies filtradas (youtube excluida)",
              js.get("ok") and js.get("cookies") == 3, js)  # SID HSID GV
        check("sin layout previo escribe AMBAS rutas (compat)",
              sorted(js.get("storage_paths", [])) == sorted([str(modern), str(legacy)]),
              js.get("storage_paths"))
        data = json.loads(modern.read_text(encoding="utf-8"))
        doms = {c["domain"] for c in data["cookies"]}
        check("storage JSON con cookies google/gstatic únicamente",
              doms == {".google.com", ".gstatic.com"}
              and data.get("source") == "google_profile_global"
              and data.get("origins") == [], doms)
        names = [c["name"] for c in data["cookies"]]
        check("dedupe por (name,domain,path)", names.count("SID") == 1, names)
        mode = stat.S_IMODE(modern.stat().st_mode)
        check("storage_state con permisos 0600", mode == 0o600, oct(mode))
        check("legacy también escrito y 0600",
              json.loads(legacy.read_text(encoding="utf-8"))["cookies"][0]["name"] == "SID"
              and stat.S_IMODE(legacy.stat().st_mode) == 0o600)

        # (e) layout preexistente → SOLO se actualiza el existente
        home2 = tmp / "nblm-home2"
        r2 = _cfg_overrides(NOTEBOOKLM_HOME=str(home2), NOTEBOOKLM_PROFILE="work")
        try:
            m2 = mcpm.MCPClientManager()
            m2._cdp_up = up_true
            m2._cdp_fetch_google_cookies_impl = ok_fetch
            pre = home2 / "profiles" / "work" / "storage_state.json"
            pre.parent.mkdir(parents=True, exist_ok=True)
            pre.write_text("{\"cookies\":[],\"old\":true}", encoding="utf-8")
            js2 = await m2.capture_google_session()
            check("layout preexistente (profiles/work) respetado",
                  js2.get("storage_paths") == [str(pre)], js2.get("storage_paths"))
            check("archivo preexistente actualizado in-place",
                  json.loads(pre.read_text(encoding="utf-8")).get("cookies"), )
            check("legacy NO creado cuando el layout ya existía",
                  not (home2 / "storage_state.json").exists())
        finally:
            r2()
    finally:
        m._cdp_up = orig_up
        m._cdp_fetch_google_cookies_impl = orig_fetch
        r()

    # (f) filtro puro
    out = mcpm.MCPClientManager._filter_google_cookies(cookies_raw)
    check("filtro puro: 3 cookies, sin ajenas (.youtube/.example excluidas)",
          len(out) == 3 and all("google" in c["domain"] or "gstatic" in c["domain"]
                                for c in out), out)
    check("filtro puro: dicts con claves Playwright completas",
          all(set(c) >= {"name", "value", "domain", "path", "expires",
                         "httpOnly", "secure"} for c in out))
    check("filtro puro: [] con entrada vacía",
          mcpm.MCPClientManager._filter_google_cookies([]) == []
          and mcpm.MCPClientManager._filter_google_cookies(None) == [])


# ─────────────────────────── S6 · google_login_status ──
async def status_tests():
    print("\n── S6 · google_login_status (polling barato de la UI) ──")
    tmp = Path(tempfile.mkdtemp(prefix="int025_st_"))
    m = mcpm.MCPClientManager()
    r = _cfg_overrides(GOOGLE_PROFILE_GLOBAL=str(tmp / "prof"),
                       GOOGLE_LOGIN_CDP_PORT=9777, FLOW_CDP_PORT=9777)
    orig_up = m._cdp_up
    try:
        async def up_true(port):
            return True
        m._cdp_up = up_true
        js = await m.google_login_status()
        check("chrome_up + puerto + perfil presentes",
              js["chrome_up"] is True and js["cdp_port"] == 9777
              and js["profile_dir"].endswith("prof"), js)
        check("shared_with_flow True con mismo puerto", js["shared_with_flow"] is True)
        check("storage incluido en el estado",
              js["notebooklm_storage"]["exists"] is False)
    finally:
        m._cdp_up = orig_up
        r()
    r = _cfg_overrides(GOOGLE_LOGIN_CDP_PORT=9888, FLOW_CDP_PORT=9777)
    try:
        async def up_false(port):
            return False
        m._cdp_up = up_false
        js = await m.google_login_status()
        check("puerto distinto → shared_with_flow False y chrome_up False",
              js["shared_with_flow"] is False and js["chrome_up"] is False, js)
    finally:
        m._cdp_up = orig_up
        r()


# ─────────── S7 · inyección del perfil global en _spawn (google-flow) ──
async def spawn_env_tests():
    print("\n── S7 · _spawn expone GOOGLE_PROFILE_GLOBAL/FLOW_USER_DATA_DIR a Flow ──")
    tmp = Path(tempfile.mkdtemp(prefix="int025_env_"))
    prof = tmp / "google_profile_global"
    m = mcpm.MCPClientManager()

    def fake_resolve(service):
        return ["/bin/true"], None
    m._resolve_command = fake_resolve

    captured = {}

    class FakeProc:
        returncode = None
        stdin = None
        stdout = None
        stderr = None

        async def wait(self):
            return 0

    async def fake_exec(*argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env") or {}
        proc = FakeProc()

        async def rl():
            return b""
        proc.stdout = SimpleNamespace(readline=rl)
        proc.stderr = SimpleNamespace(readline=rl)
        return proc

    orig_exec = mcpm.asyncio.create_subprocess_exec
    os.environ.pop("GOOGLE_PROFILE_GLOBAL", None)
    os.environ.pop("FLOW_USER_DATA_DIR", None)
    r = _cfg_overrides(GOOGLE_PROFILE_GLOBAL=str(prof), FLOW_CDP_PORT=9333)
    try:
        mcpm.asyncio.create_subprocess_exec = fake_exec
        conn = await m._spawn("google-flow")
        env = captured["env"]
        check("google-flow recibe FLOW_CDP_PORT",
              env.get("FLOW_CDP_PORT") == "9333", env.get("FLOW_CDP_PORT"))
        check("google-flow recibe GOOGLE_PROFILE_GLOBAL (sesión compartida)",
              env.get("GOOGLE_PROFILE_GLOBAL") == str(prof), env.get("GOOGLE_PROFILE_GLOBAL"))
        check("google-flow recibe alias FLOW_USER_DATA_DIR",
              env.get("FLOW_USER_DATA_DIR") == str(prof), env.get("FLOW_USER_DATA_DIR"))
        # setdefault: si el usuario ya fijó la var, no se pisa
        os.environ["GOOGLE_PROFILE_GLOBAL"] = "/ya/fijado/por/usuario"
        conn2 = await m._spawn("google-flow")
        check("setdefault respeta el valor del entorno del usuario",
              captured["env"].get("GOOGLE_PROFILE_GLOBAL") == "/ya/fijado/por/usuario",
              captured["env"].get("GOOGLE_PROFILE_GLOBAL"))
        os.environ.pop("GOOGLE_PROFILE_GLOBAL", None)
        for t in (conn._reader, conn._stderr, conn2._reader, conn2._stderr):
            if t:
                t.cancel()
        conn3 = await m._spawn("notebooklm")
        check("notebooklm NO recibe el perfil global por este camino",
              "GOOGLE_PROFILE_GLOBAL" not in captured["env"]
              and "FLOW_USER_DATA_DIR" not in captured["env"],
              {k: v for k, v in captured["env"].items() if "PROFILE" in k or "USER_DATA" in k})
        for t in (conn3._reader, conn3._stderr):
            if t:
                t.cancel()
    finally:
        mcpm.asyncio.create_subprocess_exec = orig_exec
        r()


# ─────────────────────── S8 · endpoints HTTP ──
class FakeLoginManager:
    """Sustituto del manager para los endpoints /api/mcp/login-google."""

    def __init__(self, launch=None, status=None, capture=None):
        self._launch = launch
        self.launch_urls = None
        self._status = status or {"cdp_port": 9333, "chrome_up": False,
                                  "profile_dir": "/tmp/prof",
                                  "profile_exists": True,
                                  "flow_cdp_port": 9333,
                                  "shared_with_flow": True,
                                  "notebooklm_storage": {"paths": [], "active": "",
                                                         "exists": False,
                                                         "size_bytes": 0, "mtime": 0.0}}
        self._capture = capture

    async def launch_google_login(self, urls=None):
        self.launch_urls = list(urls or [])
        if isinstance(self._launch, mcpm.MCPManagerError):
            raise self._launch
        return self._launch or {"ok": True, "already_up": False, "pid": 123,
                                "cdp_port": 9333, "profile_dir": "/tmp/prof",
                                "login_url": "https://accounts.google.com/",
                                "pages": self.launch_urls,
                                "notebooklm_storage": self._status["notebooklm_storage"]}

    async def google_login_status(self):
        return self._status

    async def capture_google_session(self):
        if isinstance(self._capture, mcpm.MCPManagerError):
            raise self._capture
        return self._capture or {"ok": True, "cookies": 12,
                                 "storage_paths": ["/x/storage_state.json"],
                                 "chrome_up": True, "cdp_port": 9333}


async def endpoint_tests():
    print("\n── S8 · endpoints HTTP login-google / capture-google-session ──")
    import httpx
    import main as _main
    from services import mcp_manager as mcpm_mod

    orig_mgr = mcpm_mod.manager
    try:
        mcpm_mod.manager = FakeLoginManager()
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            # INT-026 · «Vincular Sesión Google (Login Único)»
            r = await c.post("/api/mcp/launch-auth-browser", json={},
                             headers={"Origin": "http://testserver"})
            js = r.json()
            _pages = list(getattr(config, "GOOGLE_LOGIN_PAGES", []) or [])
            check("POST /mcp/launch-auth-browser 200 (multi-pestaña)",
                  r.status_code == 200 and js.get("ok")
                  and js.get("pages") == _pages
                  and "flow.google.com" in " ".join(_pages), r.text[:200])
            check("el endpoint pasa GOOGLE_LOGIN_PAGES al manager",
                  mcpm_mod.manager.launch_urls == _pages,
                  (mcpm_mod.manager.launch_urls, _pages))
            mcpm_mod.manager = FakeLoginManager(
                launch=mcpm.MCPManagerError("no hay chrome", "CHROME_NOT_FOUND"))
            r = await c.post("/api/mcp/launch-auth-browser", json={},
                             headers={"Origin": "http://testserver"})
            check("launch-auth-browser con Chrome ausente → 502 [CHROME_NOT_FOUND]",
                  r.status_code == 502 and "[CHROME_NOT_FOUND]" in r.text,
                  r.text[:160])
            mcpm_mod.manager = FakeLoginManager()
            r = await c.post("/api/mcp/login-google", json={},
                             headers={"Origin": "http://testserver"})
            js = r.json()
            check("POST /mcp/login-google 200 con pid+perfil",
                  r.status_code == 200 and js.get("ok") and js.get("pid") == 123
                  and js.get("profile_dir"), r.text[:200])
            r = await c.get("/api/mcp/login-google",
                            headers={"Origin": "http://testserver"})
            js = r.json()
            check("GET /mcp/login-google 200 con estado completo",
                  r.status_code == 200 and {"chrome_up", "cdp_port", "shared_with_flow",
                                            "notebooklm_storage"} <= set(js), r.text[:200])
            mcpm_mod.manager = FakeLoginManager(capture={"ok": True, "cookies": 5,
                                                         "storage_paths": ["/p/s.json"]})
            r = await c.post("/api/mcp/capture-google-session", json={},
                             headers={"Origin": "http://testserver"})
            js = r.json()
            check("POST /mcp/capture-google-session 200",
                  r.status_code == 200 and js.get("cookies") == 5, r.text[:200])
            for err, label in (
                    (mcpm.MCPManagerError("no hay chrome", "CHROME_NOT_FOUND"),
                     "CHROME_NOT_FOUND"),
                    (mcpm.MCPManagerError("chrome abajo", "CHROME_NOT_UP"),
                     "CHROME_NOT_UP"),
                    (mcpm.MCPManagerError("sin cookies", "NO_GOOGLE_COOKIES"),
                     "NO_GOOGLE_COOKIES")):
                mcpm_mod.manager = FakeLoginManager(launch=err, capture=err)
                r = await c.post("/api/mcp/login-google", json={},
                                 headers={"Origin": "http://testserver"})
                r2 = await c.post("/api/mcp/capture-google-session", json={},
                                  headers={"Origin": "http://testserver"})
                check(f"502 [{label}] estable en login y capture",
                      r.status_code == 502 and f"[{label}]" in r.text
                      and r2.status_code == 502 and f"[{label}]" in r2.text,
                      (r.status_code, r2.status_code))
    finally:
        mcpm_mod.manager = orig_mgr


# ─────────────────────────────── S9 · contrato UI ──
def ui_tests():
    print("\n── S9 · contrato UI (sesión unificada + dropdown auto; v≥2.25.0 INT-028) ──")
    static = BACKEND / "static"
    appjs = (static / "app.js").read_text(encoding="utf-8")
    index = (static / "index.html").read_text(encoding="utf-8")
    for sym in ("mcpGsessHTML", "gsessLogin", "gsessCapture", "gsessRefresh",
                "gsessApply", "mcpPopulateNotebooks", "gsess-card"):
        check(f"app.js define {sym}", sym in appjs)
    check("dropdown de notebooks dinámico presente (#nblm-nid-sel)",
          'id="nblm-nid-sel"' in appjs)
    _mc = appjs[appjs.index("async function mcpConnect"):
                appjs.index("async function mcpDisconnect")]
    check("auto-listado al conectar notebooklm (silent, dentro de mcpConnect)",
          "st.state === 'connected'" in _mc
          and "mcpListNotebooks({ silent: true })" in _mc, _mc[:400])
    check("el input #nblm-nid sigue siendo la fuente de pipeRun (regresión)",
          "const nid = mcpNid();" in appjs and 'id="nblm-nid"' in appjs)
    check("botones login/captura presentes",
          "🔑 Vincular Sesión Google (Login Único)" in appjs
          and "📥 Capturar sesión → NotebookLM" in appjs)
    check("tooltip helper del mandato presente",
          "abrir el navegador con tu perfil unificado" in appjs
          and "inicia sesión en Google una sola vez" in appjs
          and "Refrescar estado" in appjs)
    check("endpoint launch-auth-browser invocado por la UI",
          "/mcp/launch-auth-browser" in appjs
          and appjs.index("gsessLogin") < appjs.index("/mcp/launch-auth-browser"))
    check("tras vincular: refresco de badges MCP (pre-flight green)",
          "mcpRefresh(true)" in appjs[appjs.index("async function gsessLogin"):
                                       appjs.index("async function gsessCapture")])
    check("endpoint del backend invocado por la UI",
          "/mcp/login-google" in appjs and "/mcp/capture-google-session" in appjs)
    check("index.html sirve app.js v2.25.0 (INT-028 rebrand)",
          "app.js?v=2.25.0" in index)
    check("fin del copy-paste: placeholder sin «pegar UUID» obligatorio",
          "conecta NotebookLM para listar los tuyos" in appjs)


def main() -> int:
    print("=" * 60)
    print("BATERÍA INT-025 · sesión Google unificada + auto-dropdown")
    print("=" * 60)
    config_tests()
    chrome_bin_tests()
    asyncio.run(launch_tests())
    storage_paths_tests()
    asyncio.run(capture_tests())
    asyncio.run(status_tests())
    asyncio.run(spawn_env_tests())
    asyncio.run(endpoint_tests())
    ui_tests()
    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
