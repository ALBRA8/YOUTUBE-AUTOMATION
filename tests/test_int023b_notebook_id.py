#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-023.4 (HOTFIX) · Propagación y auto-descubrimiento de notebook_id

Reproduce el bug REAL del E2E live: pre-flight [0/3] green con notebook_id
vacío → Stage [1/3] muere con `[TOOL_ERROR] 1 validation error for
call[notebook_query] notebook_id Missing required argument` y
`"notebook_id": ""` en el state.json.

Regresión cubierta (todo hermético: cero red, cero Chrome, cero LLM):
  · parse_notebook_list: JSON (lista/dict anidado), líneas con UUID,
    URLs /notebook/<id>, dedupe, ids inválidos filtrados, basura → [].
  · mcp_manager.execute: inyección del id (payload > param > .env) y
    FAIL-FAST determinista MISSING_NOTEBOOK_ID para tools que lo requieren
    (p.ej. 'notebook_query'); tools de listado exentas (warning).
  · list_notebooks() / discover_notebook_id(): selección de tool de listado,
    AUTH_REQUIRED surfaced, LIST_EMPTY, descubrimiento NUNCA lanza.
  · Pipeline Orchestrator [0/3]: auto-descubrimiento → estado persistido +
    inyección en los arguments de notebook_query; discovery vacío →
    PRE_FLIGHT_MISSING_NOTEBOOK_ID ANTES de gastar tokens; id explícito →
    0 llamadas de discovery; fallback .env propagado al estado.
  · Endpoints REST: POST /api/mcp/list-notebooks (200/502),
    POST /api/mcp/execute sin id → 502 MISSING_NOTEBOOK_ID y
    POST /api/pipeline/run SIN notebook_id → corrida completa con el id
    auto-descubierto (el escenario exacto del bug, a nivel HTTP).

Convención del repo: script stdlib (sin pytest), 0 dependencias externas.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402

OK, FAIL = 0, 0

UUID_A = "aaaa1111-bbbb-cccc-dddd-eeeeffff0000"
UUID_B = "99998888-7777-6666-5555-444433332222"


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _fake_conn(tools, responder):
    """_Conn hermético: sin proceso real; call() la responde el test."""
    c = mcpm._Conn("notebooklm")
    c.state = mcpm.ST_CONNECTED
    c.proc = SimpleNamespace(returncode=None)
    c.tools = [{"name": t} for t in tools]
    c.auth = "ok"

    async def call(tool, arguments=None, timeout=30.0):
        return await responder(tool, arguments or {})

    c.call = call
    return c


async def _echo_json(tool, arguments):
    return json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False)


def parser_tests():
    print("\n── S1 · parse_notebook_list (tolerante, sin duplicados) ──")
    nbs = mcpm.parse_notebook_list(
        json.dumps([{"id": UUID_A, "title": "Biblia A"}]))
    check("JSON lista de dicts", len(nbs) == 1 and nbs[0]["id"] == UUID_A
          and nbs[0]["title"] == "Biblia A", nbs)
    nbs = mcpm.parse_notebook_list(json.dumps(
        {"notebooks": [{"id": UUID_A, "title": "A"},
                       {"notebookId": UUID_B, "name": "B"}]}))
    check("JSON dict anidado (notebooks) con claves alternativas",
          len(nbs) == 2 and {n["id"] for n in nbs} == {UUID_A, UUID_B}
          and nbs[1]["title"] == "B", nbs)
    nbs = mcpm.parse_notebook_list(
        f"- Biblia del caso — {UUID_A}\n"
        f"* Otra investigación ({UUID_B})\n")
    check("líneas con UUID y viñetas", len(nbs) == 2
          and nbs[0]["title"] == "Biblia del caso"
          and nbs[1]["title"] == "Otra investigación", nbs)
    nbs = mcpm.parse_notebook_list(
        f"https://notebooklm.google.com/notebook/{UUID_A} mi fuente\n"
        f"/notebook/{UUID_B}\n")
    check("URLs /notebook/<id>", len(nbs) == 2 and nbs[0]["id"] == UUID_A
          and nbs[1]["id"] == UUID_B, nbs)
    nbs = mcpm.parse_notebook_list(
        f"{UUID_A}\n{UUID_A}\n")
    check("duplicados deduped", len(nbs) == 1, nbs)
    check("ids inválidos filtrados y basura → []",
          mcpm.parse_notebook_list("id corto: ab1 sin uuid") == []
          and mcpm.parse_notebook_list("") == []
          and mcpm.parse_notebook_list("nada de ids aquí") == [])


