#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-023 · Pipeline Orchestrator (NotebookLM → Agente → Flow)

Cubre el handoff completo de las 3 etapas con mocks herméticos (cero red,
cero Chrome, cero LLM real):
  · Pre-flight gatekeeper: aborta sin gastar tokens si un MCP no está
    Connected & Authenticated (PRE_FLIGHT_AUTH / PRE_FLIGHT_NOTEBOOKLM /
    PRE_FLIGHT_FLOW) y NO llama al generador de guion.
  · Stage 1: extracción de contexto vía mcp_manager (notebookId dinámico),
    context.md persistido; TOOL_UNKNOWN surfaced con código estable.
  · Stage 2: el blueprint lo genera el motor de SIEMPRE (script_gen se
    parchea como módulo — su plantilla y sanitización NO se tocan), con el
    contexto de NotebookLM INYECTADO en la idea.
  · Stage 3: referencia de personaje @{personaje} subida UNA vez y usada por
    todas las escenas; startFrame derivado del asset generado; aspect por
    formato; fallo de escena NO aborta (PARTIAL_FAILURES + scene_id
    registrado + assets intactos) y retry-scenes re-despacha SOLO las
    fallidas sin repetir Stage 1/2.
  · Estado persistente (state.json atómico) y endpoints REST del panel
    (/api/pipeline/run|status|retry-scenes) vía ASGI in-process.

Convención del repo: script stdlib (sin pytest), 0 dependencias externas.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


class FakeManager:
    """Sustituto hermético de MCPClientManager con comportamiento dirigido."""

    def __init__(self, nblm_ok=True, flow_ok=True, fail_video_at=None,
                 context_error=None, flow_dies_in_stage3=False,
                 flow_state=None):
        self.nblm_ok = nblm_ok
        self.flow_ok = flow_ok
        self.flow_state = flow_state or ("connected" if flow_ok else "auth_required")
        self.fail_video_at = fail_video_at
        self.context_error = context_error      # (code, msg) o None
        self.flow_dies_in_stage3 = flow_dies_in_stage3
        self.calls = []                          # (kind, service, tool, arguments)
        self._probe_n = 0                        # nº de test_pipeline de flow
        self._img_n = 0
        self._vid_n = 0

    async def test_pipeline(self, service, notebook_id=None):
        self.calls.append(("test", service, "", {}))
        if service == "notebooklm":
            return {"service": service, "ok": self.nblm_ok,
                    "state": "connected" if self.nblm_ok else "auth_required",
                    "auth": "ok" if self.nblm_ok else "auth_required",
                    "detail": "" if self.nblm_ok else "Not signed in"}
        self._probe_n += 1
        ok = self.flow_ok and not (self.flow_dies_in_stage3 and self._probe_n > 1)
        state = self.flow_state if ok else (
            self.flow_state if self.flow_state != "connected" and not ok else "connected")
        return {"service": service, "ok": ok,
                "state": state if not ok else "connected",
                "auth": "ok" if ok else self.flow_state,
                "detail": "" if ok else "Not signed in", "browser_up": ok}

    async def execute(self, service, tool, arguments=None, timeout=None,
                      notebook_id=None, auto_connect=True):
        args = dict(arguments or {})
        # imita la inyección §3 real de mcp_manager.execute (payload → param → .env)
        if service == "notebooklm":
            nid = (args.get("notebook_id") or notebook_id
                   or getattr(config, "NOTEBOOKLM_NOTEBOOK_ID", ""))
            if nid:
                args["notebook_id"] = nid
        self.calls.append(("exec", service, tool, args))
        if service == "notebooklm":
            if self.context_error:
                raise mcpm.MCPManagerError(self.context_error[1],
                                           self.context_error[0])
            return {"ok": True, "text": "BIBLIA FALSA: personaje alto, abrigo "
                                        "rojo, datos del caso, arco en 3 actos."}
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
            self._vid_n += 1
            if self.fail_video_at and self._vid_n == self.fail_video_at:
                raise mcpm.MCPManagerError("Flow video generation failed: boom",
                                           "TOOL_ERROR")
            return {"ok": True, "text": f'Generated video in 5.0s (100 bytes, '
                                        f'{args.get("aspect")}) with startFrame '
                                        f'"{args.get("startFrame")}":\n'
                                        f'{args.get("outFile")}'}
        return {"ok": True, "text": "ok"}


def _fake_blueprint_raw(n=3):
    return {
        "title": "El caso que nadie contó", "hook": "Todo empezó un martes…",
        "cta": "Sígueme para la parte 2", "engine": "fake",
        "scenes": [{"title": f"Escena {i+1}",
                    "narration": f"Narración de la escena {i+1} con datos del notebook.",
                    "image_prompt": f"Plano de la escena {i+1}, personaje con abrigo rojo."}
                   for i in range(n)],
    }


