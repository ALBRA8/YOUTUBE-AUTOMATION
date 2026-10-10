#!/usr/bin/env python3
"""Batería HANDS × EXECUTION CONTRACT V1.0 — conexión real de HANDS al
contrato de ejecución (FASE 7, capa contrato sobre mocks; §17 B/C/D/F del
mandato a nivel mock).

Cubre: FlowOp de controles + categoría de permisos; descubrimiento HONESTO
de capacidades (MockFlowControlAdapter; control ausente ⇒ available=False/
observed=None — NADA inventado); escenario B (spec 8s + driver 5s ⇒
VERIFIED + ALLOW_GENERATE + UI reconfigurada a 8s); escenario C (control
missing ⇒ CONFIG_UNSUPPORTED ⇒ start_generation REFUSA sin submit);
escenario D (control frozen ⇒ CONFIG_MISMATCH ⇒ refusa); stale read ⇒
CONFIG_UNVERIFIABLE ⇒ refusa; camino ALLOW ⇒ submit + ciclo legacy completo
(open_flow→…→report); evidencia CONFIG_GATE/SET_*/START_GENERATION con
refs job_id (§12); set_configuration compatible (legacy + execution_spec);
sin coordenadas (§8 vetadas por defecto); ExecutionContractHandAdapter
(discover/configure/start + unsupported ⇒ BlockedError) con
NotConnectedAdapter intacto como default; round-trip
build_execution_spec → FlowJobSpec(execution_spec=…) → FlowOperator.

Honestidad: NADA de ejecución real de Flow (E2E pendiente); los valores
"Flow real" de la matriz de control siguen NO PROBADOS.

Uso:  cd yt_automation_v2 && python3 tests/test_hands_contract.py
"""
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services.execution_contract import (                   # noqa: E402
    ALLOW_GENERATE, CONFIG_MISMATCH, CONFIG_UNVERIFIABLE, CONFIG_UNSUPPORTED,
    SCHEMA_VERSION, VERIFIED, build_execution_spec, spec_summary,
)
from services.hands import (                                # noqa: E402
    BlockedError, ErrorCode, EvidenceLayer, FakeClock, FlowJobSpec,
    FlowOperator, HandsError, MockEnvironment, MockFlowControlAdapter,
    NotConnectedAdapter, Observation, PermissionDeniedError, State,
    TargetResolver, TargetSpec, ValidationError, new_id,
)
from services.hands.contracts import (                      # noqa: E402
    FlowOp, OP_PERMISSION_CATEGORY,
)
from services.hands.future_integration import (             # noqa: E402
    INTEGRATION_STATUS, ExecutionContractHandAdapter,
)

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


# Spec canónico: escena 1 de un short vertical que pide 8s (fuente REAL de
# transporte: build_execution_spec — nada inventado a mano).
SPEC_8S = build_execution_spec({"scene_number": 1, "duration": 8},
                               kind="video", project_format="short")
PROMPT_P1 = "PROMPT EXTERNO P1 (viene de la capa creativa — HANDS jamás lo toca)"


class _DriverSinControles:
    """Driver mínimo SIN controls_adapter (contrato legacy puro)."""

    kind = "stub"
    host = "flow.google.com"

    def __init__(self):
        self.submitted = 0

    def open_session(self):
        return {"opened": True}

    def open_project(self, project_id):
        return {"project": project_id, "opened": True}

    def submit(self, job):
        job.validate()
        self.submitted += 1
        return {"handle_id": job.handle_key, "status": "queued"}

    def poll(self, handle):
        return {"handle_id": handle["handle_id"], "status": "queued"}

    def fetch(self, handle):
        return None

    def close_session(self):
        return {"closed": True}


def _operador_manual(env, driver) -> FlowOperator:
    """FlowOperator ensamblado a mano sobre un runtime mock (evidencia propia)."""
    ev = EvidenceLayer(env.runtime.workspace.evidence, new_id("evsess"),
                       operator="flow")
    return FlowOperator(
        driver=driver, permissions=env.runtime.permissions,
        workspace=env.runtime.workspace, waits=env.runtime.waits,
        verification=env.runtime.verification, evidence=ev,
        audit=env.runtime.audit, killswitch=env.runtime.killswitch,
        clock=env.clock)