async def execute_tests():
    print("\n── S2 · execute: inyección §3 + FAIL-FAST MISSING_NOTEBOOK_ID ──")
    old_id = config.NOTEBOOKLM_NOTEBOOK_ID
    old_tools = config.NOTEBOOKLM_MCP_TOOLS
    try:
        config.NOTEBOOKLM_NOTEBOOK_ID = ""
        config.NOTEBOOKLM_MCP_TOOLS = ""
        m = mcpm.MCPClientManager()
        m._conns["notebooklm"] = _fake_conn(
            ["notebook_query", "list_notebooks", "notebook_list"], _echo_json)
        # caso EXACTO del bug: notebook_query sin id en ningún sitio
        try:
            await m.execute("notebooklm", "notebook_query", {"query": "x"})
            check("notebook_query sin id → MISSING_NOTEBOOK_ID", False)
        except mcpm.MCPManagerError as e:
            check("notebook_query sin id → MISSING_NOTEBOOK_ID",
                  e.code == "MISSING_NOTEBOOK_ID"
                  and "notebook_query" in str(e)
                  and "Listar mis Notebooks" in str(e), (e.code, str(e)[:120]))
        # inyección por param (Stage 1 del orquestador)
        r = await m.execute("notebooklm", "notebook_query", {"query": "x"},
                            notebook_id="nbquery01")
        args = json.loads(r["text"])["arguments"]
        check("id por param inyectado en arguments",
              args.get("notebook_id") == "nbquery01", args)
        # prioridad payload > param
        r = await m.execute("notebooklm", "notebook_query",
                            {"query": "x", "notebook_id": "payload77"},
                            notebook_id="param7777")
        args = json.loads(r["text"])["arguments"]
        check("payload gana a param", args.get("notebook_id") == "payload77", args)
        # fallback .env
        config.NOTEBOOKLM_NOTEBOOK_ID = "envid9911"
        r = await m.execute("notebooklm", "notebook_query", {"query": "x"})
        args = json.loads(r["text"])["arguments"]
        check("fallback .env inyectado", args.get("notebook_id") == "envid9911", args)
        config.NOTEBOOKLM_NOTEBOOK_ID = ""
        # tools de listado exentas (permitidas sin id, con warning)
        for tool in ("list_notebooks", "notebook_list"):
            r = await m.execute("notebooklm", tool, {})
            check(f"'{tool}' exenta del fail-fast (warning)",
                  r.get("ok") and any("notebook_id" in w
                                      for w in r.get("warnings", [])), r)
        # id inválido sigue rechazándose igual que antes
        try:
            await m.execute("notebooklm", "notebook_query", {},
                            notebook_id="bad id!")
            check("id inválido → INVALID_NOTEBOOK_ID intacto", False)
        except mcpm.MCPManagerError as e:
            check("id inválido → INVALID_NOTEBOOK_ID intacto",
                  e.code == "INVALID_NOTEBOOK_ID", e.code)

    finally:
        config.NOTEBOOKLM_NOTEBOOK_ID = old_id
        config.NOTEBOOKLM_MCP_TOOLS = old_tools

    print("\n── S3 · list_notebooks() + discover_notebook_id() ──")
    async def lister(tool, arguments):
        return (f"- Biblia del caso — {UUID_A}\n* Secundario {UUID_B}\n")
    m = mcpm.MCPClientManager()
    m._conns["notebooklm"] = _fake_conn(["list_notebooks"], lister)
    out = await m.list_notebooks()
    check("list_notebooks parsea y elige primera tool de listado",
          out.get("ok") and out.get("tool") == "list_notebooks"
          and len(out.get("notebooks", [])) == 2
          and out.get("first_id") == UUID_A, out)
    check("discover_notebook_id → first_id", await m.discover_notebook_id() == UUID_A)
    # fallback a la otra tool de listado si la primera no está
    m2 = mcpm.MCPClientManager()
    m2._conns["notebooklm"] = _fake_conn(["notebook_list"], lister)
    out2 = await m2.list_notebooks()
    check("fallback notebook_list cuando list_notebooks no existe",
          out2.get("tool") == "notebook_list" and out2.get("first_id") == UUID_A, out2)
    # sin NINGUNA tool de listado
    m3 = mcpm.MCPClientManager()
    m3._conns["notebooklm"] = _fake_conn(["notebook_query"], _echo_json)
    try:
        await m3.list_notebooks()
        check("sin tool de listado → TOOL_UNKNOWN", False)
    except mcpm.MCPManagerError as e:
        check("sin tool de listado → TOOL_UNKNOWN", e.code == "TOOL_UNKNOWN", e.code)
    check("discover degradado a '' sin tool de listado (nunca lanza)",
          await m3.discover_notebook_id() == "")
    # sesión Google caída → AUTH_REQUIRED surfaced
    async def auth_fail(tool, arguments):
        raise mcpm.MCPManagerError("list_notebooks: not signed in", "TOOL_ERROR")
    m4 = mcpm.MCPClientManager()
    m4._conns["notebooklm"] = _fake_conn(["list_notebooks"], auth_fail)
    try:
        await m4.list_notebooks()
        check("auth caído al listar → AUTH_REQUIRED", False)
    except mcpm.MCPManagerError as e:
        check("auth caído al listar → AUTH_REQUIRED", e.code == "AUTH_REQUIRED", e.code)
    # respuesta vacía/ilegible → LIST_EMPTY
    async def empty_list(tool, arguments):
        return "(sin notebooks)"
    m5 = mcpm.MCPClientManager()
    m5._conns["notebooklm"] = _fake_conn(["list_notebooks"], empty_list)
    try:
        await m5.list_notebooks()
        check("listado ilegible → LIST_EMPTY", False)
    except mcpm.MCPManagerError as e:
        check("listado ilegible → LIST_EMPTY", e.code == "LIST_EMPTY", e.code)
    check("discover con listado ilegible → ''",
          await m5.discover_notebook_id() == "")


