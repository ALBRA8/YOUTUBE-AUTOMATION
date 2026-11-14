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
  notebooklm  : servidor `notebooklm-mcp-server` v0.1.15 (comandos
                `notebooklm-mcp` y `notebooklm-mcp-auth`; `uv tool list`
                lo confirma en la máquina del dueño, U6 2026-11-07).
                OJO: la versión que llega en server_info (p. ej. 2.14.5)
                es la del FRAMEWORK FastMCP, no la del paquete.
                — sesión vía storage_state.json (0600) en NOTEBOOKLM_HOME;
                el expirar de cookies se detecta en preflight → AUTH_REQUIRED
                e intenta UN refresh automático (`notebooklm auth refresh
                --quiet`, INT-069 · gate NLM_AUTH_REFRESH · fail-open).

INT-069 · compat de nombres con notebooklm-py v0.8.5: sus tools declaran el
parámetro `notebook` (no `notebook_id`) y FastMCP rechaza kwargs desconocidos
(ValidationError verificado). execute() espeja la clave legacy `notebook_id`
del §3 → `notebook` SOLO cuando el inputSchema real de la tool lo pide
(_mirror_notebook_arg), de modo que el panel/orquestador siguen enviando
notebook_id sin romper servidores legacy.

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
# Tools de listado del servidor NotebookLM MCP (HOTFIX INT-023.4)
_LIST_NOTEBOOK_TOOLS = ("notebook_list", "list_notebooks")
# AA1 · Herramientas de solo lectura con reintento seguro tras PROCESS_DEAD
RETRYABLE_READ_TOOLS = frozenset({
    "flow_list_assets", "notebook_query", "notebook_list", "notebook_get"
})
# AA1 · Herramientas con mutación/generación que NUNCA deben auto-reintentarse
NON_RETRYABLE_FLOW_TOOLS = frozenset({
    "flow_generate_image", "flow_generate_video", "flow_new_project", "flow_upload_file"
})
# Tools que NO aceptan notebook/notebook_id en absoluto (v0.8.5:
# notebook_create solo toma `title`; usada por el Studio Bridge INT-069).
_NO_NOTEBOOK_TOOLS = frozenset({"notebook_create"})


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


def _auth_refresh_enabled() -> bool:
    """Gate del refresh automático de sesión (INT-069): NLM_AUTH_REFRESH
    default "1"; "0"/"false"/"no" lo desactiva (fail-open por diseño)."""
    return str(_cfg("NLM_AUTH_REFRESH", "1") or "1").strip().lower() in (
        "1", "true", "yes", "on")


def auth_refresh_notebooklm(timeout: float = 90.0) -> tuple[bool, str]:
    """INT-069 · hardening de sesión: ejecuta `notebooklm auth refresh --quiet`
    (CLI del paquete notebooklm-py; verificado en el upstream v0.8.5,
    docs/cli-reference.md líneas 76-77 y sección "Authentication: auth refresh")
    para rotar las cookies del storage_state.json SIN login humano.

    - Subprocess con timeout y captura de stdout/stderr; respeta
      NOTEBOOKLM_HOME / NOTEBOOKLM_PROFILE del .env.
    - NUNCA lanza: devuelve (ok, resumen). ok=True solo con rc==0.
      Cualquier fallo (CLI ausente, OSError, timeout, rc!=0) es un resumen
      legible — fail-open: el llamante sigue igual que sin refresh.
    """
    exe = shutil.which("notebooklm")
    if not exe:
        return False, ("CLI 'notebooklm' no está en PATH (instala con: "
                       "uv tool install \"notebooklm-py[browser]==0.8.5\")")
    argv = [exe, "auth", "refresh", "--quiet"]
    env = dict(os.environ)
    home = str(_cfg("NOTEBOOKLM_HOME", "") or "").strip()
    if home:
        env.setdefault("NOTEBOOKLM_HOME", home)
    profile = str(_cfg("NOTEBOOKLM_PROFILE", "") or "").strip()
    if profile:
        env.setdefault("NOTEBOOKLM_PROFILE", profile)
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, f"timeout de {timeout:.0f}s en {' '.join(argv)}"
    except OSError as e:
        return False, f"no se pudo ejecutar {' '.join(argv)}: {e}"
    if p.returncode == 0:
        out = (p.stdout or "").strip().replace("\n", " · ")
        return True, (out[:160] or "refresh ok (sin salida)")
    detail = ((p.stderr or "") + " " + (p.stdout or "")).strip().replace("\n", " · ")
    return False, f"rc={p.returncode}: {detail[:200]}"


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
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                self._on_line(line.decode("utf-8", errors="replace").strip())
        finally:
            # Resiliencia: si el proceso cierra stdout (EOF) o cae, despertar inmediatamente
            # a todos los futures pendientes con PROCESS_DEAD en vez de esperar el timeout completo de 30s/60s.
            tail = " · ".join(list(self.stderr_tail)[-3:]) if self.stderr_tail else ""
            err_msg = f"el proceso MCP de {self.service} cerró la conexión (EOF)"
            if tail:
                err_msg += f": {tail}"
            for rid, fut in list(self._pending.items()):
                if not fut.done():
                    fut.set_exception(MCPManagerError(err_msg, "PROCESS_DEAD"))

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


# ── INT-071 · Google One-Tap Hub: extracción de cuenta (funciones puras) ──
_ACCOUNT_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ACCOUNT_JUNK_RE = re.compile(r"example|domain\.com|correo\.com|sentry|user@localhost", re.I)


def _account_from_email(email: str) -> dict:
    """Deriva el perfil visible del Hub desde el email: nombre legible
    («johan.bravo» → «Johan Bravo») e inicial para el avatar."""
    local = email.split("@", 1)[0]
    name = re.sub(r"[._\-+]+", " ", local).strip().title()
    return {"email": email,
            "name": name or email,
            "initial": (name[:1] or "G").upper()}


def account_from_html(html: str) -> dict | None:
    """Extrae la cuenta activa del HTML de accounts.google.com
    (SignOutOptions / AccountChooser muestran el email de la sesión).
    Estrategia 2 del Hub · fail-soft: None si no encuentra nada fiable."""
    if not html:
        return None
    emails: list[str] = []
    for m in re.finditer(
            r'(?:data-email=["\']|mailto:)([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',
            html):
        emails.append(m.group(1))
    if not emails:
        emails = [m.group(0) for m in _ACCOUNT_EMAIL_RE.finditer(html)]
    seen: set[str] = set()
    for e in emails:
        k = e.lower()
        if k in seen or _ACCOUNT_JUNK_RE.search(k):
            continue
        seen.add(k)
        return _account_from_email(e)
    return None