# ══ 1. CONTRATOS: FlowOp de controles + categoría de permisos (§6/§16) ════
print("── 1. FlowOp Execution Contract + OP_PERMISSION_CATEGORY")
_NUEVOS = ("DISCOVER_CAPABILITIES", "SET_MODEL", "SET_DURATION",
           "SET_ASPECT_RATIO", "SET_OUTPUTS", "SET_AUDIO", "SET_RESOLUTION",
           "VERIFY_CONTROLS")
check("8 FlowOp nuevos presentes con valor = nombre",
      all(hasattr(FlowOp, n) and FlowOp[n].value == n for n in _NUEVOS))
check("8 FlowOp nuevos en OP_PERMISSION_CATEGORY como 'domain'",
      all(OP_PERMISSION_CATEGORY.get(n) == "domain" for n in _NUEVOS))
_LEGACY = ("OPEN_FLOW", "OPEN_PROJECT", "SELECT_PROJECT", "SET_PROMPT",
           "SET_CONFIGURATION", "START_GENERATION", "WAIT_GENERATION",
           "DETECT_RESULT", "DOWNLOAD_RESULT", "VERIFY_RESULT", "REPORT_RESULT")
check("11 FlowOp legacy intactos (contrato congelado)",
      all(FlowOp[n].value == n for n in _LEGACY)
      and len(FlowOp) == len(_LEGACY) + len(_NUEVOS))
check("spec canónico: schema_version 1.0 + duration 8 requerida + 9:16",
      SPEC_8S["schema_version"] == SCHEMA_VERSION
      and SPEC_8S["duration"] == {"requested": 8.0, "required": True,
                                  "tolerance_seconds": 0}
      and SPEC_8S["aspect_ratio"]["requested"] == "9:16"
      and SPEC_8S["aspect_ratio"]["required"] is True
      and SPEC_8S["compatibility_policy"]["generate_requires_verified"] is True,
      spec_summary(SPEC_8S))

# ══ 2. DESCUBRIMIENTO HONESTO (§7) ════════════════════════════════════════
print("── 2. Descubrimiento honesto de capacidades")
with tempfile.TemporaryDirectory() as tmp:
    caps = MockFlowControlAdapter().discover()
    d = caps.of("duration")
    check("duration disponible/editable/observable (5s por defecto)",
          d["available"] and d["editable"] and d["observed"] == "5s")
    check("references NO es control de UI ⇒ no inventado en discovery",
          "references" not in caps.to_dict())
    caps_missing = MockFlowControlAdapter(missing=("duration",)).discover()
    dm = caps_missing.of("duration")
    check("control ausente ⇒ available=False / observed=None (NO se inventa)",
          dm["available"] is False and dm["editable"] is False
          and dm["observed"] is None and dm["source"] == "mock_discovery")

    env0 = MockEnvironment(root=Path(tmp) / "ws0")
    op0 = _operador_manual(env0, _DriverSinControles())
    r0 = op0.discover_capabilities()
    check("sin controls_adapter ⇒ DISCOVER FAILED honesto con available=[]",
          r0.status is State.FAILED
          and r0.result.get("available") == []
          and "no inventa" in r0.result.get("detail", ""))
    r0c = op0.configure_from_spec(SPEC_8S, job_id="j0")
    check("sin controls_adapter ⇒ configure FAILED VALIDATION_ERROR",
          r0c.status is State.FAILED
          and r0c.errors[0]["code"] == "VALIDATION_ERROR"
          and "sin controls_adapter" in r0c.errors[0]["message"])