def _fake_blueprint_raw(n=2):
    return {"title": "T", "hook": "H", "cta": "C", "engine": "fake",
            "scenes": [{"title": f"E{i+1}",
                        "narration": f"Narración {i+1}.",
                        "image_prompt": f"Prompt {i+1}."} for i in range(n)]}


class FakeManager:
    """Sustituto hermético con discovery dirigido (como la batería INT-023)."""

    def __init__(self, discover_id="discov2301"):
        self.discover_id = discover_id
        self.disc_calls = 0
        self.calls = []
        self._img_n = 0

    async def discover_notebook_id(self):
        self.disc_calls += 1
        return self.discover_id

    async def test_pipeline(self, service, notebook_id=None):
        self.calls.append(("test", service, "", {}))
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def execute(self, service, tool, arguments=None, timeout=None,
                      notebook_id=None, auto_connect=True):
        args = dict(arguments or {})
        if service == "notebooklm":
            nid = (args.get("notebook_id") or notebook_id
                   or getattr(config, "NOTEBOOKLM_NOTEBOOK_ID", ""))
            if nid:
                args["notebook_id"] = nid
        self.calls.append(("exec", service, tool, args))
        if service == "notebooklm":
            return {"ok": True, "text": "BIBLIA FALSA: datos del notebook."}
        if tool == "flow_upload_file":
            n = args.get("name", "ref")
            return {"ok": True, "text": f'Uploaded and named "{n}". '
                                        f'Reference it in prompts as @{{{n}}}.'}
        if tool == "flow_generate_image":
            self._img_n += 1
            return {"ok": True, "text": f"Generated 1 image(s) in 2.0s with 2 "
                                        f"({args.get('aspect')}):\n"
                                        f"/tmp/fake/gen_img_{self._img_n:03d}.png"}
        if tool == "flow_generate_video":
            return {"ok": True, "text": f'Generated video in 5.0s (100 bytes, '
                                        f'{args.get("aspect")}) with startFrame '
                                        f'"{args.get("startFrame")}":\n'
                                        f'{args.get("outFile")}'}
        return {"ok": True, "text": "ok"}


def _fresh(m):
    tmp = tempfile.mkdtemp(prefix="pipe234_")
    return po.PipelineOrchestrator(manager=m, runs_dir=Path(tmp) / "runs")


