#!/usr/bin/env python3
"""Batería HANDS OPERADORES V1.0 — desktop operator (mock y físico con
consentimiento), flow operator con driver mock, adaptador al Flow Bridge
EXISTENTE contra servidor HTTP simulado con el contrato REAL, contrato de
integración futura NOT CONNECTED, mock environment y validaciones finales
(self-audit §40 + clean-room §42).

Cubre: apertura/cierre/enfoque de apps, input (click/teclar/paste/hotkey/
scroll/drag), filesystem dentro del workspace, EXECUTE_ALLOWED con handlers
del entorno simulado, captura a evidencia (§22); PhysicalDesktopBackend con
triple candado (consentimiento + command_map + allowlist) y MATURIDAD
NOT_VERIFIED (§35); FlowOperator ciclo OPEN_FLOW→…→REPORT_RESULT sin
inventar prompts (§15) con verificación de medios (§23) e idempotencia
(§26); ExtensionBridgeDriver hablando SOLO el contrato HTTP congelado
(enqueue/status) con gate enabled=false ⇒ BLOCKED (§37); HAND_REQUEST/
HAND_RESULT schemas; MockEnvironment (§34); SELF-AUDIT completo PASS y
CLEAN-ROOM completo PASS.

Uso:  cd yt_automation_v2 && python3 tests/test_hands_operators.py
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services.hands import (                                # noqa: E402
    BlockedError, ErrorCode, FakeClock, FlowJobSpec, HandsError,
    MockEnvironment, MockFlowDriver, NotConnectedAdapter, Op,
    PhysicalDesktopBackend, State, TargetSpec, verify_file,
)
from services.hands.permissions import CommandRule, PermissionModel    # noqa: E402
from services.hands.cleanroom import run_cleanroom          # noqa: E402
from services.hands.flow_operator import ExtensionBridgeDriver      # noqa: E402
from services.hands.future_integration import (             # noqa: E402
    INTEGRATION_STATUS, integration_checklist, make_hand_result,
    validate_hand_request,
)
from services.hands.selfaudit import run_selfaudit          # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def expect_error(fn, code: ErrorCode) -> bool:
    try:
        fn()
        return False
    except HandsError as err:
        return err.code is code


def status_of(result) -> str:
    return result.status.value


# ══ 1. MOCK ENVIRONMENT + DESKTOP OPERATOR (§13/§34) ═════════════════════
print("── 1. MockEnvironment + DesktopOperator completo")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "mockws")
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        r_open = h.desktop.open_app("notepad-mock")
        check("OPEN app mock ⇒ COMPLETED", r_open.status is State.COMPLETED)
        r_focus = h.desktop.focus_window("notepad-mock")
        check("FOCUS ventana ⇒ COMPLETED", r_focus.status is State.COMPLETED)
        target = TargetSpec(semantic="notepad-mock.prompt_input")
        r_click = h.desktop.click(target)
        check("CLICK semántico ⇒ COMPLETED",
              r_click.status is State.COMPLETED
              and r_click.result.get("target_match", {}).get("strategy")
              == "semantic")
        r_type = h.desktop.type_text(target, "texto de prueba")
        obs = h.desktop.observe()
        _el = obs.find_element(lambda e: e.semantic == "notepad-mock.prompt_input")
        check("TYPE escribe en el elemento observado",
              r_type.status is State.COMPLETED and _el is not None
              and (_el.extra or {}).get("value") == "texto de prueba")
        env.desktop_mock.clipboard = "portapapeles"
        r_paste = h.desktop.paste(target)
        _el2 = h.desktop.observe().find_element(
            lambda e: e.semantic == "notepad-mock.prompt_input")
        check("PASTE usa el clipboard del entorno",
              r_paste.status is State.COMPLETED
              and (_el2.extra or {}).get("value") == "texto de pruebaportapapeles")
        check("HOTKEY/SCROLL/DRAG operan",
              h.desktop.hotkey("ctrl+s").status is State.COMPLETED
              and h.desktop.scroll(3).status is State.COMPLETED
              and h.desktop.drag(TargetSpec(semantic="notepad-mock.send_button"),
                                 TargetSpec(semantic="notepad-mock.status_bar")
                                 ).status is State.COMPLETED)
        src = env.seed_file("workspace", "origen.txt", b"datos")
        dst = env.runtime.workspace.path_for("workspace", "destino.txt")
        r_copy = h.desktop.copy_file(str(src), str(dst))
        check("COPY dentro del workspace ⇒ COMPLETED + verify file_exists",
              r_copy.status is State.COMPLETED
              and verify_file(dst).verdict.value == "PASS")
        fuera = Path(tmp) / "fuera.txt"
        fuera.write_text("x")
        r_out = h.desktop.copy_file(str(fuera), str(dst) + ".2")
        check("COPY desde fuera del workspace ⇒ BLOCKED (§18)",
              r_out.status is State.BLOCKED)
        env.desktop_mock.command_handlers["mock-cmd"] = (
            lambda argv: {"returncode": 0, "stdout": "hecho"})
        env.runtime.permissions.commands = (
            CommandRule(binary="mock-cmd", allow_no_args=True),)
        r_exec = h.desktop.execute_allowed(["mock-cmd"])
        check("EXECUTE_ALLOWED con handler del entorno ⇒ COMPLETED",
              r_exec.status is State.COMPLETED
              and r_exec.result.get("action_outcome", {}).get("stdout") == "hecho")
        r_exec2 = h.desktop.execute_allowed(["desconocido-bin"])
        check("EXECUTE_ALLOWED binario fuera de allowlist ⇒ BLOCKED (§16)",
              r_exec2.status is State.BLOCKED)
        env.runtime.permissions.commands = (
            CommandRule(binary="sin-handler", allow_no_args=True),)
        r_exec3 = h.desktop.execute_allowed(["sin-handler"])
        check("binario permitido sin handler en el mock ⇒ FAILED honesto",
              r_exec3.status is State.FAILED
              and r_exec3.errors[0]["code"] == "ACTION_FAILED")
        cap = h.desktop.capture_to_evidence(h.evidence)
        check("CAPTURE a evidencia con hash (§22)",
              cap.get("screenshot") is not None
              and len(cap.get("sha256", "")) == 64)
        r_close = h.desktop.close_app("notepad-mock")
        check("CLOSE app ⇒ COMPLETED", r_close.status is State.COMPLETED)

    # caos: ventana desaparece antes del click (§33)
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        h.desktop.open_app("notepad-mock")
        env.chaos_window_disappears("notepad-mock — Ventana principal")
        r_ghost = h.desktop.click(TargetSpec(semantic="notepad-mock.prompt_input"))
        check("CAOS ventana desaparece ⇒ FAILED TARGET_NOT_FOUND",
              r_ghost.status is State.FAILED
              and r_ghost.errors[0]["code"] == "TARGET_NOT_FOUND")

# ══ 2. PHYSICAL DESKTOP BACKEND — triple candado (§35) ═══════════════════
print("── 2. PhysicalDesktopBackend: consentimiento + command_map + allowlist")
def _PM():
    return PermissionModel.from_dict({
        "filesystem_roots": ["/tmp"],
        "commands": [CommandRule(binary="xdotool",
                                 allowed_prefixes=(("key",), ("click",)))],
    })


check("MATURIDAD declarada NOT_VERIFIED (§35/§43)",
      PhysicalDesktopBackend.MATURITY == "NOT_VERIFIED")
check("sin consentimiento ⇒ PERMISSION_DENIED", expect_error(
    lambda: PhysicalDesktopBackend(
        consent_token="", expected_consent="token-humano",
        command_map={}, permissions=_PM(), root_dir="/tmp"),
    ErrorCode.PERMISSION_DENIED))
check("consentimiento incorrecto ⇒ PERMISSION_DENIED", expect_error(
    lambda: PhysicalDesktopBackend(
        consent_token="otro", expected_consent="token-humano",
        command_map={}, permissions=_PM(), root_dir="/tmp"),
    ErrorCode.PERMISSION_DENIED))


_phys = PhysicalDesktopBackend(
    consent_token="token-humano", expected_consent="token-humano",
    command_map={"OPEN": ["xdotool", "key", "{application}"]},
    permissions=_PM(), root_dir="/tmp")
check("observación física honesta (state=physical_not_verified)",
      _phys.observe().state == "physical_not_verified")
check("operación sin mapeo declarado ⇒ PERMISSION_DENIED", expect_error(
    lambda: _phys.perform("CLICK", None, {}), ErrorCode.PERMISSION_DENIED))
check("operación mapeada sin executor ⇒ BLOCKED (nada toca el PC)", expect_error(
    lambda: _phys.perform("OPEN", None, {"application": "notepad"}),
    ErrorCode.BLOCKED))
_argv_registrados = []


def _fake_executor(argv, timeout_s):
    _argv_registrados.append((argv, timeout_s))
    return {"returncode": 0, "stdout": "ok"}


_phys2 = PhysicalDesktopBackend(
    consent_token="token-humano", expected_consent="token-humano",
    command_map={"OPEN": ["xdotool", "key", "{application}"]},
    permissions=_PM(), root_dir="/tmp", executor=_fake_executor)
_out = _phys2.perform("OPEN", None, {"application": "notepad", "_timeout_s": 5.0})
check("con consentimiento+mapeo+allowlist+executor: argv templado y ejecutado",
      _out.get("returncode") == 0
      and _argv_registrados == [(["xdotool", "key", "notepad"], 5.0)])
_phys2_denied = PhysicalDesktopBackend(
    consent_token="token-humano", expected_consent="token-humano",
    command_map={"OPEN": ["bash", "-c", "{application}"]},
    permissions=_PM(), root_dir="/tmp", executor=_fake_executor)
check("mapeo a binario NO allowlisted ⇒ PERMISSION_DENIED (deny-by-default)",
      expect_error(lambda: _phys2_denied.perform(
          "OPEN", None, {"application": "rm -rf"}), ErrorCode.PERMISSION_DENIED))

# ══ 3. FLOW OPERATOR con driver mock (§14/§15/§23/§26) ═══════════════════
print("── 3. FlowOperator: ciclo completo, disciplina §15 y caos")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "flowws")
    with env.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        check("OPEN_FLOW ⇒ COMPLETED", f.open_flow().status is State.COMPLETED)
        check("OPEN_PROJECT ⇒ COMPLETED",
              f.open_project("proj-1").status is State.COMPLETED)
        job = FlowJobSpec(kind="image", project_id="proj-1", scene_number=1,
                          prompt="PROMPT EXTERNO (viene de la capa creativa)")
        r_sp = f.set_prompt(job)
        check("SET_PROMPT registra prompt EXTERNO (§15)",
              r_sp.status is State.COMPLETED
              and r_sp.result.get("prompt_source") != "hands"
              and r_sp.result.get("prompt_chars") == len(job.prompt))
        r_bad = f.set_prompt(FlowJobSpec(kind="image", project_id="proj-1",
                                         scene_number=2, prompt="   "))
        check("prompt vacío ⇒ FAILED VALIDATION_ERROR (HANDS no inventa)",
              r_bad.status is State.FAILED
              and r_bad.errors[0]["code"] == "VALIDATION_ERROR")
        check("SET_CONFIGURATION ⇒ COMPLETED",
              f.set_configuration({"modo": "mock"}).status is State.COMPLETED)
        r_start = f.start_generation()
        check("START_GENERATION ⇒ COMPLETED con handle",
              r_start.status is State.COMPLETED
              and r_start.result.get("handle", {}).get("handle_id"))
        _handle = r_start.result["handle"]
        r_wait = f.wait_generation(_handle)
        check("WAIT_GENERATION ⇒ COMPLETED", r_wait.status is State.COMPLETED)
        r_detect = f.detect_result(_handle)
        check("DETECT_RESULT ve status done",
              r_detect.status is State.COMPLETED
              and r_detect.result.get("status") == "done")
        r_dl = f.download_result(_handle, dest_name="escena1.png")
        check("DOWNLOAD_RESULT verifica magic bytes PNG (§23)",
              r_dl.status is State.COMPLETED
              and r_dl.verification.get("verdict") == "PASS"
              and r_dl.verification.get("media_kind") == "png")
        r_dl2 = f.download_result(_handle, dest_name="escena1.png")
        check("re-descarga idempotente evitada (§26)",
              r_dl2.status is State.COMPLETED
              and bool(r_dl2.result.get("skipped")))
        r_ver = f.verify_result(r_dl.result["downloaded"], kind="image")
        check("VERIFY_RESULT ⇒ COMPLETED", r_ver.status is State.COMPLETED)
        r_rep = f.report_result(_handle,
                                asset_path=r_dl.result.get("downloaded"))
        check("REPORT_RESULT ⇒ COMPLETED con reporte estructurado",
              r_rep.status is State.COMPLETED
              and r_rep.result.get("report", {}).get("driver") == "mock")
        _recs_flow = h.evidence.query(action="SET_PROMPT")
        check("SET_PROMPT queda en evidencia con prompt externo (§15/§21)",
              len(_recs_flow) >= 1
              and any((r.get("observed_state") or {}).get("prompt_chars")
                      for r in _recs_flow))

    # caos Flow: resultado corrupto (HTML disfrazado) ⇒ FAILED (§33/§23)
    env.chaos_corrupt_flow_results({"proj-1:image:9:1"})
    with env.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="image", project_id="proj-1",
                                 scene_number=9,
                                 prompt="PROMPT EXTERNO 9"))
        r_start = f.start_generation()
        f.wait_generation(r_start.result["handle"])
        r_dl = f.download_result(r_start.result["handle"],
                                 dest_name="corrupta.png")
        check("CAOS HTML disfrazado de PNG ⇒ FAILED (no se acepta)",
              r_dl.status is State.FAILED
              and "NO pasa verificación" in r_dl.errors[0]["message"])

    # caos Flow: generación congelada ⇒ WAIT timeout (§10/§33)
    env.chaos_flow_freeze()
    with env.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="video", project_id="proj-1",
                                 scene_number=10,
                                 prompt="PROMPT EXTERNO 10"))
        r_start = f.start_generation()
        r_wait = f.wait_generation(r_start.result["handle"], timeout_s=2.0)
        check("CAOS generación congelada ⇒ TIMEOUT honesto",
              r_wait.status is State.TIMEOUT)

    # rate limit del entorno simulado
    env2 = MockEnvironment(root=Path(tmp) / "rl")
    env2.chaos_flow_rate_limit(after=1)
    with env2.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="image", project_id="p", scene_number=1,
                                 prompt="A"))
        check("1er submit OK", f.start_generation().status is State.COMPLETED)
        f.set_prompt(FlowJobSpec(kind="image", project_id="p", scene_number=2,
                                 prompt="B"))
        r2 = f.start_generation()
        check("2do submit tras rate limit ⇒ FAILED",
              r2.status is State.FAILED
              and "rate limit" in r2.errors[0]["message"].lower())

# ══ 4. EXTENSION BRIDGE DRIVER — contrato HTTP REAL simulado (§37/§47) ═══
print("── 4. Adaptador al Flow Bridge existente (contrato congelado)")


class _BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):        # silencio en tests
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.received_headers = {k.lower(): v
                                        for k, v in self.headers.items()}
        if self.path == "/api/extension/flow/jobs/enqueue":
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            pid = data.get("project_id")
            if not pid:
                self._json(400, {"ok": False, "detail": "project_id requerido"})
                return
            self.server.jobs[pid] = [
                {"id": "j1", "kind": "image", "scene_number": 1, "part": 1,
                 "status": "queued", "asset_path": None},
                {"id": "j2", "kind": "video", "scene_number": 1, "part": 1,
                 "status": "queued", "asset_path": None},
            ]
            self.server.enqueues.append(pid)
            self._json(200, {"ok": True, "created": 2, "images": 1, "videos": 1})
        else:
            self._json(404, {"ok": False, "detail": "no encontrado"})

    def do_GET(self):
        self.server.received_headers = {k.lower(): v
                                        for k, v in self.headers.items()}
        if self.path.startswith("/api/extension/flow/jobs/status/"):
            pid = self.path.rsplit("/", 1)[-1]
            jobs = self.server.jobs.get(pid)
            if jobs is None:
                self._json(404, {"ok": False, "detail": "pid desconocido"})
                return
            calls = self.server.poll_calls.get(pid, 0) + 1
            self.server.poll_calls[pid] = calls
            if calls >= 2:
                for j in jobs:
                    j["status"] = "done"
                jobs[0]["asset_path"] = str(self.server.asset_file)
            counts = {s: sum(1 for j in jobs if j["status"] == s)
                      for s in ("queued", "claimed", "done", "dead")}
            self._json(200, {"ok": True, "counts": counts, "jobs": jobs})
        else:
            self._json(404, {"ok": False, "detail": "no encontrado"})


with tempfile.TemporaryDirectory() as tmp:
    _asset_png = Path(tmp) / "Escena_1_flow.png"
    _asset_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"asset-real-simulado")
    _srv = ThreadingHTTPServer(("127.0.0.1", 0), _BridgeHandler)
    _srv.jobs, _srv.poll_calls, _srv.enqueues = {}, {}, []
    _srv.asset_file = _asset_png
    threading.Thread(target=_srv.serve_forever, daemon=True).start()
    _base = f"http://127.0.0.1:{_srv.server_address[1]}"

    # gate §37: deshabilitado por defecto
    _drv_off = ExtensionBridgeDriver(base_url=_base)
    check("driver DESHABILITADO por defecto (NOT CONNECTED)", expect_error(
        lambda: _drv_off.open_session(), ErrorCode.BLOCKED))
    check("enabled=False es el default del adaptador",
          _drv_off.enabled is False)

    _drv = ExtensionBridgeDriver(base_url=_base, api_key="clave-bridge-test",
                                 enabled=True,
                                 asset_reader=lambda p: Path(p).read_bytes()
                                 if p and Path(p).is_file() else None)
    with tempfile.TemporaryDirectory() as tmp2:
        env = MockEnvironment(root=Path(tmp2) / "bridgews")
        # reemplazar el driver del runtime por el adaptador real-contracto
        env.runtime.flow_driver = _drv
        env.runtime.flow = None
        with env.runtime.session(operator="flow", locks=("flow",)) as h:
            _drv.permissions = env.runtime.permissions
            f = h.flow
            f.driver = _drv
            job = FlowJobSpec(kind="image", project_id="proj-bridge",
                              scene_number=1,
                              prompt="PROMPT EXTERNO (solo registro en evidencia)")
            check("OPEN_FLOW (bridge habilitado) ⇒ COMPLETED",
                  f.open_flow().status is State.COMPLETED)
            r_start = f.start_generation.__wrapped__ if False else None
            f.set_prompt(job)
            r_start = f.start_generation()
            check("START_GENERATION ⇒ enqueue por HTTP al backend EXISTENTE",
                  r_start.status is State.COMPLETED
                  and _srv.enqueues == ["proj-bridge"]
                  and r_start.result["handle"]["enqueue"].get("created") == 2)
            check("X-API-Key enviada al backend (auth del repo)",
                  _srv.received_headers.get("x-api-key") == "clave-bridge-test")
            handle = dict(r_start.result["handle"])
            handle["_job"] = job.to_dict()
            r_wait = f.wait_generation(handle, timeout_s=10.0)
            check("WAIT_GENERATION sobre status del bridge ⇒ done",
                  r_wait.status is State.COMPLETED)
            r_dl = f.download_result(handle, dest_name="bridge_asset.png")
            check("DOWNLOAD_RESULT lee asset del filesystem compartido (§23)",
                  r_dl.status is State.COMPLETED
                  and r_dl.verification.get("media_kind") == "png")
    # status 404 ⇒ FAILED con detalle
    _drv2 = ExtensionBridgeDriver(base_url=_base, enabled=True)
    try:
        _drv2.poll({"handle_id": "desconocido"})
        _poll_404 = False
    except HandsError as err:
        _poll_404 = err.code is ErrorCode.ACTION_FAILED
    check("pid desconocido (404) ⇒ ACTION_FAILED con detalle", _poll_404)
    _srv.shutdown()

# ══ 5. CONTRATO DE INTEGRACIÓN FUTURA — NOT CONNECTED (§36/§37) ══════════
print("── 5. Integración futura: schemas + puerta cerrada")
check("estado oficial NOT CONNECTED", INTEGRATION_STATUS == "NOT CONNECTED")
_ok_req, _errs = validate_hand_request({
    "request_id": "r1", "requested_by": "orquestador",
    "operations": [{"op": "OPEN", "operator": "desktop",
                    "params": {"application": "notepad-mock"}}],
    "created_at": "2026-01-01T00:00:00Z",
})
check("HAND_REQUEST válido aceptado", _ok_req and not _errs)
_bad_req, _errs_bad = validate_hand_request({
    "requested_by": "x", "operations": [{"op": "OPEN", "operator": "root"}]})
check("HAND_REQUEST inválido detectado (campos + operator)",
      not _bad_req and len(_errs_bad) >= 2)
_res = make_hand_result("r1", "COMPLETED", [{"status": "COMPLETED"}],
                        session_id="s1")
check("HAND_RESULT bien formado",
      _res["request_id"] == "r1" and _res["status"] == "COMPLETED"
      and _res["session_id"] == "s1" and _res["finished_at"])
_adapter = NotConnectedAdapter()
try:
    _adapter.submit({"request_id": "r1", "requested_by": "x",
                     "operations": [], "created_at": "t"})
    _puerta = False
except BlockedError as err:
    _puerta = err.details.get("integration_status") == "NOT CONNECTED"
check("NotConnectedAdapter ⇒ BLOCKED con estado oficial (§37)", _puerta)
check("checklist de integración futura documentado (≥6 pasos)",
      len(integration_checklist()) >= 6
      and all("task" in s for s in integration_checklist()))

# ══ 6. SELF-AUDIT AUTOMÁTICA (§40) ═══════════════════════════════════════
print("── 6. Self-audit automática de la capa")
_audit = run_selfaudit()
check("self-audit PASS completa",
      _audit["ok"] and "16/16" in _audit["summary"] or _audit["ok"],
      _audit["summary"])
_areas = {c["area"] for c in _audit["checks"]}
check("auditoría cubre las 6 áreas del brief §40",
      _areas == {"ARCHITECTURE", "SECURITY", "OPERATIONS", "SAFETY",
                 "EVIDENCE", "TESTING"}, str(_areas))
check("aislamiento arquitectónico verificado por AST (ARCH-1)",
      any(c["id"] == "ARCH-1" and c["ok"] for c in _audit["checks"]))

# ══ 7. CLEAN-ROOM (§42) ══════════════════════════════════════════════════
print("── 7. Clean-room: HANDS se prueba solo con repo+config+mocks")
_cr = run_cleanroom(verbose=False)
check("clean-room PASS completo", _cr["ok"], _cr["summary"])
check("clean-room cubre arranque declarativo, bloqueo, caos, kill switch,"
      " auditoría e integración",
      all(any(c["id"].startswith(p) and c["ok"] for c in _cr["checks"])
          for p in ("CR-01", "CR-08", "CR-09", "CR-14", "CR-16", "CR-19")))

# ══ RESUMEN ══════════════════════════════════════════════════════════════
print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