# ══ 3. ESCENARIO B — spec 8s + driver 5s ⇒ VERIFIED + ALLOW_GENERATE ══════
print("── 3. B: duration 8 vs UI 5s ⇒ reconfigura, verifica y permite")
with tempfile.TemporaryDirectory() as tmp:
    envB = MockEnvironment(root=Path(tmp) / "wsB", controls_state={"duration": "5s"})
    JOB_B = "projB:video:1:1"
    with envB.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        check("FlowOperator hereda controls_adapter del driver mock",
              f.controls_adapter is not None
              and f.controls_adapter is envB.flow_mock.controls_adapter)
        check("OPEN_FLOW ⇒ COMPLETED", f.open_flow().status is State.COMPLETED)
        r_disc = f.discover_capabilities()
        check("DISCOVER_CAPABILITIES ⇒ COMPLETED con capacidades reales del mock",
              r_disc.status is State.COMPLETED
              and "duration" in r_disc.result.get("available", [])
              and r_disc.result["capabilities"]["duration"]["observed"] == "5s")
        job = FlowJobSpec(kind="video", project_id="projB", scene_number=1,
                          prompt=PROMPT_P1, execution_spec=SPEC_8S)
        f.set_prompt(job)
        r_cfg = f.configure_from_spec(SPEC_8S, job_id=JOB_B)
        check("configure_from_spec ⇒ COMPLETED (gate ALLOW_GENERATE)",
              r_cfg.status is State.COMPLETED
              and r_cfg.result.get("decision") == ALLOW_GENERATE)
        check("verification {expected: ALLOW_GENERATE, observed, verdict PASS}",
              r_cfg.verification.get("expected") == ALLOW_GENERATE
              and r_cfg.verification.get("observed") == ALLOW_GENERATE
              and r_cfg.verification.get("verdict") == "PASS")
        check("control duration ⇒ VERIFIED por relectura",
              f.last_gate["control_results"]["duration"]["verdict"] == VERIFIED
              and f.last_gate["control_results"]["aspect_ratio"]["verdict"]
              == VERIFIED)
        check("UI reconfigurada: adapter.state['duration'] == '8s'",
              envB.flow_mock.controls_adapter.state["duration"] == "8s")
        r_start = f.start_generation()
        check("START_GENERATION ⇒ COMPLETED (gate ALLOW fresco antes de submit)",
              r_start.status is State.COMPLETED
              and envB.flow_mock.submitted == 1
              and f.last_gate["decision"] == ALLOW_GENERATE)
        check("CONFIG ≠ prompt: P1 intacto en el job subido",
              envB.flow_mock.jobs[JOB_B]["job"]["prompt"] == PROMPT_P1)

# ══ 4. ESCENARIO C — duration missing ⇒ CONFIG_UNSUPPORTED ⇒ REFUSA ═══════
print("── 4. C: control ausente ⇒ CONFIG_UNSUPPORTED ⇒ NO se genera")
with tempfile.TemporaryDirectory() as tmp:
    envC = MockEnvironment(root=Path(tmp) / "wsC",
                           controls_missing=("duration",))
    JOB_C = "projC:video:1:1"
    with envC.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="video", project_id="projC",
                                 scene_number=1, prompt=PROMPT_P1,
                                 execution_spec=SPEC_8S))
        r_cfg = f.configure_from_spec(SPEC_8S, job_id=JOB_C)
        check("configure_from_spec ⇒ FAILED con decisión CONFIG_UNSUPPORTED",
              r_cfg.status is State.FAILED
              and r_cfg.verification.get("observed") == CONFIG_UNSUPPORTED
              and r_cfg.verification.get("verdict") == "FAIL"
              and f.last_gate["decision"] == CONFIG_UNSUPPORTED)
        check("error del gate contiene CONFIG_UNSUPPORTED",
              "CONFIG_UNSUPPORTED" in r_cfg.errors[0]["message"])
        antes = envC.flow_mock.submitted
        r_start = f.start_generation()
        check("start_generation REFUSA: FAILED + driver.submitted intacto",
              r_start.status is State.FAILED
              and envC.flow_mock.submitted == antes == 0)
        check("refuso: error VERIFICATION_FAILED con CONFIG_UNSUPPORTED",
              r_start.errors[0]["code"] == "VERIFICATION_FAILED"
              and "CONFIG_UNSUPPORTED" in r_start.errors[0]["message"])
        check("refuso: result {gate: CONFIG_UNSUPPORTED, refusado_por: "
              "execution_contract, submitted: False}",
              r_start.result.get("gate") == CONFIG_UNSUPPORTED
              and r_start.result.get("refusado_por") == "execution_contract"
              and r_start.result.get("submitted") is False)
        # ── evidencia refs job_id (§12) ──────────────────────────────────
        gates = h.evidence.query(action="CONFIG_GATE")
        check("evidencia CONFIG_GATE registrada con refs job_id",
              len(gates) >= 2
              and all((r.get("refs") or {}).get("job_id") == JOB_C
                      for r in gates)
              and any(r.get("result") == "FAIL" for r in gates))
        sets = h.evidence.query(action="SET_DURATION")
        check("evidencia SET_DURATION (UNSUPPORTED) con refs job_id",
              len(sets) >= 1
              and all((r.get("refs") or {}).get("job_id") == JOB_C
                      for r in sets))
        starts = h.evidence.query(action="START_GENERATION")
        check("refuso START_GENERATION en evidencia con refs job_id",
              any(r.get("result") == "FAILED"
                  and (r.get("refs") or {}).get("job_id") == JOB_C
                  for r in starts))