def _fresh(**kw):
    m = FakeManager(**kw)
    tmp = tempfile.mkdtemp(prefix="pipe23_")
    o = po.PipelineOrchestrator(manager=m, runs_dir=Path(tmp) / "runs")
    return m, o


async def stage_tests():
    orig_from_idea = po.script_gen.from_idea

    print("\n── S1 · create_run: validación y single-flight ──")
    m, o = _fresh()
    try:
        try:
            o.create_run("")
            check("idea vacía rechazada", False)
        except po.PipelineError as e:
            check("idea vacía rechazada", e.code == "IDEA_REQUIRED", e.code)
        o._busy = "run_x"
        try:
            o.create_run("idea")
            check("single-flight en create_run", False)
        except po.PipelineError as e:
            check("single-flight en create_run", e.code == "PIPELINE_BUSY", e.code)
        o._busy = None
        run = o.create_run("historia del abrigo rojo", notebook_id="pipeid23",
                           fmt="short")
        check("run creado con id saneado", po._RUN_ID_RE.match(run["run_id"]) is not None,
              run["run_id"])
        check("etapas inicializadas", [s["stage"] for s in run["steps"]] ==
              ["preflight", "stage1_context", "stage2_blueprint", "stage3_dispatch"],
              run["steps"])
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S2 · pre-flight NotebookLM caído → aborta SIN gastar tokens ──")
    po.script_gen.from_idea = orig_from_idea
    called = {"n": 0, "s3_base": 0}

    async def spy_from_idea(*a, **k):
        called["n"] += 1
        return _fake_blueprint_raw()

    m, o = _fresh(nblm_ok=False)
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("idea", notebook_id="pipeid23")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida en error", snap["stage"] == po.ST_ERROR, snap["stage"])
        check("código PRE_FLIGHT_AUTH (auth_required detectado)",
              snap["error_code"] == "PRE_FLIGHT_AUTH", snap["error_code"])
        check("el generador de guion NO se llamó (0 tokens)", called["n"] == 0,
              called["n"])
        check("estado persistido en state.json",
              (o.runs_dir / run["run_id"] / "state.json").is_file())
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S3 · pre-flight Flow caído → aborta sin gastar tokens ──")
    m, o = _fresh(flow_ok=False)
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("idea")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida en error por Flow", snap["stage"] == po.ST_ERROR, snap["stage"])
        check("auth_required del fake → PRE_FLIGHT_AUTH",
              snap["error_code"] == "PRE_FLIGHT_AUTH", snap["error_code"])
        check("guion no generado", called["n"] == called["s3_base"], called["n"])
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S3b · Flow desconectado (no auth) → PRE_FLIGHT_FLOW ──")
    m, o = _fresh(flow_ok=False, flow_state="disconnected")
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("idea")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("código PRE_FLIGHT_FLOW (no auth)",
              snap["error_code"] == "PRE_FLIGHT_FLOW", snap["error_code"])
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S4 · happy path: 3 escenas con personaje consistente ──")
    m, o = _fresh()
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("el abrigo rojo", notebook_id="pipeid23", fmt="short")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida done 100%", snap["stage"] == po.ST_DONE
              and snap["progress_pct"] == 100, snap["stage"])
        check("3 escenas done", all(s["status"] == "done"
                                    for s in snap["scenes"]), snap["scenes"])
        rd = o.runs_dir / run["run_id"]
        check("context.md persistido", (rd / "context.md").is_file())
        check("blueprint.json persistido", (rd / "blueprint.json").is_file())
        bp = json.loads((rd / "blueprint.json").read_text(encoding="utf-8"))
        check("blueprint anota notebookId", bp.get("notebook_id") == "pipeid23",
              bp.get("notebook_id"))
        # handoff Stage1→Stage2: la idea enriquecida lleva el contexto del notebook
        exec_calls = [c for c in m.calls if c[0] == "exec"]
        nblm_calls = [c for c in exec_calls if c[1] == "notebooklm"]
        check("Stage 1 consultó notebooklm con notebookId dinámico",
              len(nblm_calls) == 1 and nblm_calls[0][3].get("notebook_id") == "pipeid23",
              nblm_calls)
        # Stage 2 recibió el contexto (la idea enriquecida va en from_idea)
        check("from_idea llamado exactamente 1 vez (handoff 1→2)",
              called["n"] == 1, called["n"])
        # Stage 3: consistencia de personaje
        ups = [c for c in exec_calls if c[2] == "flow_upload_file"]
        check("referencia de personaje subida UNA vez",
              len(ups) == 1 and ups[0][3].get("name") == "personaje", ups)
        vids = [c for c in exec_calls if c[2] == "flow_generate_video"]
        check("3 videos despachados", len(vids) == 3, len(vids))
        check("todos los videos en 9:16 (format short)",
              all(c[3].get("aspect") == "9:16" for c in vids), [c[3].get("aspect") for c in vids])
        frames = [c[3].get("startFrame") for c in vids]
        check("startFrame = asset generado por escena (distintos)",
              len(set(frames)) == 3 and all(f.startswith("gen_img_") for f in frames),
              frames)
        imgs = [c for c in exec_calls if c[2] == "flow_generate_image"]
        check("start-frames citan a @{personaje} (consistencia)",
              all("@{personaje}" in c[3].get("prompt", "") for c in imgs[1:]),
              [c[3].get("prompt", "")[:40] for c in imgs])
        check("vout scene_sN.mp4 en el dir de la corrida",
              all(c[3].get("outFile", "").endswith(f"scene_s{i+1}.mp4")
                  for i, c in enumerate(vids)), [c[3].get("outFile") for c in vids])
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S5 · escena 2 falla → PARTIAL_FAILURES, assets intactos ──")
    m, o = _fresh(fail_video_at=2)   # 2ª llamada a flow_generate_video (escena s2)
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("idea", fmt="short")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida done CON fallos parciales",
              snap["stage"] == po.ST_DONE and snap["error_code"] == "PARTIAL_FAILURES",
              (snap["stage"], snap["error_code"]))
        st_by_id = {s["scene_id"]: s for s in snap["scenes"]}
        check("s1 y s3 done", st_by_id["s1"]["status"] == "done"
              and st_by_id["s3"]["status"] == "done",
              {k: v["status"] for k, v in st_by_id.items()})
        check("s2 failed con detail del error", st_by_id["s2"]["status"] == "failed"
              and "TOOL_ERROR" in st_by_id["s2"]["detail"], st_by_id["s2"])
        check("failed_scene_ids = [s2]", snap["failed_scene_ids"] == ["s2"],
              snap["failed_scene_ids"])
        check("asset de s1 intacto (video_file registrado)",
              st_by_id["s1"]["video_file"].endswith("scene_s1.mp4"),
              st_by_id["s1"]["video_file"])
        o._busy = "otra_corrida"
        try:
            await o.retry_scenes(run["run_id"])
            check("retry bloqueado si hay otra corrida en marcha", False)
        except po.PipelineError as e:
            check("retry bloqueado si hay otra corrida en marcha",
                  e.code == "PIPELINE_BUSY", e.code)
        o._busy = None
        retry_calls_before = len([c for c in m.calls if c[0] == "exec"])
        from_idea_before = called["n"]

        print("\n── S6 · retry-scenes: SOLO s2, sin repetir Stage 1/2 ──")
        out = await o.retry_scenes(run["run_id"])
        check("retry deja la corrida done 100%",
              out["stage"] == po.ST_DONE and out["progress_pct"] == 100,
              (out["stage"], out["progress_pct"]))
        st_by_id = {s["scene_id"]: s for s in out["scenes"]}
        check("s2 done tras retry", st_by_id["s2"]["status"] == "done", st_by_id["s2"])
        check("failed_scene_ids limpio tras retry OK",
              out["failed_scene_ids"] == [], out["failed_scene_ids"])
        exec_after = [c for c in m.calls if c[0] == "exec"][retry_calls_before:]
        check("retry NO re-genera guion (sin delta de from_idea)",
              called["n"] == from_idea_before, (called["n"], from_idea_before))
        check("retry NO re-extrae contexto de NotebookLM",
              not any(c[1] == "notebooklm" for c in exec_after), exec_after)
        vids_after = [c for c in exec_after if c[2] == "flow_generate_video"]
        check("retry despacha exactamente 1 video (s2)", len(vids_after) == 1,
              len(vids_after))
        check("retry NO re-sub la referencia (cacheada)",
              not any(c[2] == "flow_upload_file" for c in exec_after), exec_after)
        check("attempts de s2 = 2", st_by_id["s2"]["attempts"] == 2,
              st_by_id["s2"]["attempts"])
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S7 · errores limpios: run inexistente, sin blueprint, sin fallidas ──")
    m, o = _fresh()
    try:
        try:
            o.get_status("run_inexistente")
            check("run inexistente → RUN_NOT_FOUND", False)
        except po.PipelineError as e:
            check("run inexistente → RUN_NOT_FOUND", e.code == "RUN_NOT_FOUND", e.code)
        run = o.create_run("idea")
        try:
            await o.retry_scenes(run["run_id"])
            check("retry sin blueprint → RETRY_NO_BLUEPRINT", False)
        except po.PipelineError as e:
            check("retry sin blueprint → RETRY_NO_BLUEPRINT",
                  e.code == "RETRY_NO_BLUEPRINT", e.code)
    finally:
        pass

    print("\n── S8 · Flow se cae EN Stage 3 → escenas failed y reintegrables ──")
    m, o = _fresh(flow_dies_in_stage3=True)
    po.script_gen.from_idea = spy_from_idea
    try:
        run = o.create_run("idea")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("corrida en error FLOW_NOT_CONNECTED",
              snap["stage"] == po.ST_ERROR and snap["error_code"] == "FLOW_NOT_CONNECTED",
              (snap["stage"], snap["error_code"]))
        check("escenas pendientes marcadas failed (reintegrables)",
              all(s["status"] == "failed" for s in snap["scenes"]),
              [s["status"] for s in snap["scenes"]])
        check("blueprint intacto para el retry",
              (o.runs_dir / run["run_id"] / "blueprint.json").is_file())
    finally:
        po.script_gen.from_idea = orig_from_idea

    print("\n── S9 · tool de contexto ausente → error surfaced con código ──")
    m, o = _fresh(context_error=("TOOL_UNKNOWN",
                                 "el servidor no expone 'query_notebook' (tools: list_notebooks)"))
    po.script_gen.from_idea = spy_from_idea
    n_before_s9 = called["n"]
    try:
        run = o.create_run("idea")
        await o.start_run(run["run_id"])
        await o.wait(run["run_id"])
        snap = o.get_status(run["run_id"])
        check("CONTEXT_EXTRACTION_FAILED surfaced",
              snap["error_code"] == "CONTEXT_EXTRACTION_FAILED"
              and "TOOL_UNKNOWN" in snap["error_detail"],
              (snap["error_code"], snap["error_detail"][:80]))
        check("0 tokens gastados en la corrida",
              called["n"] == n_before_s9, (called["n"], n_before_s9))
    finally:
        po.script_gen.from_idea = orig_from_idea


