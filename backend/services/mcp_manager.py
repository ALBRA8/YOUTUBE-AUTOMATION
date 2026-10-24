"""
YOUTUBE AUTOMATION v2.21 — MCP Client Manager (INT-022)
Puente del Panel de Control hacia servidores MCP stdio externos.

El panel (navegador) no puede hablar stdio con un servidor MCP: este módulo
actúa como CLIENTE MCP persistente en el backend y expone estado/acciones
consumibles por REST (endpoints en main.py §INT-022).

Servicios soportados:
  google-flow : tools/GoogleFlowMCP (node src/mcp.js) — usa Chrome DEDICADO
                con CDP persistente (FLOW_CDP_PORT + user-data-dir propio de
                la herramienta); Chrome sobrevive al proceso, así que la
                sesión de Google persiste entre ejecuciones (§2 del mandato).
  notebooklm  : servidor `notebooklm-mcp` (uv tool install "notebooklm-py[browser]")
                — sesión vía storage_state.json (0600) en NOTEBOOKLM_HOME;
                el expirar de cookies se detecta en preflight → AUTH_REQUIRED.

Framing: JSON-RPC 2.0 delimitado por saltos de línea — el mismo que usa
flow_mcp_client (no se toca, sigue sirviendo al orquestador) y el transporte
stdio estándar de MCP.

Hermeticidad de baterías: toda dependencia externa pasa por métodos
parcheables (_cdp_up / _resolve_command / _spawn); los tests usan
tests/fixtures/fake_mcp_server.py (subprocess local, cero red real).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib import request as _urlreq

import config

log = logging.getLogger("mcp_manager")

SERVICES = ("google-flow", "notebooklm")

# Estados canónicos que pinta el panel (§4 del mandato):
ST_DISCONNECTED = "disconnected"      # gris
ST_CONNECTING = "connecting"          # amarillo
ST_CONNECTED = "connected"            # verde (conectado y autenticado)
ST_AUTH_REQUIRED = "auth_required"    # rojo (auth/sesión)
ST_ERROR = "error"                    # rojo (fallo técnico)

_PROTO = "2024-11-05"
_NOTEBOOK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$")
_AUTHISH_RE = re.compile(r"not signed in|auth|sign[- ]?in|login|cookie|credential|unauthor|401|403", re.I)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Tools de listado del servidor NotebookLM MCP (HOTFIX INT-023.4): no requieren
# notebook_id y son la fuente del auto-descubrimiento / dropdown del panel.
_LIST_NOTEBOOK_TOOLS = ("notebook_list", "list_notebooks")


def parse_notebook_list(text: str) -> list[dict]:
    """Parsea la respuesta de la tool de listado de notebooks (tolerante).
    Acepta JSON (lista de dicts, dict con key notebooks/items), líneas con
    UUID estándar, URLs /notebook/<id> y viñetas con título. Devuelve
    [{'id', 'title'}, …] sin duplicados y solo con ids que pasan el patrón
    canónico (_NOTEBOOK_ID_RE) — el mismo que valida execute()."""
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def _add(nid: str, title: str) -> None:
        nid = (nid or "").strip()
        if nid and nid not in seen and _NOTEBOOK_ID_RE.match(nid):
            seen.add(nid)
            out.append({"id": nid,
                        "title": re.sub(r"[\s\-—–|,;:]+$", "",
                                        (title or "").strip())[:120]})

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        data = None
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                nid = str(it.get("id") or it.get("notebook_id")
                          or it.get("notebookId") or "")
                _add(nid, str(it.get("title") or it.get("name")
                              or it.get("display_name") or ""))
            elif isinstance(it, str):
                m = _UUID_RE.search(it)
                if m:
                    _add(m.group(0), it[:m.start()].strip(" -*•—–:|("))
        return out
    if isinstance(data, dict):
        items = data.get("notebooks") or data.get("items") or []
        if isinstance(items, list):
            return parse_notebook_list(json.dumps(items, ensure_ascii=False))

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _UUID_RE.search(line)
        if m:
            _add(m.group(0), line[:m.start()].strip(" -*•—–:|("))
            continue
        m2 = re.search(r"/notebook/([A-Za-z0-9][A-Za-z0-9_\-]{5,63})", line)
        if m2:
            _add(m2.group(1), line[:m2.start()].strip(" -*•—–:|("))
    return out


class MCPManagerError(Exception):
    """Error operacional del gestor con código estable para la UI."""

    def __init__(self, msg: str, code: str = "MCP_ERROR"):
        super().__init__(msg)
        self.code = code


def _cfg(name: str, default: Any) -> Any:
    return getattr(config, name, default)


# ──────────────────────────────── conexión individual ──
class _Conn:
    """Una conexión stdio viva con un servidor MCP."""

    def __init__(self, service: str):
        self.service = service
        self.state = ST_CONNECTING
        self.proc: asyncio.subprocess.Process | None = None
        self.server_info: dict = {}
        self.tools: list[dict] = []
        self.auth: str = "unknown"          # ok | auth_required | unknown
        self.auth_detail: str = ""
        self.last_error: str = ""
        self.connected_at: float = 0.0
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._wlock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._stderr: asyncio.Task | None = None
        self.stderr_tail: deque[str] = deque(maxlen=40)

    # ── E/S de bajo nivel ──
    async def _send(self, payload: dict) -> None:
        if not self.proc or self.proc.stdin is None or self.proc.stdin.is_closing():
            raise MCPManagerError("proceso del servidor MCP no disponible", "PROCESS_DEAD")
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._wlock:
            self.proc.stdin.write(line)
            await self.proc.stdin.drain()

    async def _request(self, method: str, params: dict | None = None,
                       timeout: float = 30.0) -> dict:
        rid = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                              "params": params or {}})
            msg = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise MCPManagerError(
                f"timeout de {timeout:.0f}s en {method}", "TIMEOUT")
        finally:
            self._pending.pop(rid, None)
        if "error" in msg:
            err = msg["error"]
            detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise MCPManagerError(f"{method}: {detail}", "RPC_ERROR")
        return msg.get("result", {})

    def _on_line(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("[%s] línea no-JSON ignorada: %.120s", self.service, raw)
            return
        rid = msg.get("id")
        if isinstance(rid, int) and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                fut.set_result(msg)

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            self._on_line(line.decode("utf-8", errors="replace").strip())

    async def _stderr_loop(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            chunk = await self.proc.stderr.readline()
            if not chunk:
                break
            self.stderr_tail.append(chunk.decode("utf-8", errors="replace").rstrip())

    # ── ciclo de vida ──
    async def handshake(self) -> None:
        init = await self._request("initialize", {
            "protocolVersion": _PROTO,
            "capabilities": {},
            "clientInfo": {"name": "yta-mcp-manager", "version": "2.21.0"},
        }, timeout=30.0)
        self.server_info = dict(init.get("serverInfo") or {})
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = await self._request("tools/list", {}, timeout=30.0)
        self.tools = list(tools.get("tools") or [])
        self.connected_at = time.time()

    async def call(self, tool: str, arguments: dict, timeout: float) -> str:
        result = await self._request("tools/call", {"name": tool, "arguments": arguments},
                                     timeout=timeout)
        if result.get("isError"):
            content = result.get("content") or []
            text = content[0].get("text", "error de herramienta") if content else "error de herramienta"
            raise MCPManagerError(text, "TOOL_ERROR")
        content = result.get("content") or []
        return content[0].get("text", "") if content else ""

    async def close(self) -> None:
        for t in (self._reader, self._stderr):
            if t and not t.done():
                t.cancel()
        if self.proc:
            try:
                if self.proc.stdin and not self.proc.stdin.is_closing():
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


# ──────────────────────────────── gestor ──
class MCPClientManager:
    """Supervisor de conexiones MCP stdio (una por servicio)."""

    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._lifecycle = asyncio.Lock()  # serializa connect/disconnect entre requests

    # ── resolvers parcheables (hermeticidad) ──
    def _resolve_command(self, service: str) -> tuple[list[str], str | None]:
        """Devuelve (argv, cwd). Lanza MCPManagerError con causa precisa."""
        if service == "google-flow":
            entry = _cfg("FLOW_MCP_DIR", config.BASE_DIR.parent / "tools" / "GoogleFlowMCP")
            entry = entry / "src" / "mcp.js"
            if not entry.is_file():
                raise MCPManagerError(
                    f"no existe {entry} — clona/instala GoogleFlowMCP y ajusta FLOW_MCP_DIR",
                    "ENTRY_MISSING")
            node = shutil.which("node") or (
                r"C:\Program Files\nodejs\node.exe"
                if os.path.isfile(r"C:\Program Files\nodejs\node.exe") else None)
            if not node:
                raise MCPManagerError("binario 'node' no encontrado (GoogleFlowMCP lo requiere)",
                                      "NODE_MISSING")
            return [node, str(entry)], str(_cfg("FLOW_MCP_DIR", entry.parent.parent))
        # notebooklm
        cmd = str(_cfg("NOTEBOOKLM_MCP_CMD", "notebooklm-mcp") or "notebooklm-mcp")
        argv = shlex.split(cmd, posix=(os.name != "nt"))
        exe = argv[0]
        needs_which = not (os.sep in exe or "/" in exe)
        if needs_which and not shutil.which(exe):
            raise MCPManagerError(
                f"'{exe}' no está en PATH — instala con: uv tool install "
                "\"notebooklm-py[browser]\" (o ajusta NOTEBOOKLM_MCP_CMD)",
                "CMD_MISSING")
        return argv, None

    @staticmethod
    async def _cdp_up(port: int) -> bool:
        """¿Hay un Chrome con CDP vivo en 127.0.0.1:<port>? (hermético: parcheable)"""
        def _probe() -> bool:
            try:
                with _urlreq.urlopen(
                        f"http://127.0.0.1:{port}/json/version", timeout=2.0) as r:
                    return r.status == 200
            except Exception:
                return False
        return await asyncio.to_thread(_probe)

    async def _spawn(self, service: str) -> _Conn:
        argv, cwd = self._resolve_command(service)
        env = dict(os.environ)
        if service == "google-flow":
            # §2 mandato: puerto/directorio de sesión explícitos y coherentes
            env.setdefault("FLOW_CDP_PORT", str(_cfg("FLOW_CDP_PORT", 9333)))
            # INT-025 sesión unificada: expone el perfil global al bridge —
            # si su chrome.js soporta un user-data-dir custom lo usa y con
            # esto Flow comparte el MISMO perfil Chrome del login humano.
            gpg = str(_cfg("GOOGLE_PROFILE_GLOBAL", "") or "")
            if gpg:
                env.setdefault("GOOGLE_PROFILE_GLOBAL", gpg)
                env.setdefault("FLOW_USER_DATA_DIR", gpg)
        else:
            home = str(_cfg("NOTEBOOKLM_HOME", "") or "").strip()
            if home:
                env["NOTEBOOKLM_HOME"] = home
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            raise MCPManagerError(f"no se pudo lanzar {argv[0]}: {e}", "SPAWN_FAILED")
        conn = _Conn(service)
        conn.proc = proc
        conn._reader = asyncio.create_task(conn._read_loop())
        conn._stderr = asyncio.create_task(conn._stderr_loop())
        return conn

    # ── API pública ──
    async def connect(self, service: str, notebook_id: str | None = None) -> dict:
        if service not in SERVICES:
            raise MCPManagerError("servicio desconocido", "BAD_SERVICE")
        async with self._lifecycle:
            old = self._conns.get(service)
            if old and old.state == ST_CONNECTED and old.proc and old.proc.returncode is None:
                st = self._conn_status(old)
                st["already_connected"] = True
                return st
            if old:
                await old.close()
                self._conns.pop(service, None)
            conn = await self._spawn(service)
            self._conns[service] = conn
            try:
                await conn.handshake()
            except MCPManagerError as e:
                conn.state = ST_ERROR
                conn.last_error = str(e)
                await conn.close()
                self._conns.pop(service, None)
                raise
            conn.state = ST_CONNECTED
            # preflight de sesión (§2): nunca lanza — degrada a auth_required
            await self._preflight(conn, notebook_id)
            st = self._conn_status(conn)
            log.info("[%s] conectado: %s · %d tools · auth=%s",
                     service, conn.server_info.get("name"), len(conn.tools), conn.auth)
            return st

    async def disconnect(self, service: str) -> dict:
        if service not in SERVICES:
            raise MCPManagerError("servicio desconocido", "BAD_SERVICE")
        async with self._lifecycle:
            conn = self._conns.pop(service, None)
            if conn:
                await conn.close()
            return {"service": service, "state": ST_DISCONNECTED}

    async def status(self) -> dict:
        out: dict[str, dict] = {}
        for svc in SERVICES:
            conn = self._conns.get(svc)
            if conn and conn.proc and conn.proc.returncode is not None:
                conn.state = ST_ERROR
                conn.last_error = (conn.last_error or
                                   f"el proceso terminó (rc={conn.proc.returncode})")
            out[svc] = self._conn_status(conn) if conn else {
                "service": svc, "state": ST_DISCONNECTED, "auth": "unknown",
                "tools": [], "server_info": {}, "last_error": ""}
            out[svc].update(await self._availability(svc))
        return {"services": out}

    async def execute(self, service: str, tool: str, arguments: dict | None,
                      timeout: float | None = None,
                      notebook_id: str | None = None,
                      auto_connect: bool = True) -> dict:
        if service not in SERVICES:
            raise MCPManagerError("servicio desconocido", "BAD_SERVICE")
        arguments = dict(arguments or {})
        allow = self._allowed_tools(service)
        if allow is not None and tool not in allow:
            raise MCPManagerError(
                f"tool '{tool}' fuera de la allowlist de {service} "
                f"({', '.join(sorted(allow))})", "TOOL_NOT_ALLOWED")
        warn: list[str] = []
        if service == "notebooklm":
            id_key = str(_cfg("NOTEBOOKLM_ID_KEY", "notebook_id") or "notebook_id")
            nid = arguments.get(id_key) or notebook_id or str(_cfg("NOTEBOOKLM_NOTEBOOK_ID", "") or "").strip()
            if nid:
                if not _NOTEBOOK_ID_RE.match(nid):
                    raise MCPManagerError(
                        f"notebook_id inválido: '{nid[:24]}' (patrón {id_key})", "INVALID_NOTEBOOK_ID")
                arguments[id_key] = nid            # §3: inyección dinámica
            elif tool in _LIST_NOTEBOOK_TOOLS or tool == str(
                    _cfg("NOTEBOOKLM_PROBE_TOOL", "list_notebooks") or "").strip():
                warn.append(f"notebook_id ausente; '{tool}' es de listado y no lo necesita")
            else:
                # HOTFIX INT-023.4 + INT-025: fallo DETERMINISTA con código
                # estable en vez del TOOL_ERROR críptico del servidor.
                raise MCPManagerError(
                    f"la tool '{tool}' requiere notebook_id y está ausente "
                    f"(arguments['{id_key}'], payload y .env NOTEBOOKLM_NOTEBOOK_ID "
                    f"vacíos). Conecta NotebookLM en el panel y elige tu notebook "
                    f"del dropdown «Notebook activo» (se rellena solo al conectar); "
                    f"si la sesión Google no es válida usa «🔑 Vincular Sesión "
                    f"Google (Login Único)» + «📥 Capturar sesión».",
                    "MISSING_NOTEBOOK_ID")
        conn = self._conns.get(service)
        if not conn or conn.state != ST_CONNECTED or not conn.proc or conn.proc.returncode is not None:
            if not auto_connect:
                raise MCPManagerError(f"{service} no está conectado", "DISCONNECTED")
            await self.connect(service)
            conn = self._conns.get(service)
            if not conn or conn.state != ST_CONNECTED:
                raise MCPManagerError(f"{service} no se pudo conectar", "DISCONNECTED")
        names = {t.get("name") for t in conn.tools}
        if names and tool not in names:
            raise MCPManagerError(
                f"el servidor no expone '{tool}' (tools: {', '.join(sorted(n for n in names if n))})",
                "TOOL_UNKNOWN")
        t0 = time.time()
        try:
            text = await conn.call(tool, arguments, float(
                timeout if timeout is not None else
                (_cfg("NOTEBOOKLM_MCP_TIMEOUT", 60.0) if service == "notebooklm"
                 else _cfg("FLOW_MCP_TIMEOUT", 120.0))))
        except MCPManagerError as e:
            if e.code in ("TIMEOUT", "PROCESS_DEAD"):
                conn.state = ST_ERROR
                conn.last_error = str(e)
                await conn.close()
                self._conns.pop(service, None)
            raise
        log.info("[mcp-exec] %s::%s ok en %.1fs", service, tool, time.time() - t0)
        return {"ok": True, "service": service, "tool": tool, "text": text,
                "elapsed_s": round(time.time() - t0, 2),
                **({"warnings": warn} if warn else {})}

    async def test_pipeline(self, service: str, notebook_id: str | None = None) -> dict:
        """Dry-run §4: conecta (si hace falta), verifica sesión y preparación.
        Nunca genera contenido real."""
        res: dict = {"service": service, "ok": False}
        try:
            st = await self.connect(service, notebook_id=notebook_id)
        except MCPManagerError as e:
            res.update({"state": ST_ERROR, "code": e.code, "detail": str(e)[:280]})
            if service == "google-flow":
                res["browser_up"] = await self._cdp_up(int(_cfg("FLOW_CDP_PORT", 9333)))
            return res
        res.update({"state": st.get("state"), "auth": st.get("auth"),
                    "auth_detail": st.get("auth_detail", ""),
                    "tools": len(st.get("tools") or []),
                    "server": (st.get("server_info") or {}).get("name", "")})
        if service == "google-flow":
            res["browser_up"] = await self._cdp_up(int(_cfg("FLOW_CDP_PORT", 9333)))
            res["cdp_port"] = int(_cfg("FLOW_CDP_PORT", 9333))
        nid = (notebook_id or str(_cfg("NOTEBOOKLM_NOTEBOOK_ID", "") or "").strip())
        if service == "notebooklm":
            if nid:
                res["notebook_id"] = nid
                res["notebook_id_valid"] = bool(_NOTEBOOK_ID_RE.match(nid))
            else:
                res["notebook_id_valid"] = False
                res["notebook_id"] = ""
        res["ok"] = (res.get("state") == ST_CONNECTED
                     and res.get("auth") == "ok"
                     and (service != "google-flow" or res.get("browser_up")))
        return res

    # ── notebook discovery (HOTFIX INT-023.4) ──
    async def list_notebooks(self, notebook_id: str | None = None) -> dict:
        """Lista los notebooks de la cuenta vía la tool de listado del MCP
        (notebook_list / list_notebooks). Alimenta el dropdown «📋 Listar mis
        Notebooks» del panel y el auto-descubrimiento del pre-flight."""
        conn = self._conns.get("notebooklm")
        if (not conn or conn.state != ST_CONNECTED or not conn.proc
                or conn.proc.returncode is not None):
            await self.connect("notebooklm", notebook_id=notebook_id)
            conn = self._conns.get("notebooklm")
            if not conn or conn.state != ST_CONNECTED:
                raise MCPManagerError("notebooklm no se pudo conectar", "DISCONNECTED")
        names = {t.get("name") for t in conn.tools}
        probe = str(_cfg("NOTEBOOKLM_PROBE_TOOL", "list_notebooks") or "").strip()
        candidates = [t for t in _LIST_NOTEBOOK_TOOLS if t in names]
        if probe and probe in names and probe not in candidates:
            candidates.append(probe)
        if not candidates:
            raise MCPManagerError(
                "el servidor no expone tool de listado de notebooks "
                f"(esperaba {', '.join(_LIST_NOTEBOOK_TOOLS)})", "TOOL_UNKNOWN")
        last_err: MCPManagerError | None = None
        for t in candidates:
            try:
                text = await conn.call(t, {}, timeout=25.0)
            except MCPManagerError as e:
                if _AUTHISH_RE.search(str(e)):
                    raise MCPManagerError(
                        f"sesión Google no válida al listar notebooks: {e}",
                        "AUTH_REQUIRED") from e
                last_err = e
                continue
            nbs = parse_notebook_list(text)
            if nbs:
                return {"ok": True, "tool": t, "notebooks": nbs,
                        "first_id": nbs[0]["id"]}
        raise MCPManagerError(
            "listado de notebooks vacío o ilegible"
            + (f" ({last_err})" if last_err else ""), "LIST_EMPTY")

    async def discover_notebook_id(self) -> str:
        """Primer notebook_id disponible ("" si no hay — NUNCA lanza).
        Fallback determinista del pre-flight del orquestador (HOTFIX INT-023.4)."""
        try:
            return str((await self.list_notebooks()).get("first_id") or "")
        except MCPManagerError:
            return ""

    # ── 🔑 sesión Google unificada (INT-025) ──
    # UN login manual humano en un Chrome REAL con user-data-dir compartido
    # (google_profile_global) autentica ambos servidores MCP:
    #   · google-flow  : GoogleFlowMCP hace connectOverCDP al puerto
    #     GOOGLE_LOGIN_CDP_PORT (= FLOW_CDP_PORT) → usa ESTE Chrome/sesión.
    #   · notebooklm   : capture_google_session() extrae las cookies .google.com
    #     del MISMO Chrome por CDP y las escribe en el storage_state.json que
    #     notebooklm-py lee (estructura verificada del wheel 0.8.5:
    #     <home>/profiles/<profile>/storage_state.json, fallback legacy <home>/).
    _CHROME_CANDIDATES: tuple[str, ...] = (
        "google-chrome-stable", "google-chrome", "chrome", "chromium",
        "chromium-browser", "microsoft-edge", "brave-browser")

    def _find_chrome_bin(self) -> str:
        """Binario Chrome real para el login humano (parcheable en tests vía
        MCP_LOGIN_CHROME_BIN / shutil.which)."""
        override = str(_cfg("MCP_LOGIN_CHROME_BIN", "") or "").strip()
        if override:
            if os.path.isfile(override) or shutil.which(override):
                return override
            raise MCPManagerError(
                f"MCP_LOGIN_CHROME_BIN='{override}' no existe en esta máquina",
                "CHROME_NOT_FOUND")
        for cand in self._CHROME_CANDIDATES:
            w = shutil.which(cand)
            if w:
                return w
        # rutas típicas de escritorio (Windows / macOS)
        import platform
        if platform.system() == "Windows":
            pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
            lapp = os.environ.get("LOCALAPPDATA", "")
            for p in (
                    rf"{pf}\Google\Chrome\Application\chrome.exe",
                    rf"{pf86}\Google\Chrome\Application\chrome.exe",
                    rf"{lapp}\Google\Chrome\Application\chrome.exe",
                    rf"{pf}\Microsoft\Edge\Application\msedge.exe",
                    rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe"):
                if os.path.isfile(p):
                    return p
        elif platform.system() == "Darwin":
            for p in (
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                    "/Applications/Chromium.app/Contents/MacOS/Chromium"):
                if os.path.isfile(p):
                    return p
        raise MCPManagerError(
            "no se encontró Chrome/Chromium/Edge/Brave en esta máquina — "
            "instala Google Chrome o fija MCP_LOGIN_CHROME_BIN en backend/.env",
            "CHROME_NOT_FOUND")

    def _spawn_chrome(self, argv: list[str]) -> int:
        """Lanza el Chrome de login DESACOPLADO del backend (parcheable):
        start_new_session → sobrevive al reinicio de uvicorn; el perfil
        compartido hace el resto (Chrome singleton reenvía a la instancia
        viva si ya existía). Devuelve el pid."""
        import sys
        if sys.platform == "win32":
            chrome = argv[0]
            cmd_parts = [f'"{chrome}"']
            for a in argv[1:]:
                if a.startswith("--user-data-dir="):
                    val = a[len("--user-data-dir="):].strip('"')
                    cmd_parts.append(f'--user-data-dir="{val}"')
                elif " " in a and not (a.startswith('"') and a.endswith('"')):
                    cmd_parts.append(f'"{a}"')
                else:
                    cmd_parts.append(a)
            full_cmd = 'start "" ' + " ".join(cmd_parts)
            log.info("[mcp] Lanzando Chrome en Windows via start: %s", full_cmd)
            return subprocess.Popen(full_cmd, shell=True).pid
        return subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True).pid

    def _nb_storage_paths(self) -> list[Path]:
        """Rutas candidatas del storage_state.json de notebooklm-py, en orden
        de precedencia (verificada en el wheel 0.8.5 — paths.py):
        1) <home>/profiles/<profile>/storage_state.json  (estructura moderna)
        2) <home>/storage_state.json                     (fallback legacy del
           perfil 'default'). Nota: el paquete MIGRA legacy→profiles/default
           al arrancar, por eso si preexistía legacy escribimos legacy."""
        home = Path(str(_cfg("NOTEBOOKLM_HOME", "") or "").strip() or
                    Path.home() / ".notebooklm")
        profile = (str(_cfg("NOTEBOOKLM_PROFILE", "") or "").strip()
                   or "default")
        return [home / "profiles" / profile / "storage_state.json",
                home / "storage_state.json"]

    def nb_storage_state(self) -> dict:
        """Estado del storage_state.json de notebooklm-py (para la UI)."""
        paths = self._nb_storage_paths()
        existing = next((p for p in paths if p.is_file()), None)
        return {"paths": [str(p) for p in paths],
                "active": str(existing) if existing else "",
                "exists": existing is not None,
                "size_bytes": existing.stat().st_size if existing else 0,
                "mtime": existing.stat().st_mtime if existing else 0.0}

    async def launch_google_login(self, urls: list[str] | None = None, cdp: bool = True) -> dict:
        """🔑 Abre (o reutiliza) el Chrome REAL con el perfil global y la URL
        de login de Google. UNA vez el humano loguea: Flow hereda la sesión
        (mismo Chrome por CDP) y NotebookLM la captura («📥 Capturar sesión»).
        urls: pestañas a abrir (default = [GOOGLE_LOGIN_URL]). El endpoint
        «Vincular Sesión Google (Login Único)» pasa flow.google.com +
        notebooklm.google.com para que el único login cubra ambos products."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        profile = Path(str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        profile.mkdir(parents=True, exist_ok=True)
        pages = [u.strip() for u in (urls or []) if u and u.strip()] or [
            str(_cfg("GOOGLE_LOGIN_URL", "https://accounts.google.com/"))]
        already_up = await self._cdp_up(port) if cdp else False
        pid = None
        if not already_up:
            chrome = self._find_chrome_bin()
            argv = [chrome,
                    f"--user-data-dir={profile}",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-session-crashed-bubble"]
            if cdp:
                argv.insert(2, f"--remote-debugging-port={port}")
            argv += pages
            try:
                pid = self._spawn_chrome(argv)
            except OSError as e:
                raise MCPManagerError(f"no se pudo lanzar Chrome: {e}",
                                      "CHROME_SPAWN_FAILED") from e
        else:
            import httpx
            for p_url in pages:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.put(f"http://127.0.0.1:{port}/json/new?{p_url}", timeout=2.0)
                except Exception:
                    pass
        st = self.nb_storage_state()
        return {"ok": True, "already_up": already_up, "pid": pid,
                "cdp_port": port,
                "profile_dir": str(profile),
                "login_url": pages[0],
                "pages": pages,
                "notebooklm_storage": st}

    async def google_login_status(self) -> dict:
        """Estado de la sesión unificada (polling barato de la UI)."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        profile = Path(str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        out = {"cdp_port": port,
               "chrome_up": await self._cdp_up(port),
               "profile_dir": str(profile),
               "profile_exists": profile.is_dir(),
               "flow_cdp_port": int(_cfg("FLOW_CDP_PORT", 9333)),
               "shared_with_flow": port == int(_cfg("FLOW_CDP_PORT", 9333)),
               "notebooklm_storage": self.nb_storage_state()}
        return out

    async def _cdp_fetch_google_cookies_impl(self, port: int) -> list[dict]:
        """Extrae cookies de dominios Google del Chrome de login vía
        Playwright connectOverCDP (import diferido: solo existe en máquinas
        con notebooklm-py[browser] — en el sandbox se parchea). Corre en
        thread porque Playwright sync no puede vivir en el loop del backend."""
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        def _job() -> list[dict]:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}")
                try:
                    cookies: list[dict] = []
                    for ctx in browser.contexts:
                        for c in ctx.cookies():
                            cookies.append({
                                "name": c.get("name", ""),
                                "value": c.get("value", ""),
                                "domain": c.get("domain", ""),
                                "path": c.get("path", "/"),
                                "expires": c.get("expires", -1),
                                "httpOnly": bool(c.get("httpOnly", False)),
                                "secure": bool(c.get("secure", False)),
                            })
                    return cookies
                finally:
                    browser.close()
        return await asyncio.to_thread(_job)

    @staticmethod
    def _filter_google_cookies(cookies: list[dict]) -> list[dict]:
        """Solo cookies de dominios Google con name+value+domain (el
        storage_state de Playwright exige esas tres claves)."""
        out: list[dict] = []
        seen: set[tuple] = set()
        for c in cookies or []:
            dom = str(c.get("domain") or "")
            if "google.com" not in dom and "gstatic.com" not in dom:
                continue
            if not (c.get("name") and c.get("value") and dom):
                continue
            key = (c["name"], dom, c.get("path", "/"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": c["name"], "value": c["value"],
                        "domain": dom, "path": c.get("path", "/"),
                        "expires": c.get("expires", -1),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "secure": bool(c.get("secure", True))})
        return out

    async def capture_google_session(self) -> dict:
        """📥 Captura las cookies Google del Chrome de login (CDP) y las
        escribe en el storage_state.json de notebooklm-py → el MCP de
        NotebookLM autentica con EL MISMO login que Flow."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        if not await self._cdp_up(port):
            raise MCPManagerError(
                f"el Chrome de login no responde en el puerto CDP {port} — "
                "pulsa primero «🔑 Vincular Sesión Google (Login Único)» "
                "y loguéate",
                "CHROME_NOT_UP")
        try:
            raw = await self._cdp_fetch_google_cookies_impl(port)
        except ImportError as e:
            raise MCPManagerError(
                "Playwright no está disponible en el backend — instala con: "
                'uv tool install "notebooklm-py[browser]" (o pip install '
                "playwright && playwright install chromium)", "PLAYWRIGHT_MISSING") from e
        cookies = self._filter_google_cookies(raw)
        if not cookies:
            raise MCPManagerError(
                "el Chrome de login no tiene cookies de Google todavía — "
                "completa el login humano y reintenta la captura",
                "NO_GOOGLE_COOKIES")
        state = {"cookies": cookies,
                 "origins": [],
                 "captured_at": time.time(),
                 "source": "google_profile_global"}
        paths = self._nb_storage_paths()
        pre = [p for p in paths if p.is_file()]
        targets = pre if pre else paths  # respeta el layout ya existente
        written: list[str] = []
        for p in targets:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                         encoding="utf-8")
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
            written.append(str(p))
        log.info("[google-login] storage_state capturado: %d cookies → %s",
                 len(cookies), ", ".join(written))
        return {"ok": True, "cookies": len(cookies),
                "storage_paths": written,
                "chrome_up": True, "cdp_port": port}


    # ── helpers ──
    def _allowed_tools(self, service: str) -> set[str] | None:
        """None = todas (default documentado en .env.example)."""
        if service == "google-flow":
            return None  # las tools reales ya son flow_* del propio servidor
        raw = [t.strip() for t in str(_cfg("NOTEBOOKLM_MCP_TOOLS", "") or "").split(",")
               if t.strip()]
        return set(raw) or None

    async def _preflight(self, conn: _Conn, notebook_id: str | None) -> None:
        """Verifica sesión Google real ANTES de que el panel dispare nada (§2).
        Cualquier problema → state=auth_required, sin excepción."""
        try:
            if conn.service == "google-flow":
                text = await conn.call("flow_list_assets", {}, timeout=20.0)
                if "not signed in" in text.lower():
                    conn.auth = "auth_required"
                    conn.auth_detail = text.strip()[:200]
                    conn.state = ST_AUTH_REQUIRED
                else:
                    conn.auth = "ok"
            else:
                probe = str(_cfg("NOTEBOOKLM_PROBE_TOOL", "list_notebooks") or "").strip()
                names = {t.get("name") for t in conn.tools}
                if probe and probe in names:
                    try:
                        await conn.call(probe, {}, timeout=25.0)
                        conn.auth = "ok"
                    except MCPManagerError as e:
                        if _AUTHISH_RE.search(str(e)):
                            conn.auth = "auth_required"
                            conn.auth_detail = str(e)[:200]
                            conn.state = ST_AUTH_REQUIRED
                        else:
                            conn.auth = "unknown"
                            conn.auth_detail = f"sonda '{probe}' falló sin patrón de auth: {e}"
                else:
                    conn.auth = "unknown"
                    conn.auth_detail = (f"sonda '{probe}' no está entre las tools del "
                                        f"servidor; auth se verificará al ejecutar")
        except MCPManagerError as e:
            if _AUTHISH_RE.search(str(e)):
                conn.auth = "auth_required"
                conn.auth_detail = str(e)[:200]
                conn.state = ST_AUTH_REQUIRED
            else:
                conn.auth = "unknown"
                conn.auth_detail = f"preflight sin veredicto: {str(e)[:160]}"
        except Exception as e:  # noqa: BLE001 — preflight NUNCA rompe el connect
            conn.auth = "unknown"
            conn.auth_detail = f"preflight sin veredicto: {str(e)[:160]}"

    def _conn_status(self, conn: _Conn | None) -> dict:
        if not conn:
            return {}
        return {
            "service": conn.service, "state": conn.state, "auth": conn.auth,
            "auth_detail": conn.auth_detail, "pid": conn.proc.pid if conn.proc else None,
            "uptime_s": round(time.time() - conn.connected_at, 1) if conn.connected_at else 0.0,
            "server_info": conn.server_info,
            "tools": [{"name": t.get("name"), "description": (t.get("description") or "")[:120]}
                      for t in conn.tools],
            "last_error": conn.last_error,
            "stderr_tail": list(conn.stderr_tail)[-6:],
        }

    async def _availability(self, service: str) -> dict:
        """Pistas de configuración para la UI (sin lanzar procesos)."""
        try:
            argv, _ = self._resolve_command(service)
            ok = bool(shutil.which(argv[0]) or os.path.isfile(argv[0]))
        except MCPManagerError as e:
            return {"available": False, "hint": f"{e.code}: {e}"}
        out: dict = {"available": ok}
        if service == "google-flow":
            out["cdp_port"] = int(_cfg("FLOW_CDP_PORT", 9333))
            out["browser_up"] = await self._cdp_up(out["cdp_port"])
        else:
            out["notebook_id_configured"] = bool(str(_cfg("NOTEBOOKLM_NOTEBOOK_ID", "") or "").strip())
        return out


# Singleton del backend (los endpoints en main.py lo consumen)
manager = MCPClientManager()