# ══ 5. ESCENARIO D — duration frozen ⇒ CONFIG_MISMATCH ⇒ REFUSA ═══════════
print("── 5. D: control congelado (5s pese al click) ⇒ CONFIG_MISMATCH")
with tempfile.TemporaryDirectory() as tmp:
    envD = MockEnvironment(root=Path(tmp) / "wsD", controls_frozen=("duration",))
    with envD.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="video", project_id="projD",
                                 scene_number=1, prompt=PROMPT_P1,
                                 execution_spec=SPEC_8S))
        r_start = f.start_generation()
        check("frozen ⇒ gate CONFIG_MISMATCH ⇒ start REFUSA sin submit",
              r_start.status is State.FAILED
              and r_start.result.get("gate") == CONFIG_MISMATCH
              and "CONFIG_MISMATCH" in r_start.errors[0]["message"]
              and envD.flow_mock.submitted == 0)
        check("UI sigue en 5s (el MISMATCH es real, no teórico)",
              envD.flow_mock.controls_adapter.state["duration"] == "5s"
              and f.last_gate["control_results"]["duration"]["verdict"]
              == "MISMATCH")

# ══ 6. STALE READ — relectura traidora ⇒ CONFIG_UNVERIFIABLE ⇒ REFUSA ═════
print("── 6. stale read ⇒ CONFIG_UNVERIFIABLE ⇒ NO se genera")
with tempfile.TemporaryDirectory() as tmp:
    envS = MockEnvironment(root=Path(tmp) / "wsS", controls_stale=("duration",))
    with envS.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(FlowJobSpec(kind="video", project_id="projS",
                                 scene_number=1, prompt=PROMPT_P1,
                                 execution_spec=SPEC_8S))
        r_start = f.start_generation()
        check("stale ⇒ gate CONFIG_UNVERIFIABLE ⇒ start REFUSA sin submit",
              r_start.status is State.FAILED
              and r_start.result.get("gate") == CONFIG_UNVERIFIABLE
              and "CONFIG_UNVERIFIABLE" in r_start.errors[0]["message"]
              and envS.flow_mock.submitted == 0)

# ══ 7. CAMINO ALLOW + CICLO LEGACY COMPLETO (§14) ═════════════════════════
print("── 7. ALLOW ⇒ submit + ciclo legacy completo sobre mock")
with tempfile.TemporaryDirectory() as tmp:
    envA = MockEnvironment(root=Path(tmp) / "wsA", controls_state={"duration": "5s"})
    JOB_A = "projA:video:1:1"
    with envA.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        check("OPEN_FLOW ⇒ COMPLETED", f.open_flow().status is State.COMPLETED)
        check("OPEN_PROJECT ⇒ COMPLETED",
              f.open_project("projA").status is State.COMPLETED)
        f.set_prompt(FlowJobSpec(kind="video", project_id="projA",
                                 scene_number=1, prompt=PROMPT_P1,
                                 execution_spec=SPEC_8S))
        r_start = f.start_generation()
        check("gate ALLOW ⇒ submit ejecutado (driver.submitted crece)",
              r_start.status is State.COMPLETED
              and envA.flow_mock.submitted == 1)
        handle = r_start.result["handle"]
        r_wait = f.wait_generation(handle)
        check("WAIT_GENERATION ⇒ COMPLETED", r_wait.status is State.COMPLETED)
        r_detect = f.detect_result(handle)
        check("DETECT_RESULT ve status done",
              r_detect.status is State.COMPLETED
              and r_detect.result.get("status") == "done")
        r_dl = f.download_result(handle, dest_name="contrato_b.mp4")
        check("DOWNLOAD_RESULT verifica magic bytes MP4 (§23)",
              r_dl.status is State.COMPLETED
              and r_dl.verification.get("verdict") == "PASS"
              and r_dl.verification.get("media_kind") == "mp4")
        r_dl2 = f.download_result(handle, dest_name="contrato_b.mp4")
        check("re-descarga idempotente evitada (§26)",
              r_dl2.status is State.COMPLETED
              and bool(r_dl2.result.get("skipped")))
        r_ver = f.verify_result(r_dl.result["downloaded"], kind="video")
        check("VERIFY_RESULT ⇒ COMPLETED", r_ver.status is State.COMPLETED)
        r_rep = f.report_result(handle, asset_path=r_dl.result["downloaded"])
        check("REPORT_RESULT ⇒ COMPLETED",
              r_rep.status is State.COMPLETED)
        check("evidencia START_GENERATION del ALLOW con refs job_id",
              any((r.get("refs") or {}).get("job_id") == JOB_A
                  for r in h.evidence.query(action="START_GENERATION")))

    # set_configuration: legacy intacto y ruta execution_spec con adapter
    with envA.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        r_legacy = f.set_configuration({"modo": "mock"})
        check("set_configuration legacy (sin execution_spec) intacto",
              r_legacy.status is State.COMPLETED
              and f.configuration == {"modo": "mock"}
              and r_legacy.result.get("configuration") == {"modo": "mock"})
        r_spec = f.set_configuration({"execution_spec": SPEC_8S,
                                      "job_id": "projA:video:2:1"})
        check("set_configuration con execution_spec ⇒ gate VERIFY_CONTROLS "
              "ALLOW + configuración almacenada",
              r_spec.status is State.COMPLETED
              and r_spec.name == FlowOp.VERIFY_CONTROLS.value
              and r_spec.result.get("decision") == ALLOW_GENERATE
              and f.configuration.get("job_id") == "projA:video:2:1")

    env0b = MockEnvironment(root=Path(tmp) / "ws0b")
    op1 = _operador_manual(env0b, _DriverSinControles())
    r_legacy0 = op1.set_configuration({"modo": "sin-adapter"})
    check("set_configuration sin adapter ⇒ legacy exacto (self.configuration)",
          r_legacy0.status is State.COMPLETED
          and op1.configuration == {"modo": "sin-adapter"})

