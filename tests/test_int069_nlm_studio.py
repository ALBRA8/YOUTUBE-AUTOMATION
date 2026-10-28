#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-069 · NotebookLM Studio Bridge + session hardening + pin

Cubre (pytest NATIVO, cero red, cero subprocess reales):
  · auth_refresh_notebooklm: ok / rc!=0 / timeout / CLI ausente (mock subprocess.run)
  · _preflight: refresh automático al detectar AUTH_REQUIRED, gate NLM_AUTH_REFRESH
    y fail-open (si el refresh falla, estado EXACTAMENTE igual que sin refresh)
  · _mirror_notebook_arg: compat `notebook_id` → `notebook` para notebooklm-py
    v0.8.5 (FastMCP rechaza kwargs desconocidos)
  · Studio Bridge: happy path mockeado, fail-closed sin MCP, guard
    NLM_STUDIO_ENABLED=0, endpoints REST (202/400/404/409/502) y download
    con exports en tmp_path.

Convención INT-068+: pytest con TestClient síncrono y @pytest.mark.asyncio.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import nlm_studio  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

NB = "nbid1234567"  # pasa el patrón canónico [A-Za-z0-9][A-Za-z0-9_-]{5,63}
client = TestClient(app)


class _Resp:
    """Sustituto mínimo de subprocess.CompletedProcess."""

    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


class _StubConn:
    """_Conn mínima para _preflight/_mirror (sin subprocess)."""

    service = "notebooklm"
    state = mcpm.ST_CONNECTED
    auth = "unknown"
    auth_detail = ""
    server_info = {}

    def __init__(self, tools=None, fail_first=True):
        self.tools = tools if tools is not None else [
            {"name": "notebook_list", "inputSchema": {"properties": {}}}]
        self.fail_first = fail_first
        self.probe_calls = 0

    async def call(self, tool, arguments, timeout):
        self.probe_calls += 1
        if self.fail_first and self.probe_calls == 1:
            raise mcpm.MCPManagerError(
                "Error: Not signed in — cookies expiradas", "TOOL_ERROR")
        return "[]"


class FakeExec:
    """Sustituto de nlm_studio._exec: tools MCP → respuestas JSON enlatadas."""

    def __init__(self, script=None, fail_code=None):
        self.calls = []
        self.script = script or {}
        self.fail_code = fail_code

    async def __call__(self, tool, arguments, timeout=None):
        self.calls.append((tool, dict(arguments)))
        if self.fail_code:
            raise mcpm.MCPManagerError(f"{tool} no disponible", self.fail_code)
        h = self.script.get(tool)
        if callable(h):
            return h(arguments)
        return {"ok": True, "tool": tool,
                "text": json.dumps(h or {}, ensure_ascii=False)}


def _download_writer():
    """Handler de studio_download que ESCRIBE el fichero en args['path']."""

    def _h(args):
        Path(args["path"]).write_bytes(b"ID3-fake-audio-bytes")
        return {"ok": True, "tool": "studio_download",
                "text": json.dumps({"status": "downloaded", "path": args["path"]})}
    return _h