async def orchestrator_tests():
    orig_from_idea = po.script_gen.from_idea
    old_env_id = config.NOTEBOOKLM_NOTEBOOK_ID
    try:
        config.NOTEBOOKLM_NOTEBOOK_ID = ""

        print("\n── S4 · [0/3] auto-descubre el notebook_id y lo propaga ──")
        called = {"n": 0}

        async def spy(*a, **k):
            called["n"] += 1
            return _fake_blueprint_raw()

        po.script_gen.from_idea = spy
        m = FakeManager(discover_id="discov2301")
        o = _fresh(m)
        run = o.create_run("idea sin notebook id")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida done pese a UI/.env vacíos (auto-descubrimiento)",
              snap["stage"] == po.ST_DONE, (snap["stage"], snap["error_code"]))
        st = json.loads((o.runs_dir / run["run_id"] / "state.json").read_text(
            encoding="utf-8"))
        check("notebook_id auto-descubierto persistido en state.json",
              st.get("notebook_id") == "discov2301", st.get("notebook_id"))
        check("preflight [0/3] anota el auto-descubrimiento",
              "auto-descubierto" in (snap["steps"][0]["detail"] or ""),
              snap["steps"][0]["detail"])
        exec_nblm = [c for c in m.calls if c[0] == "exec" and c[1] == "notebooklm"]
        check("notebook_query recibió el id auto-descubierto",
              len(exec_nblm) == 1
              and exec_nblm[0][3].get("notebook_id") == "discov2301", exec_nblm)
        check("discovery llamado exactamente 1 vez",
              m.disc_calls == 1, m.disc_calls)
        check("Stage 2 recibió el contexto (pipeline continúa)", called["n"] == 1,
              called["n"])

        print("\n── S5 · [0/3] discovery vacío → PRE_FLIGHT_MISSING_NOTEBOOK_ID ──")
        called["n"] = 0
        po.script_gen.from_idea = spy
        m = FakeManager(discover_id="")
        o = _fresh(m)
        run = o.create_run("idea sin id y sin notebooks")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida abortada en error", snap["stage"] == po.ST_ERROR, snap["stage"])
        check("código PRE_FLIGHT_MISSING_NOTEBOOK_ID",
              snap["error_code"] == "PRE_FLIGHT_MISSING_NOTEBOOK_ID",
              snap["error_code"])
        check("detalle pide usar «Listar mis Notebooks»",
              "Listar mis Notebooks" in (snap["error_detail"] or ""),
              snap["error_detail"][:120])
        check("0 tokens: el generador de guion NO se llamó", called["n"] == 0,
              called["n"])
        check("sin llamadas notebooklm (nunca llegó a Stage 1)",
              not [c for c in m.calls if c[0] == "exec"], m.calls)

        print("\n── S6 · id explícito en UI → 0 llamadas de discovery ──")
        po.script_gen.from_idea = spy
        m = FakeManager()
        o = _fresh(m)
        run = o.create_run("idea", notebook_id="explicit99")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida done con id explícito", snap["stage"] == po.ST_DONE,
              snap["stage"])
        check("discovery NO llamado (0)", m.disc_calls == 0, m.disc_calls)
        exec_nblm = [c for c in m.calls if c[0] == "exec" and c[1] == "notebooklm"]
        check("notebook_query usó el id de la UI", exec_nblm
              and exec_nblm[0][3].get("notebook_id") == "explicit99", exec_nblm)

        print("\n── S7 · fallback .env propagado al estado (visibilidad) ──")
        config.NOTEBOOKLM_NOTEBOOK_ID = "envid23011"
        po.script_gen.from_idea = spy
        m = FakeManager()
        o = _fresh(m)
        run = o.create_run("idea")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        st = json.loads((o.runs_dir / run["run_id"] / "state.json").read_text(
            encoding="utf-8"))
        check("env NOTEBOOKLM_NOTEBOOK_ID propagado al state.json",
              st.get("notebook_id") == "envid23011", st.get("notebook_id"))
        check("env presente → discovery NO llamado", m.disc_calls == 0, m.disc_calls)
        config.NOTEBOOKLM_NOTEBOOK_ID = ""
    finally:
        po.script_gen.from_idea = orig_from_idea
        config.NOTEBOOKLM_NOTEBOOK_ID = old_env_id


class FakeListManager:
    """Sustituto del manager para los endpoints /api/mcp/* a nivel HTTP."""

    def __init__(self, nbs=None, error=None):
        self.nbs = nbs if nbs is not None else [
            {"id": UUID_A, "title": "Biblia HTTP"}, {"id": UUID_B, "title": "B"}]
        self.error = error

    async def list_notebooks(self, notebook_id=None):
        if self.error:
            raise mcpm.MCPManagerError(self.error[1], self.error[0])
        return {"ok": True, "tool": "list_notebooks", "notebooks": self.nbs,
                "first_id": self.nbs[0]["id"] if self.nbs else ""}

    async def execute(self, service, tool, arguments=None, timeout=None,
                      notebook_id=None, auto_connect=True):
        raise mcpm.MCPManagerError(
            f"la tool '{tool}' requiere notebook_id y está ausente", "MISSING_NOTEBOOK_ID")