# ══ 8. SIN COORDENADAS (§8/§28 — política por defecto) ════════════════════
print("── 8. Coordenadas vetadas por política (allow_coordinate_fallback=False)")
_resolver = TargetResolver()          # default: allow_coordinate_fallback=False
check("TargetSpec(coords=(10,10)) sin match ⇒ PermissionDeniedError (§8)",
      expect_error(lambda: _resolver.resolve(
          TargetSpec(coords=(10, 10)),
          Observation(timestamp="t", elements=[])), ErrorCode.PERMISSION_DENIED))

# ══ 9. ROUND-TRIP spec → FlowJobSpec → FlowOperator (transporte congelado) ═
print("── 9. Round-trip execution_spec (P1 intacto, to_dict congelado)")
with tempfile.TemporaryDirectory() as tmp:
    envR = MockEnvironment(root=Path(tmp) / "wsR", controls_state={"duration": "5s"})
    job_rt = FlowJobSpec(kind="video", project_id="projR", scene_number=1,
                         prompt=PROMPT_P1, execution_spec=SPEC_8S)
    job_rt.validate()
    check("to_dict() NO transporta execution_spec (contrato congelado)",
          "execution_spec" not in job_rt.to_dict()
          and job_rt.to_dict()["prompt"] == PROMPT_P1)
    with envR.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        f.set_prompt(job_rt)
        check("pending_job.execution_spec es el spec del contrato",
              f.pending_job is not None
              and f.pending_job.execution_spec is SPEC_8S)
        r = f.start_generation()
        check("round-trip operativo: spec → gate ALLOW → submit",
              r.status is State.COMPLETED
              and envR.flow_mock.submitted == 1
              and f.last_gate["decision"] == ALLOW_GENERATE)
    job_bad = FlowJobSpec(kind="video", project_id="projR", scene_number=1,
                          prompt=PROMPT_P1, execution_spec="no-soy-dict")
    check("execution_spec no-dict ⇒ VALIDATION_ERROR (no se inventa spec)",
          expect_error(job_bad.validate, ErrorCode.VALIDATION_ERROR))