def _happy_script(nb=NB):
    return {
        nlm_studio.TOOL_NOTEBOOK_CREATE: {"status": "created", "notebook_id": nb},
        nlm_studio.TOOL_SOURCE_ADD: {"status": "added", "source_id": "src-1"},
        nlm_studio.TOOL_STUDIO_GENERATE: {"notebook_id": nb, "task_id": "task-1",
                                          "status": "running"},
        nlm_studio.TOOL_STUDIO_STATUS: {"notebook_id": nb, "task_id": "task-1",
                                        "status": "completed", "is_complete": True,
                                        "media_ready": True,
                                        "url": "https://example/audio"},
        nlm_studio.TOOL_STUDIO_DOWNLOAD: _download_writer(),
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Aislamiento por test: exports en tmp, gates por defecto, jobs limpios."""
    monkeypatch.setattr(config, "NLM_STUDIO_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setattr(config, "NLM_STUDIO_ENABLED", "1")
    monkeypatch.setattr(config, "NLM_STUDIO_POLL_TIMEOUT", "900")
    monkeypatch.setattr(config, "NLM_AUTH_REFRESH", "1")
    nlm_studio._JOBS.clear()
    nlm_studio._TASKS.clear()
    yield
    for t in list(nlm_studio._TASKS.values()):
        t.cancel()


# ── 1-2 · auth refresh (subprocess 100% mockeado) ────────────────────────
def test_auth_refresh_ok(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        seen["timeout"] = kw.get("timeout")
        return _Resp(0, out="cookies rotated\n")

    monkeypatch.setattr(mcpm.shutil, "which",
                        lambda n: "/usr/bin/notebooklm" if n == "notebooklm" else None)
    monkeypatch.setattr(mcpm.subprocess, "run", fake_run)
    ok, summary = mcpm.auth_refresh_notebooklm(timeout=42.0)
    assert ok is True
    assert seen["argv"][1:] == ["auth", "refresh", "--quiet"]
    assert seen["timeout"] == 42.0
    assert "rotated" in summary


def test_auth_refresh_fail_modes(monkeypatch):
    monkeypatch.setattr(mcpm.shutil, "which",
                        lambda n: "/usr/bin/notebooklm" if n == "notebooklm" else None)
    # rc != 0
    monkeypatch.setattr(mcpm.subprocess, "run",
                        lambda argv, **kw: _Resp(1, err="no session"))
    ok, s = mcpm.auth_refresh_notebooklm()
    assert ok is False and "rc=1" in s and "no session" in s
    # timeout (NUNCA lanza)
    def boom(argv, **kw):
        raise mcpm.subprocess.TimeoutExpired(cmd=argv, timeout=5)
    monkeypatch.setattr(mcpm.subprocess, "run", boom)
    ok2, s2 = mcpm.auth_refresh_notebooklm()
    assert ok2 is False and "timeout" in s2.lower()
    # CLI ausente
    monkeypatch.setattr(mcpm.shutil, "which", lambda n: None)
    ok3, s3 = mcpm.auth_refresh_notebooklm()
    assert ok3 is False and "PATH" in s3 and "0.8.5" in s3


# ── 3-5 · integración del refresh en el preflight (AUTH_REQUIRED) ────────
@pytest.mark.asyncio
async def test_preflight_refresh_recovers(monkeypatch):
    conn = _StubConn()
    refresh_calls = []

    def fake_refresh(timeout=90.0):        # sync: corre en to_thread
        refresh_calls.append(timeout)
        return True, "rotated ok"

    monkeypatch.setattr(mcpm, "auth_refresh_notebooklm", fake_refresh)
    await mcpm.manager._preflight(conn, None)
    assert conn.probe_calls == 2          # sonda + UN reintento
    assert refresh_calls == [90.0]        # UN solo refresh
    assert conn.auth == "ok"
    assert conn.state == mcpm.ST_CONNECTED
    assert "refresh" in conn.auth_detail.lower()


@pytest.mark.asyncio
async def test_preflight_refresh_disabled_gate(monkeypatch):
    monkeypatch.setattr(config, "NLM_AUTH_REFRESH", "0")
    conn = _StubConn()
    called = []

    def fake_refresh(timeout=90.0):
        called.append(1)
        return True, "rotated"

    monkeypatch.setattr(mcpm, "auth_refresh_notebooklm", fake_refresh)
    await mcpm.manager._preflight(conn, None)
    assert called == []                    # gate a "0": no se intenta
    assert conn.auth == "auth_required"
    assert conn.state == mcpm.ST_AUTH_REQUIRED


@pytest.mark.asyncio
async def test_preflight_refresh_fail_open(monkeypatch):
    conn = _StubConn()

    def fake_refresh(timeout=90.0):
        return False, "rc=1: sin master token"

    monkeypatch.setattr(mcpm, "auth_refresh_notebooklm", fake_refresh)
    await mcpm.manager._preflight(conn, None)
    # fail-open: estado EXACTAMENTE igual que sin refresh
    assert conn.auth == "auth_required"
    assert conn.state == mcpm.ST_AUTH_REQUIRED
    assert conn.probe_calls == 1           # no se reintenta si el refresh falló
    assert "refresh automático falló" in conn.auth_detail


# ── 6-8 · compat de nombres v0.8.5 + exención de notebook_create ─────────
def test_execute_mirrors_notebook_arg():
    mgr = mcpm.MCPClientManager()
    conn = _StubConn(tools=[{
        "name": "studio_generate",
        "inputSchema": {"properties": {"notebook": {"type": "string"},
                                       "artifact_type": {"type": "string"}}}}])
    args = {"notebook_id": NB, "artifact_type": "audio"}
    mgr._mirror_notebook_arg(conn, "studio_generate", args)
    assert args == {"notebook": NB, "artifact_type": "audio"}
    # servidor legacy (declara notebook_id) queda intacto
    conn2 = _StubConn(tools=[{
        "name": "echo",
        "inputSchema": {"properties": {"notebook_id": {"type": "string"}}}}])
    args2 = {"notebook_id": NB, "x": 1}
    mgr._mirror_notebook_arg(conn2, "echo", args2)
    assert args2 == {"notebook_id": NB, "x": 1}


# ── INT-069.1 · alineación de defaults a v0.8.5 + mirror query→question ───
def test_mirror_query_arg_v085():
    """chat_ask (v0.8.5) declara `question`; el orquestador (INT-023) envía
    `query` (nombre de la tool legacy query_notebook) → se espeja."""
    mgr = mcpm.MCPClientManager()
    conn = _StubConn(tools=[{
        "name": "chat_ask",
        "inputSchema": {"properties": {"notebook": {"type": "string"},
                                       "question": {"type": "string"}}}}])
    args = {"notebook": NB, "query": "biblia de investigación"}
    mgr._mirror_query_arg(conn, "chat_ask", args)
    assert args == {"notebook": NB, "question": "biblia de investigación"}
    # servidor legacy (declara query, p.ej. query_notebook) queda intacto
    conn2 = _StubConn(tools=[{
        "name": "query_notebook",
        "inputSchema": {"properties": {"notebook_id": {"type": "string"},
                                       "query": {"type": "string"}}}}])
    args2 = {"notebook_id": NB, "query": "x"}
    mgr._mirror_query_arg(conn2, "query_notebook", args2)
    assert args2 == {"notebook_id": NB, "query": "x"}


def test_defaults_aligned_v085():
    """INT-069.1: los defaults de código apuntan a tools v0.8.5
    (notebook_list para el probe; chat_ask para el contexto del orquestador),
    con los nombres legacy aún aceptados en _LIST_NOTEBOOK_TOOLS."""
    assert config.NOTEBOOKLM_PROBE_TOOL == "notebook_list"
    assert config.NOTEBOOKLM_CONTEXT_TOOL == "chat_ask"
    backend = Path(__file__).resolve().parents[1] / "backend"
    mm_src = (backend / "services" / "mcp_manager.py").read_text(encoding="utf-8")
    assert '_cfg("NOTEBOOKLM_PROBE_TOOL", "notebook_list")' in mm_src
    assert '"notebook_list", "list_notebooks"' in mm_src  # legacy aceptado
    po_src = (backend / "services" / "pipeline_orchestrator.py").read_text(
        encoding="utf-8")
    assert '_cfg("NOTEBOOKLM_CONTEXT_TOOL", "chat_ask")' in po_src


@pytest.mark.asyncio
async def test_notebook_create_exempt_from_missing_id_guard(monkeypatch):
    """notebook_create no acepta notebook_id (v0.8.5): debe pasar el fail-fast
    del §3 y fallar SOLO por no haber conexión (DISCONNECTED), nunca por
    MISSING_NOTEBOOK_ID."""
    try:
        await mcpm.manager.execute("notebooklm", "notebook_create",
                                   {"title": "ALBRA Studio"}, auto_connect=False)
        raise AssertionError("debía fallar sin conexión")
    except mcpm.MCPManagerError as e:
        assert e.code == "DISCONNECTED", e.code


@pytest.mark.asyncio
async def test_ensure_notebook_creates_with_title(monkeypatch):
    fake = FakeExec(script=_happy_script("created991"))
    monkeypatch.setattr(nlm_studio, "_exec", fake)
    out = await nlm_studio.ensure_notebook(title="ALBRA Studio 2026-10-27")
    assert out == {"notebook_id": "created991", "created": True,
                   "title": "ALBRA Studio 2026-10-27"}
    tool, args = fake.calls[0]
    assert tool == nlm_studio.TOOL_NOTEBOOK_CREATE
    assert args == {"title": "ALBRA Studio 2026-10-27"}


# ── 9-11 · Studio Bridge: happy path / fail-closed / poll ────────────────
@pytest.mark.asyncio
async def test_studio_happy_path(monkeypatch, tmp_path):
    fake = FakeExec(script=_happy_script())
    monkeypatch.setattr(nlm_studio, "_exec", fake)
    res = await nlm_studio.run_audio_overview(notebook_id=NB,
                                              text="guion de prueba",
                                              poll_interval=0.5)
    assert res["notebook_id"] == NB and res["task_id"] == "task-1"
    p = Path(res["file"])
    assert p.is_file() and p.stat().st_size > 0
    assert p.suffix == ".m4a"                      # v0.8.5 baja AAC/MP4 (#2034)
    assert str(tmp_path) in str(p)                 # export dir override respetado
    assert [c[0] for c in fake.calls] == [
        nlm_studio.TOOL_SOURCE_ADD, nlm_studio.TOOL_STUDIO_GENERATE,
        nlm_studio.TOOL_STUDIO_STATUS, nlm_studio.TOOL_STUDIO_DOWNLOAD]
    gen_args = fake.calls[1][1]
    assert gen_args["notebook_id"] == NB and gen_args["artifact_type"] == "audio"
    dl_args = fake.calls[3][1]
    assert dl_args["artifact_type"] == "audio" and dl_args["path"] == str(p)


@pytest.mark.asyncio
async def test_fail_closed_sin_mcp(monkeypatch):
    monkeypatch.setattr(nlm_studio, "_exec", FakeExec(fail_code="DISCONNECTED"))
    with pytest.raises(nlm_studio.NLMStudioError) as ei:
        await nlm_studio.run_audio_overview(notebook_id=NB, text="x")
    assert ei.value.code == "DISCONNECTED"


@pytest.mark.asyncio
async def test_poll_outcomes(monkeypatch):
    # timeout del poll
    monkeypatch.setattr(nlm_studio, "_exec", FakeExec(script={
        nlm_studio.TOOL_STUDIO_STATUS: {"status": "running",
                                        "is_complete": False}}))
    with pytest.raises(nlm_studio.NLMStudioError) as ei:
        await nlm_studio.poll_status(NB, "task-1", timeout_s=0.5, interval=0.1)
    assert ei.value.code == "GENERATION_TIMEOUT"
    # error del backend de NotebookLM
    monkeypatch.setattr(nlm_studio, "_exec", FakeExec(script={
        nlm_studio.TOOL_STUDIO_STATUS: {"status": "failed", "error": "quota"}}))
    with pytest.raises(nlm_studio.NLMStudioError) as ei2:
        await nlm_studio.poll_status(NB, "task-1", timeout_s=5, interval=0.1)
    assert ei2.value.code == "GENERATION_FAILED"


# ── 12-16 · guard + endpoints REST ───────────────────────────────────────
@pytest.mark.asyncio
async def test_studio_guard_disabled(monkeypatch):
    monkeypatch.setattr(config, "NLM_STUDIO_ENABLED", "0")
    with pytest.raises(nlm_studio.NLMStudioError) as ei:
        await nlm_studio.ensure_notebook(notebook_id=NB)
    assert ei.value.code == "STUDIO_DISABLED"
    r = client.post("/api/nlm/studio/audio-overview", json={"text": "hola"})
    assert r.status_code == 404
    r2 = client.get(f"/api/nlm/studio/status/{NB}")
    assert r2.status_code == 404


def test_endpoint_validation_and_status():
    r = client.post("/api/nlm/studio/audio-overview", json={})
    assert r.status_code == 400                      # text requerido
    r2 = client.post("/api/nlm/studio/audio-overview",
                     json={"text": "x", "notebook_id": "bad id!"})
    assert r2.status_code == 502                     # id inválido → fail-closed
    assert "INVALID_NOTEBOOK_ID" in r2.json()["detail"]
    r3 = client.get(f"/api/nlm/studio/status/{NB}")
    assert r3.status_code == 200 and r3.json()["state"] == "idle"


def test_endpoint_download_serves_latest(tmp_path):
    d = Path(config.NLM_STUDIO_EXPORT_DIR) / NB
    d.mkdir(parents=True)
    old = d / "albra_studio_20260101_000000_aaa.m4a"
    old.write_bytes(b"old-audio")
    new = d / "albra_studio_20260102_000000_bbb.m4a"
    new.write_bytes(b"new-audio-bytes")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    r = client.get(f"/api/nlm/studio/download/{NB}")
    assert r.status_code == 200
    assert r.content == b"new-audio-bytes"
    assert r.headers["content-type"].startswith("audio/mp4")


def test_endpoint_download_rejects_bad_ids():
    # traversal URL-encoded → ni siquiera enruta (404 del router, sin tocar FS)
    r = client.get("/api/nlm/studio/download/..%2F..%2Fetc")
    assert r.status_code == 404
    # id que enruta pero viola el patrón canónico → 404 INVALID_NOTEBOOK_ID
    r1 = client.get("/api/nlm/studio/download/bad%20id")
    assert r1.status_code == 404 and "INVALID_NOTEBOOK_ID" in r1.json()["detail"]
    # id válido sin exports → 404 NO_AUDIO
    r2 = client.get(f"/api/nlm/studio/download/{NB}")
    assert r2.status_code == 404 and "NO_AUDIO" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_start_in_progress_and_job_lifecycle(monkeypatch):
    # guard: segunda generación para el mismo notebook → 409-code
    nlm_studio._JOBS[NB] = {"notebook_id": NB, "state": "generating"}
    with pytest.raises(nlm_studio.NLMStudioError) as ei:
        await nlm_studio.start_audio_overview(notebook_id=NB, text="guion")
    assert ei.value.code == "GENERATION_IN_PROGRESS"
    # ciclo completo con task de fondo (mockeado)
    nlm_studio._JOBS.clear()
    monkeypatch.setattr(nlm_studio, "_exec", FakeExec(script=_happy_script()))
    job = await nlm_studio.start_audio_overview(notebook_id=NB, text="guion job")
    assert job["state"] == "generating" and job["notebook_id"] == NB
    await asyncio.wait_for(nlm_studio._TASKS[NB], timeout=5)
    st = nlm_studio.job_status(NB)
    assert st["state"] == "ready" and st["task_id"] == "task-1"
    assert st["file"] and Path(st["file"]).is_file()