def account_from_targets(targets: list[dict]) -> dict | None:
    """Estrategia 1: URLs/títulos de las pestañas del Chrome CDP
    (GET http://127.0.0.1:<port>/json/list). Páginas de Google suelen traer
    el correo en ?authuser= / Email= o en el título de la pestaña.
    Fail-soft: None si no encuentra nada."""
    for t in targets or []:
        blob = f"{t.get('url') or ''} {t.get('title') or ''}"
        m = re.search(
            r"(?:[?&]authuser=|[?&]Email=)([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
            blob)
        email = m.group(1) if m else None
        if not email:
            m2 = _ACCOUNT_EMAIL_RE.search(blob)
            email = m2.group(0) if m2 else None  # regex genérico SIN grupos
        if email:
            k = email.lower()
            if not _ACCOUNT_JUNK_RE.search(k):
                return _account_from_email(email)
    return None


# ──────────────────────────────── gestor ──
class MCPClientManager:
    """Supervisor de conexiones MCP stdio (una por servicio)."""

    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._lifecycle = asyncio.Lock()  # serializa connect/disconnect entre requests
        # INT-071 · Google One-Tap Hub: estado del watcher de login SSO.
        # "task" guarda la referencia fuerte al asyncio task del watchdog
        # (nunca se serializa hacia la UI: los endpoints la omiten).
        self._sso: dict = {"phase": "idle", "started_at": 0.0, "error": "",
                           "account": None, "updated_at": 0.0, "task": None}

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
                "\"notebooklm-py[browser]==0.8.5\" (o ajusta NOTEBOOKLM_MCP_CMD)",
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

    async def tools_catalog(self, service: str, auto_connect: bool = True) -> dict:
        """SOLO LECTURA · catálogo de tools del servicio tal como lo devolvió
        `tools/list` del handshake MCP: {service, server_info,
        tools:[{name, description, inputSchema}]}.

        auto_connect=True (default, vía histórica de la sonda --modo-local):
        conecta si no hay conexión viva.
        auto_connect=False (Y1, endpoint GET /api/mcp/catalogo/{service}):
        NUNCA conecta ni lanza procesos — si el servicio no está conectado
        levanta MCPManagerError NOT_CONNECTED («conecta primero desde el
        panel»). En ambos modos NUNCA ejecuta ninguna tool (la sonda de
        capacidades es quien decide qué hacer con el catálogo)."""
        if service not in SERVICES:
            raise MCPManagerError("servicio desconocido", "BAD_SERVICE")
        conn = self._conns.get(service)
        if not conn or conn.state != ST_CONNECTED:
            if not auto_connect:
                raise MCPManagerError(
                    f"{service}: sin conexión activa (se lee SOLO la conexión "
                    "ya levantada por el backend)", "NOT_CONNECTED")
            await self.connect(service)
            conn = self._conns.get(service)
        if not conn or conn.state != ST_CONNECTED:
            raise MCPManagerError(f"{service}: sin conexión activa",
                                  "NOT_CONNECTED")
        return {
            "service": service,
            "server_info": dict(conn.server_info or {}),
            "tools": [
                {"name": t.get("name"),
                 "description": t.get("description", ""),
                 "inputSchema": dict(t.get("inputSchema") or {})}
                for t in (conn.tools or []) if isinstance(t, dict)
            ],
        }

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
            elif tool in _LIST_NOTEBOOK_TOOLS or tool in _NO_NOTEBOOK_TOOLS or tool == str(
                    _cfg("NOTEBOOKLM_PROBE_TOOL", "notebook_list") or "").strip():
                warn.append(f"notebook_id ausente; '{tool}' no lo necesita "
                            f"(listado/creación)")
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
        t0 = time.time()
        call_timeout = float(
            timeout if timeout is not None else
            (_cfg("NOTEBOOKLM_MCP_TIMEOUT", 60.0) if service == "notebooklm"
             else _cfg("FLOW_MCP_TIMEOUT", 120.0)))

        max_attempts = 2 if auto_connect else 1
        last_exc: Exception | None = None
        text: str = ""

        for attempt in range(1, max_attempts + 1):
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
            if service == "notebooklm":
                # INT-069/069.1: v0.8.5 nombra los parámetros `notebook` (antes
                # notebook_id) y `question` (antes query en la tool de contexto del
                # orquestador); espejar claves legacy según el inputSchema REAL
                # (ver _mirror_notebook_arg / _mirror_query_arg).
                self._mirror_notebook_arg(conn, tool, arguments)
                self._mirror_query_arg(conn, tool, arguments)
            try:
                text = await conn.call(tool, arguments, call_timeout)
                last_exc = None
                break
            except MCPManagerError as e:
                last_exc = e
                if e.code in ("TIMEOUT", "PROCESS_DEAD"):
                    conn.state = ST_ERROR
                    conn.last_error = str(e)
                    await conn.close()
                    self._conns.pop(service, None)
                    # AA1: NUNCA reintentar herramientas que generen o muten en Flow
                    if e.code == "PROCESS_DEAD" and tool in NON_RETRYABLE_FLOW_TOOLS:
                        raise MCPManagerError(
                            "la herramienta pudo ejecutarse; verifica en Flow antes de reintentar",
                            "PROCESS_DEAD",
                        )
                    # AA1: Auto-reintento SOLO para herramientas de lectura seguras
                    if attempt < max_attempts and e.code == "PROCESS_DEAD" and tool in RETRYABLE_READ_TOOLS:
                        log.warning("[%s] proceso cerró la conexión durante call() de lectura '%s'; reintentando una vez...", service, tool)
                        continue
                raise

        if last_exc:
            raise last_exc
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
        probe = str(_cfg("NOTEBOOKLM_PROBE_TOOL", "notebook_list") or "").strip()
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

    @staticmethod
    def heal_chrome_profile(profile_path: Path | str | None = None) -> dict:
        """Sanea el perfil de Chrome (google_profile_global / FlowImageChrome) antes de spawn:
        1. Elimina Local State.bad si existe.
        2. Elimina bloqueos huérfanos: lockfile, SingletonLock, SingletonCookie, SingletonSocket.
        3. Verifica y repara Local State si está dañado o JSON corrupto.
        4. Sanea Default/Preferences: repara JSON corrupto y fuerza exit_type='Normal' y exited_cleanly=True.
        """
        p = Path(profile_path if profile_path else str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        actions: list[str] = []
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
                actions.append("directorio creado")
            except OSError:
                pass
            return {"ok": True, "profile": str(p), "actions": actions}

        # 1. Local State.bad
        bad_ls = p / "Local State.bad"
        if bad_ls.is_file():
            try:
                bad_ls.unlink()
                actions.append("Local State.bad eliminado")
                log.info("[mcp-profile] Local State.bad eliminado en %s", p)
            except OSError as e:
                actions.append(f"error eliminando Local State.bad: {e}")

        # 2. Bloqueos huérfanos
        for lock_name in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock = p / lock_name
            if lock.is_file() or lock.exists():
                try:
                    lock.unlink()
                    actions.append(f"{lock_name} eliminado")
                except OSError as e:
                    actions.append(f"error eliminando {lock_name}: {e}")

        # 3. Local State
        ls = p / "Local State"
        if ls.is_file():
            try:
                content = ls.read_text(encoding="utf-8", errors="ignore")
                json.loads(content)
            except Exception:
                try:
                    ls.unlink()
                    actions.append("Local State corrupto eliminado")
                    log.warning("[mcp-profile] Local State corrupto eliminado en %s", p)
                except OSError as e:
                    actions.append(f"error eliminando Local State corrupto: {e}")

        # 4. Default/Preferences
        pref_file = p / "Default" / "Preferences"
        if pref_file.is_file():
            repaired = False
            try:
                content = pref_file.read_text(encoding="utf-8", errors="ignore")
                prefs = json.loads(content)
                if not isinstance(prefs, dict):
                    prefs = {}
                    repaired = True
            except Exception:
                prefs = {}
                repaired = True

            prof = prefs.setdefault("profile", {})
            if prof.get("exit_type") != "Normal":
                prof["exit_type"] = "Normal"
                repaired = True
            if not prof.get("exited_cleanly"):
                prof["exited_cleanly"] = True
                repaired = True

            if prefs.get("exit_type") and prefs.get("exit_type") != "Normal":
                prefs["exit_type"] = "Normal"
                repaired = True

            if repaired:
                try:
                    pref_file.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
                    actions.append("Default/Preferences saneado (exit_type=Normal, exited_cleanly=true)")
                    log.info("[mcp-profile] Default/Preferences saneado en %s", pref_file)
                except OSError as e:
                    actions.append(f"error escribiendo Default/Preferences: {e}")

        return {"ok": True, "profile": str(p), "actions": actions}

    @staticmethod
    def kill_profile_processes(profile_path: Path | str | None = None) -> list[int]:
        """Busca y termina cualquier proceso Chrome huérfano/zombi que esté bloqueando
        profile_path para permitir que el nuevo Chrome con CDP se enlace sin conflictos."""
        p_str = str(profile_path if profile_path else _cfg("GOOGLE_PROFILE_GLOBAL", ""))
        p_name = Path(p_str).name
        killed = []
        if sys.platform == "win32":
            try:
                ps_cmd = (
                    "Get-CimInstance -Query \"SELECT ProcessId, CommandLine "
                    "FROM Win32_Process WHERE Name = 'chrome.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -like '*{p_name}*' }} | "
                    f"Select-Object -ExpandProperty ProcessId"
                )
                res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                      "-Command", ps_cmd],
                                     capture_output=True, text=True, timeout=8)
                for line in res.stdout.strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        pid = int(line)
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True, timeout=8)
                        killed.append(pid)
                if killed:
                    log.info("[mcp-profile] Procesos zombis de Chrome purgados en %s: %s", p_str, killed)
            except Exception as e:
                log.warning("[mcp-profile] Error al purgar procesos de %s: %s", p_str, e)
        return killed

    def repair_profile(self, profile_path: Path | str | None = None) -> dict:
        """Alias público de saneamiento del perfil Chrome con purga de zombis."""
        p = Path(profile_path if profile_path else str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        killed = self.kill_profile_processes(p)
        res = self.heal_chrome_profile(p)
        if killed:
            res["actions"].insert(0, f"{len(killed)} procesos zombis terminados ({', '.join(map(str, killed))})")
        return res

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
        # Auto-heal profile si --user-data-dir está en argv
        for a in argv:
            if a.startswith("--user-data-dir="):
                u_dir = a[len("--user-data-dir="):].strip('"')
                self.heal_chrome_profile(u_dir)
                break

        if sys.platform == "win32":
            # INT-081 (SSO Hub): chrome.exe es una app GUI Win32 NATIVA, no un
            # comando de consola. El antiguo .bat + cmd.exe /c + DETACHED_PROCESS
            # aislaba el proceso de la estación de ventana interactiva
            # (WinSta0\Default) y la ventana de Google Login NUNCA aparecía en el
            # escritorio del usuario. Ahora se lanza DIRECTO con Popen y
            # CREATE_NEW_PROCESS_GROUP (sin DETACHED_PROCESS): el proceso queda en
            # la sesión interactiva del usuario y Windows trae la ventana al
            # frente (--new-window + --start-maximized ya vienen en argv).
            # Fallback: os.startfile (ShellExecuteEx, siempre escritorio
            # interactivo). Los args pasan verbatim en la lista → sin re-cotizar.
            chrome = argv[0]
            try:
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                p = subprocess.Popen(argv, creationflags=flags,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, close_fds=True)
                return p.pid
            except Exception as ex:
                log.warning("[mcp] Popen directo falló (%s), fallback a os.startfile...", ex)
                cmd_parts = []
                for a in argv[1:]:
                    if a.startswith("--user-data-dir="):
                        val = a[len("--user-data-dir="):].strip('"')
                        cmd_parts.append(f'--user-data-dir="{val}"')
                    elif " " in a and not (a.startswith('"') and a.endswith('"')):
                        cmd_parts.append(f'"{a}"')
                    else:
                        cmd_parts.append(a)
                try:
                    os.startfile(chrome, "open", arguments=" ".join(cmd_parts))
                    return 0
                except Exception:
                    return 0
        return subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True).pid

    def _windows_visible_state(self, profile_path: Path | str | None = None) -> bool | None:
        """🪟 Windows: ¿la instancia de Chrome vinculada al perfil tiene ventana
        gráfica REAL? Devuelve True (≥1 ventana visible en el escritorio),
        False (procesos vivos pero todos con MainWindowHandle == 0 → zombie
        fantasma que responde CDP pero el usuario JAMÁS ve) o None (no-Windows
        o PowerShell falló → estado desconocido: el llamador NUNCA mata nada).
        Una sola pasada PowerShell: Win32_Process (CommandLine = perfil) +
        Get-Process (MainWindowHandle del top-level). $0.00, sin dependencias."""
        if sys.platform != "win32":
            return None
        p_name = Path(str(profile_path if profile_path
                          else _cfg("GOOGLE_PROFILE_GLOBAL", ""))).name
        # INT-081: consulta WQL ligera (solo ProcessId+CommandLine, filtrado en
        # el proveedor WMI), PowerShell -NonInteractive (jamás abre diálogos que
        # cuelgan) y timeout 3.0 s — el antiguo Get-CimInstance sin SELECT
        # (+timeout 10) congelaba el event-loop hasta 10 s en Windows.
        ps_cmd = (
            "Get-CimInstance -Query \"SELECT ProcessId, CommandLine "
            "FROM Win32_Process WHERE Name = 'chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{p_name}*' }} | "
            "ForEach-Object { "
            "$p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "
            "if ($p) { [PSCustomObject]@{ pid = $_.ProcessId; "
            "hwnd = $p.MainWindowHandle } } } | ConvertTo-Json -Compress"
        )
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                  "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                                 capture_output=True, text=True, timeout=3.0)
            if res.returncode != 0:
                log.warning("[mcp] _windows_visible_state: PowerShell rc=%s — desconocido, no se mata nada",
                            res.returncode)
                return None
            out = (res.stdout or "").strip()
            if not out:
                return False  # cero procesos del perfil → cero ventanas
            data = json.loads(out)
            rows = data if isinstance(data, list) else [data]
            return any(int(r.get("hwnd") or 0) != 0
                       for r in rows if isinstance(r, dict))
        except Exception as e:
            log.warning("[mcp] _windows_visible_state falló (%s) — desconocido, no se mata nada", e)
            return None

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

    async def launch_google_login(self, urls: list[str] | None = None, cdp: bool = True,
                                  force_window: bool = False) -> dict:
        """🔑 Abre (o reutiliza) el Chrome REAL con el perfil global y la URL
        de login de Google. UNA vez el humano loguea: Flow hereda la sesión
        (mismo Chrome por CDP) y NotebookLM la captura («📥 Capturar sesión»).
        urls: pestañas a abrir (default = [GOOGLE_LOGIN_URL]). El endpoint
        «Vincular Sesión Google (Login Único)» pasa ServiceLogin Flow +
        notebooklm.google.com para que el único login cubra ambos products.
        INT-071-fix (ventana visible): si CDP ya responde en 9333 se verifica
        que la instancia viva tenga ventana gráfica real en Windows; un zombie
        (MainWindowHandle == 0) se purga con taskkill /F, se borran los
        Singleton* y se relanza una ventana interactiva limpia con foco.
        force_window=True («Abrir Ventana de Chrome» y desde INT-081 también
        «Continuar con Google») purga SIEMPRE y relanza ventana interactiva
        garantizada, sin sondear el estado previo."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        profile = Path(str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        profile.mkdir(parents=True, exist_ok=True)
        heal_res = self.heal_chrome_profile(profile)

        pages = [u.strip() for u in (urls or []) if u and u.strip()] or [
            str(_cfg("GOOGLE_LOGIN_URL",
                     "https://accounts.google.com/ServiceLogin?continue=https://labs.google/fx/tools/flow"))]
        already_up = await self._cdp_up(port) if cdp else False
        pid = None
        window_state: bool | None = None
        relaunched = False
        killed_pids: list[int] = []
        spawn_confirmed: bool | None = None
        window_state_after_spawn: bool | None = None
        if already_up:
            # INT-081 (SSO Hub): purge rules —
            # · force_window=True (botón «Continuar con Google» / «Abrir Ventana»):
            #   purga DIRECTA sin sondear (ahorra hasta 3 s de PowerShell) →
            #   la ventana gráfica queda GARANTIZADA por el spawn nuevo.
            # · Sin force: sondear; se purga si window_state es False (zombie
            #   MainWindowHandle==0) o None EN WINDOWS (PowerShell colgado/error →
            #   se asume SIN ventana visible, nunca se confía en un fantasma).
            #   En no-Windows None es estructural (no hay comprobación) y no purga.
            on_windows = sys.platform == "win32"
            if force_window:
                killed_pids = self.kill_profile_processes(profile)
                heal_res = self.heal_chrome_profile(profile)  # borra Singleton* + repara
                already_up = False
                relaunched = True
                log.warning("[mcp] force_window=True: purgados %s zombis del perfil "
                            "→ spawn de ventana interactiva garantizada", killed_pids or "[]")
            else:
                window_state = self._windows_visible_state(profile)
                if window_state is False or (window_state is None and on_windows):
                    killed_pids = self.kill_profile_processes(profile)
                    heal_res = self.heal_chrome_profile(profile)
                    already_up = False
                    relaunched = True
                    log.warning("[mcp] Chrome fantasma (window_state=%s): "
                                "purgados %s → relanzando ventana interactiva",
                                window_state, killed_pids or "[]")
        if not already_up:
            # Purgar SIEMPRE procesos huérfanos/zombis en profile antes del spawn (tanto CDP como sin CDP)
            # para evitar que una instancia fantasma capture la petición silenciosamente sin abrir ventana visible.
            killed = self.kill_profile_processes(profile)
            if killed:
                heal_res = self.heal_chrome_profile(profile)
            chrome = self._find_chrome_bin()
            argv = [chrome,
                    f"--user-data-dir={profile}",
                    "--new-window",
                    "--start-maximized",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-session-crashed-bubble",
                    "--hide-crash-restore-bubble",
                    "--disable-features=SessionCrashedBubble",
                    "--disable-blink-features=AutomationControlled"]
            if cdp:
                argv.insert(2, f"--remote-debugging-port={port}")
            argv += pages
            try:
                pid = self._spawn_chrome(argv)
            except OSError as e:
                raise MCPManagerError(f"no se pudo lanzar Chrome: {e}",
                                      "CHROME_SPAWN_FAILED") from e
            # INT-081b (lección BROWSER-FACTORY, que SIEMPRE abre): no bastará
            # con lanzar — se CONFIRMA que el Chrome recién nacido está vivo
            # en el puerto CDP (≤3 s) y, en Windows, que la ventana gráfica
            # real apareció. La respuesta deja evidencia exacta en vez de un
            # toast a ciegas: spawn_confirmed + window_state_after_spawn.
            if cdp and pid is not None:
                for _ in range(6):
                    await asyncio.sleep(0.5)
                    if await self._cdp_up(port):
                        spawn_confirmed = True
                        break
                else:
                    spawn_confirmed = False
                    log.warning("[mcp] Chrome lanzado (pid=%s) pero CDP %s NO "
                                "responde tras 3 s — posible fantasma nuevo", pid, port)
                if spawn_confirmed:
                    window_state_after_spawn = self._windows_visible_state(profile)
                    if window_state_after_spawn is False:
                        log.warning("[mcp] CDP %s arriba pero SIN ventana visible "
                                    "(MainWindowHandle==0) — revisar sesión de Windows", port)
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
                "heal_actions": heal_res.get("actions", []),
                "notebooklm_storage": st,
                "window_state": window_state,
                "relaunched": relaunched,
                "killed_pids": killed_pids,
                "spawn_confirmed": spawn_confirmed,
                "window_state_after_spawn": window_state_after_spawn}

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

    async def connect_all_google(self, cdp_timeout_s: float | None = None) -> dict:
        """🚀 Conexión Google en 1 solo clic (W1 + X2):
        1. Primero comprueba si Chrome ya está SANO: puerto CDP arriba Y con
           ventana visible (X2: un Chrome sano NUNCA se mata ni se relanza).
        2. SOLO si está caído o es zombi (puerto abierto sin ventana visible):
           purga procesos del perfil (kill_profile_processes), auto-heal del
           perfil y relanza con force_window=True (misma ruta robusta que
           «Abrir ventana de Chrome»), esperando hasta cdp_timeout_s segundos
           (por defecto 30) sondeando cada 0.5 s.
        3. Si Chrome no sube: no disimular con ok; devolver chrome_up=False y motivo explícito.
        4. Si Chrome está activo: captura preventiva de storage_state si falta,
           y conectar servidores MCP.
        """
        port = int(_cfg("FLOW_CDP_PORT", 9333))
        profile = Path(str(_cfg("GOOGLE_PROFILE_GLOBAL", "")))
        timeout_s = float(cdp_timeout_s if cdp_timeout_s is not None
                          else _cfg("MCP_CONNECT_ALL_CDP_TIMEOUT_S", 30.0))

        heal_actions: list[str] = []

        # 1. Comprobar si ya está arriba Y tiene ventana visible (Chrome sano)
        is_up = await self._cdp_up(port)
        is_zombie = False
        if is_up:
            w_state = self._windows_visible_state(profile)
            if w_state is False:
                is_zombie = True
                log.warning("[connect_all_google] Puerto CDP %s abierto pero sin ventana visible "
                            "(zombie) → purga, saneo y relanzamiento forzado", port)

        launch_res = {}
        chrome_error = None
        if not is_up or is_zombie:
            # 2. SOLO Chrome caído o zombi: purga defensiva y auto-heal (X2).
            #    Un Chrome sano y visible jamás llega aquí: no se mata ni se relanza.
            killed = self.kill_profile_processes(profile)
            heal_res = self.heal_chrome_profile(profile)
            heal_actions = list(heal_res.get("actions", []))
            if killed:
                heal_actions.insert(0, f"{len(killed)} procesos zombis terminados")

            pages = [
                "https://labs.google/fx/tools/flow",
                "https://notebooklm.google.com/"
            ]
            try:
                launch_res = await self.launch_google_login(pages, cdp=True, force_window=True)
            except Exception as e:
                chrome_error = f"Error al lanzar Chrome: {e}"
                log.warning("[connect_all_google] %s", chrome_error)

            # Sondear hasta timeout_s cada 0.5 s
            is_up = False
            steps = max(1, int(timeout_s / 0.5))
            for _ in range(steps):
                if await self._cdp_up(port):
                    is_up = True
                    break
                await asyncio.sleep(0.5)

            if not is_up and not chrome_error:
                chrome_error = f"Chrome no respondió en el puerto CDP {port} tras {int(timeout_s)} s"

        # 3. Captura preventiva si falta storage_state de NotebookLM
        nb_storage = self.nb_storage_state()
        if is_up and (not nb_storage.get("exists") or nb_storage.get("size_bytes", 0) < 100):
            try:
                await self.capture_google_session()
            except Exception as e:
                log.debug("[connect_all_google] auto-captura omitida: %s", e)

        # 4. Conectar ambos servidores MCP
        flow_st = {}
        flow_err = None
        if is_up:
            try:
                flow_st = await self.connect("google-flow")
            except Exception as e:
                flow_err = str(e)
                conn = self._conns.get("google-flow")
                flow_st = self._conn_status(conn) if conn else {"service": "google-flow", "state": ST_ERROR, "last_error": flow_err}
        else:
            flow_err = chrome_error or f"Chrome no responde en el puerto CDP {port}"
            flow_st = {"service": "google-flow", "state": ST_ERROR, "last_error": flow_err}

        nb_st = {}
        nb_err = None
        try:
            nb_st = await self.connect("notebooklm")
        except Exception as e:
            nb_err = str(e)
            conn = self._conns.get("notebooklm")
            nb_st = self._conn_status(conn) if conn else {"service": "notebooklm", "state": ST_ERROR, "last_error": nb_err}

        ok = bool(is_up and flow_st.get("state") == ST_CONNECTED and nb_st.get("state") == ST_CONNECTED)
        return {
            "ok": ok,
            "chrome_up": is_up,
            "chrome_error": chrome_error if not is_up else None,
            "cdp_port": port,
            "flow": flow_st,
            "notebooklm": nb_st,
            "flow_error": flow_err,
            "notebooklm_error": nb_err,
            "heal_actions": heal_actions,
            "launch_result": launch_res,
        }

    async def _cdp_fetch_cookies_raw(self, port: int, timeout: float = 4.0) -> list[dict]:
        """Consulta cookies reales del Chrome vía CDP WebSocket (Storage.getCookies o Network.getAllCookies).
        Usa aiohttp nativo si está disponible, o fallback a Playwright sync en thread."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                ws_url = None
                try:
                    async with session.get(f"http://127.0.0.1:{port}/json/version",
                                           timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            ws_url = data.get("webSocketDebuggerUrl")
                except Exception:
                    pass

                if not ws_url:
                    try:
                        async with session.get(f"http://127.0.0.1:{port}/json/list",
                                               timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                            if resp.status == 200:
                                targets = await resp.json()
                                for t in targets:
                                    if t.get("webSocketDebuggerUrl"):
                                        ws_url = t["webSocketDebuggerUrl"]
                                        break
                    except Exception:
                        pass

                if ws_url:
                    async with session.ws_connect(ws_url, timeout=timeout) as ws:
                        await ws.send_json({"id": 1, "method": "Storage.getCookies"})
                        msg = await ws.receive_json(timeout=timeout)
                        cookies = msg.get("result", {}).get("cookies", [])
                        if cookies:
                            return cookies
                        await ws.send_json({"id": 2, "method": "Network.getAllCookies"})
                        msg = await ws.receive_json(timeout=timeout)
                        return msg.get("result", {}).get("cookies", [])
        except Exception as e:
            log.debug("[mcp] _cdp_fetch_cookies_raw via aiohttp falló (%s)", e)

        # Fallback a Playwright si aiohttp no obtuvo cookies
        try:
            return await self._cdp_fetch_google_cookies_impl(port)
        except Exception as e:
            log.debug("[mcp] fallback playwright falló: %s", e)
            return []

    async def _cdp_has_google_auth(self, port: int) -> tuple[bool, str]:
        """Comprueba de forma estricta si el Chrome en port tiene cookies de autenticación Google.
        Busca __Secure-1PSID o SID asociadas a .google.com con valor no vacío."""
        if not await self._cdp_up(port):
            return False, f"Chrome no responde en el puerto CDP {port}"
        cookies = await self._cdp_fetch_cookies_raw(port)
        if not cookies:
            return False, "Sin cookies en el perfil de Chrome (sesión no iniciada)"
        has_auth = any(
            ("google.com" in str(c.get("domain") or "")) and
            c.get("name") in ("__Secure-1PSID", "SID", "__Secure-3PSID", "SAPISID") and
            bool(c.get("value"))
            for c in cookies
        )
        if has_auth:
            return True, "Sesión activa (cookies Google válidas en CDP)"
        return False, "Sesión no iniciada: falta cookie __Secure-1PSID / SID en FlowImageChrome"

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
        raw = []
        try:
            raw = await self._cdp_fetch_cookies_raw(port)
        except Exception:
            pass
        if not raw:
            try:
                raw = await self._cdp_fetch_google_cookies_impl(port)
            except ImportError as e:
                raise MCPManagerError(
                    "Playwright no está disponible en el backend — instala con: "
                    'uv tool install "notebooklm-py[browser]==0.8.5" (o pip install '
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

    # ── INT-071 · Google One-Tap Hub — [G] Continuar con Google ────────
    async def google_sso_start(self, urls: list[str] | None = None) -> dict:
        """[G] Estado A del Hub: abre el Chrome del perfil global (CDP 9333)
        en el SELECTOR de cuentas de Google (AccountChooser → Flow) + 2ª
        pestaña NotebookLM, y arranca el watchdog que hace polling cada
        GOOGLE_SSO_POLL_S hasta ver la cookie de autenticación
        (__Secure-1PSID / SID). Al verla: captura storage_state.json,
        conecta Flow + NotebookLM y extrae la cuenta — sin más clicks.
        Devuelve inmediatamente (el backend nunca se bloquea)."""
        nb_page = "https://notebooklm.google.com/"
        pages = [u.strip() for u in (urls or []) if u and u.strip()] or [
            str(_cfg("GOOGLE_SSO_URL", "") or nb_page), nb_page]
        # INT-081: el usuario pulsa «Continuar con Google» → exige ventana
        # visible. force_window=True purga zombis (9333 ocupado por un huérfano
        # sin MainWindowHandle), limpia Singleton* y hace spawn de Chrome
        # interactivo SIEMPRE — jamás un PUT /json/new sobre un fantasma.
        res = await self.launch_google_login(pages, cdp=True, force_window=True)
        self._sso.update({"phase": "watching", "started_at": time.time(),
                          "error": "", "account": None,
                          "updated_at": time.time()})
        self._sso_ensure_task()
        log.info("[google-sso] watching=%s poll=%ss port=%s pages=%s",
                 True, _cfg("GOOGLE_SSO_POLL_S", 2), res.get("cdp_port"), pages)
        return {"ok": True, "watching": True, "phase": "watching",
                "cdp_port": res.get("cdp_port"), "pages": pages,
                "already_up": res.get("already_up"),
                "pid": res.get("pid"),
                "heal_actions": res.get("heal_actions", []),
                "notebooklm_storage": res.get("notebooklm_storage"),
                "relaunched": res.get("relaunched", False),
                "window_state": res.get("window_state"),
                "killed_pids": res.get("killed_pids", []),
                "spawn_confirmed": res.get("spawn_confirmed"),
                "window_state_after_spawn": res.get("window_state_after_spawn")}

    def _sso_ensure_task(self) -> None:
        """Arranca el watchdog si no hay uno vivo (singleton por manager)."""
        t = self._sso.get("task")
        if t is not None and not t.done():
            return
        self._sso["task"] = asyncio.create_task(self._sso_watchdog())

    async def _sso_watchdog(self) -> None:
        """Polling GOOGLE_SSO_POLL_S: cookie __Secure-1PSID/SID vía CDP →
        captura + conexión. Fail-soft total: un error de poll se registra y
        se reintenta; el timeout solo marca phase=timeout. Nada mata nunca
        el loop del backend."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        poll = max(1, int(_cfg("GOOGLE_SSO_POLL_S", 2)))
        timeout = max(60, int(_cfg("GOOGLE_SSO_TIMEOUT_S", 900)))
        while self._sso.get("phase") == "watching":
            try:
                has_auth, _detail = await self._cdp_has_google_auth(port)
                if has_auth:
                    self._sso["phase"] = "connecting"
                    self._sso["updated_at"] = time.time()
                    if await self._sso_finish_connect(port):
                        return
                    # cookies aún incompletas para la captura → seguir esperando
                    self._sso["phase"] = "watching"
            except Exception as e:  # fail-open: el poll nunca muere por un error
                self._sso["error"] = str(e)
            if time.time() - float(self._sso.get("started_at") or 0) > timeout:
                self._sso["phase"] = "timeout"
                self._sso["updated_at"] = time.time()
                log.info("[google-sso] watchdog timeout (%ss) sin login", timeout)
                return
            await asyncio.sleep(poll)

    async def _sso_finish_connect(self, port: int) -> bool:
        """Sesión detectada: captura cookies → conecta ambos MCP → extrae
        la cuenta (fail-soft, cosmética). True = Hub pasa a CONNECTED.
        False = la captura aún no tiene cookies → reintenta (watching)."""
        try:
            await self.capture_google_session()
        except MCPManagerError as e:
            if e.code == "NO_GOOGLE_COOKIES":
                return False
            self._sso["error"] = f"captura: {e}"
        except Exception as e:
            self._sso["error"] = f"captura: {e}"
        for svc, tag in (("google-flow", "flow"), ("notebooklm", "notebooklm")):
            try:
                await self.connect(svc)
                self._sso[f"{tag}_error"] = ""
            except Exception as e:
                self._sso[f"{tag}_error"] = str(e)
        self._sso["account"] = await self.google_account_info(port)
        self._sso["phase"] = "connected"
        self._sso["updated_at"] = time.time()
        log.info("[google-sso] sesión conectada (account=%s)",
                 (self._sso.get("account") or {}).get("email", "?"))
        return True

    async def _cdp_list_targets(self, port: int, timeout: float = 3.0) -> list[dict]:
        """GET http://127.0.0.1:<port>/json/list — targets CDP (url/title)."""
        try:
            import httpx  # noqa: PLC0415
            async with httpx.AsyncClient() as client:
                r = await client.get(f"http://127.0.0.1:{port}/json/list",
                                     timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    def _fetch_signout_html(self, port: int) -> str:
        """Estrategia 2 (Playwright en thread): abre SignOutOptions en el
        Chrome del perfil vía connectOverCDP y devuelve su HTML. Cierra la
        CONEXIÓN CDP, no el Chrome del usuario (mismo patrón que
        _cdp_fetch_google_cookies_impl)."""
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.new_page()
                try:
                    page.goto("https://accounts.google.com/SignOutOptions?hl=es",
                              timeout=8000, wait_until="domcontentloaded")
                    return page.content()
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    async def google_account_info(self, port: int) -> dict | None:
        """Cuenta activa del Chrome de login — DATO COSMÉTICO del Hub:
        fail-soft, devuelve None si no puede (nunca bloquea la conexión).
        Estrategia 1: targets CDP (barata, sin Playwright). Estrategia 2:
        HTML de SignOutOptions vía Playwright en thread."""
        try:
            acc = account_from_targets(await self._cdp_list_targets(port))
            if acc:
                return acc
        except Exception:
            pass
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401,PLC0415
            html = await asyncio.to_thread(self._fetch_signout_html, port)
            return account_from_html(html)
        except Exception:
            return None

    async def google_sso_status(self) -> dict:
        """GET del Hub: fase del watcher, cuenta, pills por servicio
        (Flow / NotebookLM MCP / Workspace & Gemini), CDP y storage.
        Regla honesta de CONECTADO: sesión viva en el Chrome (cookie) O
        watcher conectado en esta sesión del backend — así el Hub refleja
        el ecosistema aunque el backend se haya reiniciado."""
        port = int(_cfg("GOOGLE_LOGIN_CDP_PORT", 9333))
        base = await self.google_login_status()
        has_auth, auth_detail = False, ""
        try:
            has_auth, auth_detail = await self._cdp_has_google_auth(port)
        except Exception as e:
            auth_detail = str(e)
        flow_st = self._conn_status(self._conns.get("google-flow")) or {}
        nb_conn = self._conns.get("notebooklm")
        nb_st = self._conn_status(nb_conn) or {}
        phase = str(self._sso.get("phase") or "idle")

        acc = self._sso.get("account")
        if not acc and (has_auth or flow_st.get("state") == ST_CONNECTED):
            try:
                acc = await self.google_account_info(port)
                if acc:
                    self._sso["account"] = acc
            except Exception:
                pass

        if phase in ("idle", "timeout") and (has_auth or flow_st.get("state") == ST_CONNECTED):
            if flow_st.get("state") == ST_CONNECTED or nb_st.get("state") == ST_CONNECTED or acc:
                phase = "connected"
        return {"cdp_port": base.get("cdp_port"),
                "chrome_up": base.get("chrome_up"),
                "profile_dir": base.get("profile_dir"),
                "shared_with_flow": base.get("shared_with_flow"),
                "notebooklm_storage": base.get("notebooklm_storage"),
                "sso_phase": phase,
                "sso_error": str(self._sso.get("error") or ""),
                "session_auth": bool(has_auth),
                "auth_detail": auth_detail,
                "account": self._sso.get("account"),
                "services": {
                    "flow": {"state": flow_st.get("state", "disconnected"),
                             "auth": flow_st.get("auth", "")},
                    "notebooklm": {"state": nb_st.get("state", "disconnected"),
                                   "auth": nb_st.get("auth", ""),
                                   "tools": len((nb_conn.tools if nb_conn else None) or [])},
                    "workspace": {"state": "connected" if has_auth else "disconnected",
                                  "note": "misma sesión Google del perfil global (Drive/Gemini)"}},
                "poll_s": max(1, int(_cfg("GOOGLE_SSO_POLL_S", 2)))}

    async def google_sso_logout(self) -> dict:
        """🚪 «Cambiar cuenta / Desconectar»: cancela el watcher, desconecta
        ambos MCP, ARCHIVA el storage_state.json (.bak-<ts>, nunca destruye
        cookies sin copia) y cierra el Chrome del perfil global — el
        siguiente «Continuar con Google» parte limpio."""
        actions: list[str] = []
        t = self._sso.get("task")
        if t is not None and not t.done():
            t.cancel()
            actions.append("vigilancia cancelada")
        for svc in ("google-flow", "notebooklm"):
            try:
                await self.disconnect(svc)
                actions.append(f"{svc} desconectado")
            except Exception as e:
                actions.append(f"{svc}: {e}")
        for p in self._nb_storage_paths():
            if p.is_file():
                bak = p.with_name(f"{p.name}.bak-{int(time.time())}")
                try:
                    p.rename(bak)
                    actions.append(f"storage archivado → {bak.name}")
                except OSError as e:
                    actions.append(f"storage: {e}")
        try:
            killed = self.kill_profile_processes(
                Path(str(_cfg("GOOGLE_PROFILE_GLOBAL", ""))))
            if killed:
                actions.append(f"{len(killed)} procesos Chrome cerrados")
        except Exception as e:
            actions.append(f"chrome: {e}")
        self._sso.update({"phase": "idle", "started_at": 0.0, "error": "",
                          "account": None, "updated_at": time.time()})
        return {"ok": True, "actions": actions}


    # ── helpers ──
    def _mirror_notebook_arg(self, conn: "_Conn", tool: str, arguments: dict) -> None:
        """INT-069 · compat notebooklm-py ≥0.8.x: sus tools (notebook_describe,
        source_add, studio_*, chat_ask…) declaran el parámetro `notebook` y
        FastMCP rechaza kwargs desconocidos con ValidationError (verificado).
        Si el inputSchema de la tool (tools/list) declara `notebook` y NO
        `notebook_id`, renombra la clave legacy del §3. Servidores legacy que
        sí declaran notebook_id (o tools sin schema) quedan intactos."""
        if "notebook_id" not in arguments:
            return
        for t in conn.tools or []:
            if t.get("name") != tool:
                continue
            props = ((t.get("inputSchema") or {}).get("properties") or {})
            if "notebook" in props and "notebook_id" not in props:
                arguments["notebook"] = arguments.pop("notebook_id")
            break

    def _mirror_query_arg(self, conn: "_Conn", tool: str, arguments: dict) -> None:
        """INT-069.1 · compat notebooklm-py ≥0.8.x: la tool de contexto del
        orquestador (chat_ask desde v0.8.5; antes query_notebook) declara el
        parámetro `question` y el orquestador (INT-023) envía `query` — el
        nombre de la tool legacy. FastMCP rechaza kwargs desconocidos con
        ValidationError. Si el inputSchema declara `question` y NO `query`,
        renombra la clave. Servidores legacy que sí declaran `query` (o tools
        sin schema) quedan intactos."""
        if "query" not in arguments:
            return
        for t in conn.tools or []:
            if t.get("name") != tool:
                continue
            props = ((t.get("inputSchema") or {}).get("properties") or {})
            if "question" in props and "query" not in props:
                arguments["question"] = arguments.pop("query")
            break

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
                is_mock = (conn.server_info.get("name") == "fake-flow")
                port = int(_cfg("FLOW_CDP_PORT", 9333))
                cdp_alive = await self._cdp_up(port)
                if cdp_alive:
                    auth_ok, auth_detail = await self._cdp_has_google_auth(port)
                    if not auth_ok:
                        conn.auth = "auth_required"
                        conn.auth_detail = auth_detail
                        conn.state = ST_AUTH_REQUIRED
                        return
                elif not is_mock:
                    conn.auth = "auth_required"
                    conn.auth_detail = f"Chrome no responde en el puerto CDP {port}"
                    conn.state = ST_AUTH_REQUIRED
                    return

                try:
                    text = await conn.call("flow_list_assets", {}, timeout=15.0)
                    if "not signed in" in text.lower():
                        conn.auth = "auth_required"
                        conn.auth_detail = text.strip()[:200]
                        conn.state = ST_AUTH_REQUIRED
                    else:
                        conn.auth = "ok"
                        conn.auth_detail = "Sesión activa (cookies Google válidas en CDP)" if cdp_alive else "Mock ok"
                except Exception as ex:
                    if _AUTHISH_RE.search(str(ex)):
                        conn.auth = "auth_required"
                        conn.auth_detail = str(ex)[:200]
                        conn.state = ST_AUTH_REQUIRED
                    else:
                        conn.auth = "ok" if cdp_alive else "unknown"
                        conn.auth_detail = str(ex)[:160]
            else:
                probe = str(_cfg("NOTEBOOKLM_PROBE_TOOL", "notebook_list") or "").strip()
                names = {t.get("name") for t in conn.tools}
                if probe not in names:
                    for cand in _LIST_NOTEBOOK_TOOLS:
                        if cand in names:
                            probe = cand
                            break
                if probe and probe in names:
                    try:
                        await conn.call(probe, {}, timeout=25.0)
                        conn.auth = "ok"
                    except MCPManagerError as e:
                        if _AUTHISH_RE.search(str(e)):
                            conn.auth = "auth_required"
                            conn.auth_detail = str(e)[:200]
                            conn.state = ST_AUTH_REQUIRED
                            # INT-069 · session hardening: cookies expiradas →
                            # UN `notebooklm auth refresh --quiet` + UN reintento
                            # de la sonda. Gate NLM_AUTH_REFRESH (default "1").
                            # Fail-open: si el refresh falla, el estado queda
                            # EXACTAMENTE igual que sin refresh (auth_required).
                            if _auth_refresh_enabled():
                                try:
                                    ok, summary = await asyncio.to_thread(
                                        auth_refresh_notebooklm, 90.0)
                                except Exception as e:  # noqa: BLE001 — fail-open total
                                    ok, summary = False, f"refresh crash: {e}"
                                if ok:
                                    try:
                                        await conn.call(probe, {}, timeout=25.0)
                                        conn.auth = "ok"
                                        conn.state = ST_CONNECTED
                                        conn.auth_detail = (
                                            "auth refresh automático ok "
                                            f"({summary})"[:200])
                                        log.info("[%s] cookies refrescadas "
                                                 "automáticamente (INT-069)",
                                                 conn.service)
                                    except MCPManagerError as e2:
                                        conn.auth_detail = (
                                            f"refresh ok ({summary}) pero la "
                                            f"sonda sigue fallando: "
                                            f"{str(e2)[:140]}")
                                else:
                                    conn.auth_detail = (
                                        f"{str(e)[:120]} · refresh automático "
                                        f"falló: {summary}")
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