# ══ 10. EXECUTION CONTRACT HAND ADAPTER (puerta de la capa contrato) ══════
print("── 10. ExecutionContractHandAdapter + NotConnectedAdapter default")
with tempfile.TemporaryDirectory() as tmp:
    envH = MockEnvironment(root=Path(tmp) / "wsH", controls_state={"duration": "5s"})
    with envH.runtime.session(operator="flow", locks=("flow",)) as h:
        adapter = ExecutionContractHandAdapter(h.flow, evidence=h.evidence)
        # El prompt SIEMPRE llega de fuera (§15): la puerta lo asume ya
        # registrado en el operador (SET_PROMPT previo del orquestador).
        h.flow.set_prompt(FlowJobSpec(kind="video", project_id="projH",
                                      scene_number=1, prompt=PROMPT_P1,
                                      execution_spec=SPEC_8S))
        req = {
            "request_id": "req-ec-1", "requested_by": "orquestador-test",
            "operations": [
                {"op": "flow.discover_capabilities", "operator": "flow"},
                {"op": "flow.configure_from_spec", "operator": "flow",
                 "spec": SPEC_8S, "job_id": "projH:video:1:1"},
                {"op": "flow.start_generation", "operator": "flow"},
            ],
            "created_at": "2026-01-01T00:00:00Z",
        }
        res = adapter.submit(req)
        check("HAND_RESULT: request_id + status COMPLETED + 3 resultados",
              res.get("request_id") == "req-ec-1"
              and res.get("status") == "COMPLETED"
              and len(res.get("results", [])) == 3
              and all(r["status"] == "COMPLETED" for r in res["results"])
              and res.get("started_at") and res.get("finished_at"))
        check("discover/configure/start ejecutados en orden sobre FlowOperator",
              res["results"][0]["name"] == FlowOp.DISCOVER_CAPABILITIES.value
              and res["results"][1]["name"] == FlowOp.VERIFY_CONTROLS.value
              and res["results"][2]["name"] == FlowOp.START_GENERATION.value
              and envH.flow_mock.submitted == 1)
        check("evidence_manifest del HAND_RESULT (§21)",
              res.get("evidence_manifest", {}).get("records", 0) > 0)
        req_bad = dict(req, operations=[
            {"op": "flow.set_prompt", "operator": "flow"}])
        check("operación no soportada ⇒ BlockedError honesto",
              expect_error(lambda: adapter.submit(req_bad), ErrorCode.BLOCKED))
        req_invalid = {"requested_by": "x", "operations": [], "created_at": "t"}
        check("HAND_REQUEST inválido ⇒ ValidationError (schema §37)",
              expect_error(lambda: adapter.submit(req_invalid),
                           ErrorCode.VALIDATION_ERROR))

    envH2 = MockEnvironment(root=Path(tmp) / "wsH2",
                            controls_missing=("duration",))
    with envH2.runtime.session(operator="flow", locks=("flow",)) as h:
        adapter2 = ExecutionContractHandAdapter(h.flow)
        h.flow.set_prompt(FlowJobSpec(kind="video", project_id="projH2",
                                      scene_number=1, prompt=PROMPT_P1,
                                      execution_spec=SPEC_8S))
        res2 = adapter2.submit({
            "request_id": "req-ec-2", "requested_by": "orquestador-test",
            "operations": [
                {"op": "flow.configure_from_spec", "operator": "flow",
                 "spec": SPEC_8S, "job_id": "projH2:video:1:1"},
                {"op": "flow.start_generation", "operator": "flow"},
            ],
            "created_at": "2026-01-01T00:00:00Z",
        })
        check("gate CONFIG_UNSUPPORTED a través de la puerta ⇒ HAND FAILED "
              "sin submit (honesto extremo a extremo)",
              res2["status"] == "FAILED"
              and all(r["status"] == "FAILED" for r in res2["results"])
              and any("CONFIG_UNSUPPORTED" in (e or {}).get("message", "")
                      for e in res2.get("errors", []))
              and envH2.flow_mock.submitted == 0)

check("NotConnectedAdapter sigue siendo el default y su puerta 'NOT CONNECTED'",
      NotConnectedAdapter().name == "not_connected"
      and expect_error(lambda: NotConnectedAdapter().submit(
          {"request_id": "x", "requested_by": "t", "operations": [],
           "created_at": "now"}), ErrorCode.BLOCKED))
check("INTEGRATION_STATUS oficial: PARTIAL CONNECTED (capa contrato V1.0)",
      INTEGRATION_STATUS.startswith("PARTIAL CONNECTED")
      and "Execution Contract V1.0" in INTEGRATION_STATUS
      and "E2E real pendiente" in INTEGRATION_STATUS)

# ══ RESUMEN ═══════════════════════════════════════════════════════════════
print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