async def endpoint_tests():
    print("\n── S10 · endpoints REST del panel (ASGI in-process) ──")
    import httpx
    import main as _main

    po.script_gen.from_idea = _spy_ok
    m = FakeManager()
    orig_mgr = po.orchestrator.manager
    orig_dir = po.orchestrator.runs_dir
    orig_busy = po.orchestrator._busy
    po.orchestrator.manager = m
    po.orchestrator.runs_dir = Path(tempfile.mkdtemp(prefix="pipe23_ep_")) / "runs"
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/run", json={"idea": ""},
                             headers={"Origin": "http://testserver"})
            check("POST /run sin idea → 400", r.status_code == 400, r.text[:120])
            r = await c.post("/api/pipeline/run",
                             json={"idea": "historia del abrigo", "format": "short"},
                             headers={"Origin": "http://testserver"})
            check("POST /run 200", r.status_code == 200, r.text[:200])
            rid = r.json().get("run_id", "")
            check("run_id devuelto", bool(rid), r.text[:120])
            await po.orchestrator.wait(rid, timeout=30.0)
            r = await c.get("/api/pipeline/status",
                            params={"run_id": rid})
            js = r.json()
            check("GET /status 200 con etapas", r.status_code == 200
                  and js.get("stage") == "done"
                  and len(js.get("steps", [])) == 4, r.text[:300])
            check("status trae escenas y progreso",
                  len(js.get("scenes", [])) == 3 and js.get("progress_pct") == 100,
                  (len(js.get("scenes", [])), js.get("progress_pct")))
            r = await c.get("/api/pipeline/status")
            check("GET /status sin run_id → última corrida",
                  r.status_code == 200 and r.json().get("run_id") == rid,
                  r.text[:120])
            r = await c.get("/api/pipeline/status", params={"run_id": "nope"})
            check("GET /status run desconocido → 404", r.status_code == 404,
                  r.text[:120])
            r = await c.post("/api/pipeline/retry-scenes", json={"run_id": "nope"},
                             headers={"Origin": "http://testserver"})
            check("POST /retry-scenes run desconocido → 400", r.status_code == 400,
                  r.text[:120])
            r = await c.post("/api/pipeline/retry-scenes",
                             json={"run_id": rid},
                             headers={"Origin": "http://testserver"})
            check("POST /retry-scenes sin fallidas → 400 NO_FAILED_SCENES",
                  r.status_code == 400 and "NO_FAILED_SCENES" in r.text,
                  r.text[:160])
    finally:
        po.orchestrator.manager = orig_mgr
        po.orchestrator.runs_dir = orig_dir
        po.orchestrator._busy = orig_busy


async def _spy_ok(*a, **k):
    return _fake_blueprint_raw()


def main() -> int:
    print("=" * 60)
    print("BATERÍA INT-023 · Pipeline Orchestrator (NLM → Agente → Flow)")
    print("=" * 60)
    asyncio.run(stage_tests())
    asyncio.run(endpoint_tests())
    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