async def endpoint_tests():
    print("\n── S8 · endpoints HTTP: /mcp/list-notebooks + propagación en /pipeline/run ──")
    import httpx
    import main as _main
    from services import mcp_manager as mcpm_mod  # mismo módulo que importa main

    orig_mgr = mcpm_mod.manager
    po.script_gen.from_idea = _spy_ok
    m = FakeManager()
    orig_pipe_mgr = po.orchestrator.manager
    orig_dir = po.orchestrator.runs_dir
    orig_busy = po.orchestrator._busy
    po.orchestrator.manager = m
    po.orchestrator.runs_dir = Path(tempfile.mkdtemp(prefix="pipe234_ep_")) / "runs"
    old_env_id = config.NOTEBOOKLM_NOTEBOOK_ID
    config.NOTEBOOKLM_NOTEBOOK_ID = ""
    try:
        mcpm_mod.manager = FakeListManager()
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/mcp/list-notebooks", json={},
                             headers={"Origin": "http://testserver"})
            js = r.json()
            check("POST /mcp/list-notebooks 200", r.status_code == 200, r.text[:200])
            check("dropdown recibe notebooks + first_id",
                  len(js.get("notebooks", [])) == 2
                  and js.get("first_id") == UUID_A, js)
            mcpm_mod.manager = FakeListManager(
                error=("LIST_EMPTY", "listado de notebooks vacío"))
            r = await c.post("/api/mcp/list-notebooks", json={},
                             headers={"Origin": "http://testserver"})
            check("list-notebooks con listado vacío → 502 [LIST_EMPTY]",
                  r.status_code == 502 and "LIST_EMPTY" in r.text, r.text[:160])
            mcpm_mod.manager = FakeListManager()
            r = await c.post("/api/mcp/execute",
                             json={"service": "notebooklm", "tool": "notebook_query",
                                   "arguments": {"query": "x"}},
                             headers={"Origin": "http://testserver"})
            check("execute sin id a nivel HTTP → 502 MISSING_NOTEBOOK_ID",
                  r.status_code == 502 and "MISSING_NOTEBOOK_ID" in r.text,
                  r.text[:160])
            mcpm_mod.manager = orig_mgr

            # ESCENARIO EXACTO DEL BUG a nivel HTTP: /pipeline/run SIN notebook_id
            r = await c.post("/api/pipeline/run",
                             json={"idea": "historia del abrigo", "format": "short"},
                             headers={"Origin": "http://testserver"})
            check("POST /pipeline/run sin id → 200", r.status_code == 200,
                  r.text[:200])
            rid = r.json().get("run_id", "")
            await po.orchestrator.wait(rid, timeout=30.0)
            r = await c.get("/api/pipeline/status", params={"run_id": rid})
            js = r.json()
            check("corrida HTTP done con id AUTO-DESCUBIERTO",
                  js.get("stage") == "done"
                  and js.get("notebook_id") == "discov2301", r.text[:300])
            check("preflight HTTP anota auto-descubrimiento",
                  "auto-descubierto" in ((js.get("steps") or [{}])[0].get("detail") or ""),
                  (js.get("steps") or [{}])[0].get("detail"))

            # con id explícito en el payload (botón «🚀 Run Full Pipeline»)
            r = await c.post("/api/pipeline/run",
                             json={"idea": "otra", "notebook_id": "uidpayload9"},
                             headers={"Origin": "http://testserver"})
            check("POST /pipeline/run con payload → 200 y eco del id",
                  r.status_code == 200
                  and r.json().get("notebook_id") == "uidpayload9", r.text[:200])
            rid2 = r.json().get("run_id", "")
            disc_before = m.disc_calls  # la corrida anterior ya descubrió 1 vez
            await po.orchestrator.wait(rid2, timeout=30.0)
            st2 = json.loads((po.orchestrator.runs_dir / rid2 / "state.json")
                             .read_text(encoding="utf-8"))
            check("payload id respetado en el estado (sin discovery)",
                  m.disc_calls == disc_before
                  and st2.get("notebook_id") == "uidpayload9",
                  (m.disc_calls, disc_before, st2.get("notebook_id")))
    finally:
        mcpm_mod.manager = orig_mgr
        po.orchestrator.manager = orig_pipe_mgr
        po.orchestrator.runs_dir = orig_dir
        po.orchestrator._busy = orig_busy
        config.NOTEBOOKLM_NOTEBOOK_ID = old_env_id


async def _spy_ok(*a, **k):
    return _fake_blueprint_raw()


def main() -> int:
    print("=" * 60)
    print("BATERÍA INT-023.4 · notebook_id: propagación + auto-descubrimiento")
    print("=" * 60)
    parser_tests()
    asyncio.run(execute_tests())
    asyncio.run(orchestrator_tests())
    asyncio.run(endpoint_tests())
    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
