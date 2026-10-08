"""
HANDS · Flow Operator — especialista de Google Flow (§14-§15).

REGLA DE ORO (§15): Flow Operator NO es el cerebro. No inventa prompts,
historias, escenas ni conceptos audiovisuales: recibe instrucciones
operativas externas y las ejecuta. El prompt viaja DENTRO del job y se
valida no-vacío — la fuente creativa real sigue siendo el backend
(`flow_export.build_script_json`); HANDS nunca la sustituye.

Arquitectura de drivers (§47 — reutilizar, no duplicar):

  FlowDriver (puerto)          — contrato {job} → {status, asset}
    ├─ MockFlowDriver          — simulación determinista del ciclo de
    │                            generación (tests/clean-room, §34)
    └─ ExtensionBridgeDriver   — adaptador al CONTRATO HTTP EXISTENTE del
                                 Flow Bridge (5 endpoints congelados,
                                 enqueue/status). NO importa internals del
                                 orquestador (§36): habla HTTP con el
                                 backend ya desplegado y deshabilitado por
                                 defecto (V1.0 = NOT CONNECTED, §37).

Operaciones (§14): OPEN_FLOW · OPEN_PROJECT · SELECT_PROJECT · SET_PROMPT ·
SET_CONFIGURATION · START_GENERATION · WAIT_GENERATION · DETECT_RESULT ·
DOWNLOAD_RESULT · VERIFY_RESULT · REPORT_RESULT.

Toda operación: kill switch → permiso de dominio (§16) → acción →
observación (poll) → verificación (§12, con file verification §23 para
assets) → evidencia (§21). Idempotencia en descarga (§26): si el fichero ya
existe y verifica PASS, no se re-descarga.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from .clock import HandsClock
from .contracts import (ActionFailedError, BlockedError,
                        FlowOp, HandsError, HandsTimeoutError,
                        OperationResult, PermissionDeniedError, State,
                        StoppedError, ValidationError, new_id, now_iso)
from .evidence import AuditTrail, EvidenceLayer
from .killswitch import KillSwitch
from .permissions import PermissionModel
from .verification import Verdict, VerificationEngine, verify_file
from .waits import WaitEngine
from .workspace import HandsWorkspace

FLOW_URL = "https://flow.google.com/"
VALID_KINDS = ("image", "video")


# ════════════════════════════════════════════════════════════════════════
# Job spec — espejo del esquema de la cola real (contrato documentado)
# ════════════════════════════════════════════════════════════════════════
@dataclass
class FlowJobSpec:
    """Job operacional de Flow (forma alineada con la cola real del repo).

    prompt: SIEMPRE proviene de fuera de HANDS (§15). Vacío ⇒ ValidationError.
    """
    kind: str                      # "image" | "video"
    project_id: str
    scene_number: int
    part: int = 1
    prompt: str = ""
    prompt_meta: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValidationError(f"kind inválido: {self.kind!r}",
                                  details={"valid": list(VALID_KINDS)})
        if not self.project_id:
            raise ValidationError("project_id obligatorio")
        if not isinstance(self.scene_number, int) or self.scene_number < 1:
            raise ValidationError("scene_number debe ser int >= 1")
        if not isinstance(self.part, int) or self.part < 1:
            raise ValidationError("part debe ser int >= 1")
        if not self.prompt or not self.prompt.strip():
            raise ValidationError(
                "prompt vacío — HANDS nunca inventa prompts (§15): el prompt "
                "debe llegar de la capa creativa")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "project_id": self.project_id,
                "scene_number": self.scene_number, "part": self.part,
                "prompt": self.prompt, "prompt_meta": self.prompt_meta}

    @property
    def handle_key(self) -> str:
        return f"{self.project_id}:{self.kind}:{self.scene_number}:{self.part}"


# ════════════════════════════════════════════════════════════════════════
# Puerto FlowDriver
# ════════════════════════════════════════════════════════════════════════
class MockFlowDriver:
    """Driver simulado determinista: queued → generating → done|error.

    Genera bytes con magic bytes reales (PNG/MP4) para que la verificación
    de medios (§23) sea ejercida de verdad. Hooks de caos: fail_submit,
    error_jobs, rate_limit_after, frozen (WAIT_GENERATION se congela).
    """

    kind = "mock"
    host = "flow.google.com"

    def __init__(self, clock: HandsClock, *, generation_ticks: int = 3,
                 fail_submit: bool = False, rate_limit_after: int | None = None,
                 corrupt_results: set[str] | None = None):
        self.clock = clock
        self.generation_ticks = generation_ticks
        self.fail_submit = fail_submit
        self.rate_limit_after = rate_limit_after
        self.corrupt_results = set(corrupt_results or set())
        self.submitted = 0
        self.jobs: dict[str, dict[str, Any]] = {}
        self.session_open = False
        self.projects_opened: list[str] = []
        self.configuration: dict[str, Any] = {}
        self.frozen = False                       # CAOS: generación congelada

    # ── FlowDriver ───────────────────────────────────────────────────────
    def open_session(self) -> dict[str, Any]:
        self.session_open = True
        return {"opened": True, "url": FLOW_URL, "driver": self.kind}

    def open_project(self, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ValidationError("project_id obligatorio")
        self.projects_opened.append(project_id)
        return {"project": project_id, "opened": True}

    def submit(self, job: FlowJobSpec) -> dict[str, Any]:
        job.validate()
        if self.fail_submit:
            raise ActionFailedError("inyección de caos: submit falla")
        self.submitted += 1
        if self.rate_limit_after is not None and self.submitted > self.rate_limit_after:
            raise ActionFailedError(
                "rate limit simulado de Flow", details={"submitted": self.submitted})
        handle_id = job.handle_key
        self.jobs[handle_id] = {
            "job": job.to_dict(), "status": "queued", "ticks": 0,
            "corrupt": handle_id in self.corrupt_results,
        }
        return {"handle_id": handle_id, "status": "queued"}

    def poll(self, handle: dict[str, Any]) -> dict[str, Any]:
        handle_id = handle["handle_id"]
        job_state = self.jobs.get(handle_id)
        if job_state is None:
            raise TargetNotFoundError_(f"handle desconocido: {handle_id}")
        if not self.frozen and job_state["status"] in ("queued", "generating"):
            job_state["ticks"] += 1
            job_state["status"] = ("generating"
                                   if job_state["ticks"] < self.generation_ticks
                                   else "done")
        payload: dict[str, Any] = {"handle_id": handle_id,
                                   "status": job_state["status"],
                                   "progress": min(job_state["ticks"],
                                                   self.generation_ticks)}
        if job_state["status"] == "done":
            payload["asset_bytes"] = self._asset_bytes(job_state)
            payload["asset_kind"] = job_state["job"]["kind"]
        return payload

    def fetch(self, handle: dict[str, Any]) -> bytes | None:
        handle_id = handle["handle_id"]
        job_state = self.jobs.get(handle_id)
        if job_state is None or job_state["status"] != "done":
            return None
        return self._asset_bytes(job_state)

    def close_session(self) -> dict[str, Any]:
        self.session_open = False
        return {"closed": True}

    # ── internals ────────────────────────────────────────────────────────
    def _asset_bytes(self, job_state: dict[str, Any]) -> bytes:
        kind = job_state["job"]["kind"]
        if job_state["corrupt"]:
            return b"<html>Error de Flow simulado</html>"   # HTML disfrazado
        if kind == "image":
            return b"\x89PNG\r\n\x1a\n" + b"mock-flow-image:" + \
                handle_bytes(job_state) + b"\n"
        # mp4: caja ftyp en offset 4
        return b"\x00\x00\x00\x18ftypisom" + b"mock-flow-video:" + \
            handle_bytes(job_state)


def handle_bytes(job_state: dict[str, Any]) -> bytes:
    return json.dumps(job_state["job"], sort_keys=True).encode()[:64]


def TargetNotFoundError_(message: str) -> HandsError:
    from .contracts import TargetNotFoundError
    return TargetNotFoundError(message)


# ════════════════════════════════════════════════════════════════════════
# Adaptador al Flow Bridge EXISTENTE (contrato HTTP congelado) — §36/§37
# ════════════════════════════════════════════════════════════════════════
class _UrllibHttp:
    """Transporte HTTP por defecto (stdlib) — inyectable en tests."""

    def request(self, method: str, url: str, *, headers: dict[str, str],
                body: bytes | None, timeout_s: float) -> tuple[int, bytes]:
        req = urllib_request.Request(url, data=body, method=method)
        for key, value in headers.items():
            req.add_header(key, value)
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as resp:
                return resp.status, resp.read()
        except urllib_error.HTTPError as exc:
            return exc.code, exc.read()


class ExtensionBridgeDriver:
    """Adaptador al Flow Bridge EXISTENTE — INTEGRACIÓN DESACTIVADA (§37).

    Hable EXCLUSIVAMENTE el contrato HTTP congelado del repo (5 endpoints):
      POST /api/extension/flow/jobs/enqueue       {project_id}
      GET  /api/extension/flow/jobs/status/{pid}
    (claim/heartbeat/complete/fail son del WORKER extensión — HANDS no
    compite por ser worker: observa estado y recoge el asset ya guardado).

    NOT CONNECTED por diseño en V1.0:
      * enabled=False por defecto → toda operación BlockedError;
      * la activación explícita queda para la FUTURA integración;
      * fetch exige un `asset_reader` inyectado (filesystem compartido) —
        sin él, devuelve None honesto.
    """

    kind = "extension_bridge"

    def __init__(self, *, base_url: str = "http://127.0.0.1:8000",
                 api_key: str | None = None, enabled: bool = False,
                 http: Any | None = None, timeout_s: float = 30.0,
                 asset_reader: Callable[[str], bytes | None] | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.enabled = bool(enabled)
        self.http = http or _UrllibHttp()
        self.timeout_s = timeout_s
        self.asset_reader = asset_reader
        from urllib.parse import urlsplit
        self.host = urlsplit(self.base_url).hostname or "127.0.0.1"

    # ── gate §37 ─────────────────────────────────────────────────────────
    def _require_enabled(self) -> None:
        if not self.enabled:
            raise BlockedError(
                "ExtensionBridgeDriver DESHABILITADO: la integración "
                "YOUTUBE-AUTOMATION ↔ HANDS NO está conectada en V1.0 (§37). "
                "Activación explícita reservada a la fase de integración.",
                details={"integration_status": "NOT CONNECTED"})

    def _call(self, method: str, path: str, *,
              body: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_enabled()
        headers = {"Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            status, raw = self.http.request(method, self.base_url + path,
                                            headers=headers, body=payload,
                                            timeout_s=self.timeout_s)
        except HandsError:
            raise
        except Exception as exc:            # noqa: BLE001 — transporte ⇒ taxonomía
            raise ActionFailedError(
                f"transporte HTTP falló hacia el bridge: "
                f"{type(exc).__name__}: {exc}",
                details={"base_url": self.base_url, "path": path}) from exc
        try:
            data = json.loads(raw.decode()) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {"raw": raw[:200].decode(errors="replace")}
        if status >= 400:
            raise ActionFailedError(
                f"bridge HTTP {status} en {path}",
                details={"status": status, "response": data})
        return data

    # ── FlowDriver ───────────────────────────────────────────────────────
    def open_session(self) -> dict[str, Any]:
        self._require_enabled()
        return {"opened": True, "url": FLOW_URL,
                "note": "la apertura real la ejecuta la extensión worker "
                        "(HANDS orquesta/observa)"}

    def open_project(self, project_id: str) -> dict[str, Any]:
        self._require_enabled()
        if not project_id:
            raise ValidationError("project_id obligatorio")
        return {"project": project_id,
                "url": f"{FLOW_URL}project/{project_id}",
                "note": "selección de proyecto operada por la extensión"}

    def submit(self, job: FlowJobSpec) -> dict[str, Any]:
        job.validate()
        # CONTRATO REAL: enqueue solo toma project_id — el backend genera los
        # jobs con build_script_json (los prompts JAMÁS los inventa HANDS §15).
        data = self._call("POST", "/api/extension/flow/jobs/enqueue",
                          body={"project_id": job.project_id})
        return {"handle_id": job.project_id, "enqueue": data,
                "prompt_registered": len(job.prompt)}

    def poll(self, handle: dict[str, Any]) -> dict[str, Any]:
        pid = handle["handle_id"]
        data = self._call("GET", f"/api/extension/flow/jobs/status/{pid}")
        counts = data.get("counts", {}) if isinstance(data, dict) else {}
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        if counts.get("dead", 0) > 0:
            status = "error"
        elif counts.get("queued", 0) + counts.get("claimed", 0) > 0:
            status = "generating"
        elif jobs and counts.get("queued", 0) + counts.get("claimed", 0) \
                + counts.get("dead", 0) == 0:
            status = "done"
        else:
            status = "unknown"
        assets = [{"job": j.get("id"), "kind": j.get("kind"),
                   "scene": j.get("scene_number"), "part": j.get("part"),
                   "asset_path": j.get("asset_path")}
                  for j in jobs if j.get("status") == "done" and j.get("asset_path")]
        return {"handle_id": pid, "status": status, "counts": counts,
                "assets": assets}

    def fetch(self, handle: dict[str, Any]) -> bytes | None:
        self._require_enabled()
        if self.asset_reader is None:
            return None          # honesto: sin lector de assets no hay bytes
        assets = handle.get("_last_assets") or []
        if not assets:
            polled = self.poll(handle)
            assets = polled.get("assets", [])
            handle["_last_assets"] = assets
        if not assets:
            return None
        return self.asset_reader(assets[0]["asset_path"])

    def close_session(self) -> dict[str, Any]:
        self._require_enabled()
        return {"closed": True}


def _jsonable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Bytes del driver (asset_bytes) → marcador honesto sin datos crudos."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bytes):
            out[key] = f"<{len(value)} bytes>"
        else:
            out[key] = value
    return out


# ════════════════════════════════════════════════════════════════════════
# Flow Operator (§14)
# ════════════════════════════════════════════════════════════════════════
class FlowOperator:
    """Especialista Google Flow — ejecuta, nunca decide contenido (§15)."""

    name = "flow"

    def __init__(self, *, driver, permissions: PermissionModel,
                 workspace: HandsWorkspace, waits: WaitEngine,
                 verification: VerificationEngine, evidence: EvidenceLayer,
                 audit: AuditTrail, killswitch: KillSwitch, clock: HandsClock,
                 wait_timeout_s: float = 60.0, poll_interval_s: float = 0.5,
                 on_result: Any = None):
        self.driver = driver
        self.permissions = permissions
        self.workspace = workspace
        self.waits = waits
        self.verification = verification
        self.evidence = evidence
        self.audit = audit
        self.killswitch = killswitch
        self.clock = clock
        self.wait_timeout_s = wait_timeout_s
        self.poll_interval_s = poll_interval_s
        self.on_result = on_result        # p.ej. session.add_action (§19)
        self.pending_job: FlowJobSpec | None = None
        self.configuration: dict[str, Any] = {}

    def _notify(self, result: OperationResult) -> None:
        if self.on_result is not None:
            try:
                self.on_result(result)            # §19: acción → sesión
            except Exception:                     # noqa: BLE001
                pass

    # ── núcleo de operación (mismo modelo §7 a nivel driver) ────────────
    def _op(self, op_name: str, action: Callable[[], dict[str, Any]],
            *, verify: Callable[[dict[str, Any]], Verdict] | None = None,
            timeout_s: float | None = None) -> OperationResult:
        result = OperationResult(operation_id=new_id("flow"), name=op_name,
                                 operator=self.name, status=State.RUNNING,
                                 started_at=now_iso())
        start = time.monotonic()
        try:
            self.killswitch.check()                                   # §27
            decision = self.permissions.check_domain(self.driver.host)
            self.permissions.require(decision)                        # §16
            result.result["permission"] = decision.to_dict()
            payload = action()                                        # ACTION
            result.result.update(_jsonable_payload(payload))
            verdict = verify(payload) if verify else Verdict.PASS     # VERIFY
            result.verification = {"verdict": verdict.value,
                                   "observed": _jsonable_payload(payload)}
            if verdict is Verdict.PASS:
                result.status = State.COMPLETED
            elif verdict is Verdict.UNKNOWN:
                result.status = State.UNKNOWN                         # §11
            else:
                result.status = State.FAILED
        except StoppedError as err:
            result.status = State.STOPPED
            result.add_error(err)
        except PermissionDeniedError as err:                          # §16
            result.status = State.BLOCKED
            result.add_error(err)
        except BlockedError as err:
            result.status = State.BLOCKED
            result.add_error(err)
        except HandsTimeoutError as err:
            result.status = State.TIMEOUT
            result.add_error(err)
        except HandsError as err:
            result.status = State.FAILED
            result.add_error(err)
        except Exception as err:                                      # noqa: BLE001
            from .contracts import error_from_exception
            normalized = error_from_exception(err)
            result.status = State.FAILED
            result.add_error(normalized)
        result.finished_at = now_iso()
        result.duration_ms = int((time.monotonic() - start) * 1000)
        result.evidence_ids.append(self.evidence.record(
            action=op_name, operator=self.name,
            target={"driver": self.driver.kind, "host": self.driver.host},
            expected_state=None,
            observed_state=result.result or None,
            result=result.status.value,
            error=(result.errors[0] if result.errors else None),
        )["evidence_id"])
        self._notify(result)
        return result

    # ── operaciones §14 ──────────────────────────────────────────────────
    def open_flow(self) -> OperationResult:
        return self._op(FlowOp.OPEN_FLOW.value, self.driver.open_session,
                        verify=lambda p: Verdict.PASS if p.get("opened")
                        else Verdict.FAIL)

    def open_project(self, project_id: str) -> OperationResult:
        return self._op(FlowOp.OPEN_PROJECT.value,
                        lambda: self.driver.open_project(project_id),
                        verify=lambda p: Verdict.PASS if p.get("opened")
                        else Verdict.FAIL)

    def select_project(self, project_id: str) -> OperationResult:
        return self._op(FlowOp.SELECT_PROJECT.value,
                        lambda: self.driver.open_project(project_id),
                        verify=lambda p: Verdict.PASS if p.get("opened")
                        else Verdict.FAIL)

    def set_prompt(self, job: FlowJobSpec) -> OperationResult:
        def action() -> dict[str, Any]:
            job.validate()               # §15: prompt externo no vacío
            self.pending_job = job
            return {"prompt_registered": True, "kind": job.kind,
                    "scene": job.scene_number, "part": job.part,
                    "prompt_chars": len(job.prompt),
                    "note": "prompt EXTERNO registrado — HANDS no lo inventa"}
        return self._op(FlowOp.SET_PROMPT.value, action)

    def set_configuration(self, params: dict[str, Any]) -> OperationResult:
        def action() -> dict[str, Any]:
            self.configuration = dict(params)
            return {"configuration": dict(params)}
        return self._op(FlowOp.SET_CONFIGURATION.value, action)

    def start_generation(self) -> OperationResult:
        def action() -> dict[str, Any]:
            if self.pending_job is None:
                raise ValidationError("sin SET_PROMPT previo — nada que generar")
            handle = self.driver.submit(self.pending_job)
            handle["_job"] = self.pending_job.to_dict()
            return {"handle": {k: v for k, v in handle.items() if k != "_job"},
                    "prompt_source": "external (§15)"}
        return self._op(FlowOp.START_GENERATION.value, action)

    def wait_generation(self, handle: dict[str, Any], *,
                        timeout_s: float | None = None) -> OperationResult:
        """WAIT_GENERATION con WaitEngine (§10): poll → done|error, nunca infinito."""
        result = OperationResult(operation_id=new_id("flow"),
                                 name=FlowOp.WAIT_GENERATION.value,
                                 operator=self.name, status=State.WAITING,
                                 started_at=now_iso())
        timeout = timeout_s or self.wait_timeout_s
        try:
            self.killswitch.check()
            decision = self.permissions.check_domain(self.driver.host)
            self.permissions.require(decision)
            outcome = self.waits.wait_until(
                lambda obs: (self.driver.poll(handle).get("status") in ("done", "error")),
                timeout_s=timeout, poll_interval_s=self.poll_interval_s,
                provider=lambda: self.driver.poll(handle),
                description="espera de generación Flow")
            result.result["wait"] = outcome.to_dict()
            final = self.driver.poll(handle)
            result.result["final"] = {k: v for k, v in final.items()
                                      if k != "asset_bytes"}
            if outcome.ok and final.get("status") == "done":
                result.verification = {"verdict": Verdict.PASS.value,
                                       "expected": "status=done",
                                       "observed": final.get("status")}
                result.status = State.COMPLETED
            elif final.get("status") == "error":
                result.verification = {"verdict": Verdict.FAIL.value,
                                       "expected": "status=done",
                                       "observed": "error"}
                result.status = State.FAILED
            else:
                result.status = State.TIMEOUT
                result.add_error(HandsTimeoutError(
                    f"generación Flow no terminó en {timeout}s",
                    details={"last": final}))
        except StoppedError as err:
            result.status = State.STOPPED
            result.add_error(err)
        except PermissionDeniedError as err:                      # §16
            result.status = State.BLOCKED
            result.add_error(err)
        except HandsError as err:
            result.status = State.FAILED
            result.add_error(err)
        result.finished_at = now_iso()
        result.evidence_ids.append(self.evidence.record(
            action=FlowOp.WAIT_GENERATION.value, operator=self.name,
            observed_state=result.result, result=result.status.value,
            error=(result.errors[0] if result.errors else None))["evidence_id"])
        self._notify(result)
        return result

    def detect_result(self, handle: dict[str, Any]) -> OperationResult:
        return self._op(FlowOp.DETECT_RESULT.value,
                        lambda: self.driver.poll(handle),
                        verify=lambda p: Verdict.PASS
                        if p.get("status") in ("done", "error", "generating", "queued")
                        else Verdict.UNKNOWN)

    def download_result(self, handle: dict[str, Any], *,
                        dest_name: str | None = None,
                        idempotent: bool = True) -> OperationResult:
        """DOWNLOAD_RESULT con idempotencia §26 y file verification §23."""
        result = OperationResult(operation_id=new_id("flow"),
                                 name=FlowOp.DOWNLOAD_RESULT.value,
                                 operator=self.name, status=State.RUNNING,
                                 started_at=now_iso())
        start = time.monotonic()

        def finish(status: State) -> OperationResult:
            result.status = status
            result.finished_at = now_iso()
            result.duration_ms = int((time.monotonic() - start) * 1000)
            result.evidence_ids.append(self.evidence.record(
                action=FlowOp.DOWNLOAD_RESULT.value, operator=self.name,
                target=result.result.get("downloaded"),
                expected_state=result.verification or None,
                observed_state=result.result or None,
                result=status.value,
                error=(result.errors[0] if result.errors else None),
            )["evidence_id"])
            self._notify(result)
            return result

        try:
            self.killswitch.check()                                   # §27
            decision = self.permissions.check_domain(self.driver.host)
            self.permissions.require(decision)                        # §16
            result.result["permission"] = decision.to_dict()

            job = handle.get("_job")
            if job is None and self.pending_job is not None:
                job = self.pending_job.to_dict()
            kind = (job or {}).get("kind", "image")
            ext = "png" if kind == "image" else "mp4"
            name = dest_name or f"flow_result_{new_id('dl')}.{ext}"
            dest = self.workspace.path_for("downloads", name)

            # §26 idempotencia: ¿ya existe y verifica?
            if idempotent and dest.exists():
                existing = verify_file(dest,
                                       media_kind=("png" if kind == "image" else "mp4"))
                if existing.verdict is Verdict.PASS:
                    result.result["downloaded"] = str(dest)
                    result.result["skipped"] = "ya existe y verifica PASS (§26)"
                    result.verification = existing.to_dict()
                    return finish(State.COMPLETED)

            asset = self.driver.fetch(handle)                         # ACTION
            if asset is None:
                result.add_error(ActionFailedError(
                    "driver no devolvió bytes del asset",
                    details={"driver": self.driver.kind}))
                return finish(State.FAILED)

            dest.write_bytes(asset)
            media_kind = "png" if kind == "image" else "mp4"
            fv = verify_file(dest, min_size=1, extensions=(ext,),
                             media_kind=media_kind)                   # VERIFY §23
            result.verification = fv.to_dict()
            result.result["downloaded"] = str(dest)
            result.result["size"] = len(asset)
            result.result["sha256"] = fv.sha256
            if fv.verdict is Verdict.PASS:
                return finish(State.COMPLETED)
            if fv.verdict is Verdict.UNKNOWN:
                return finish(State.UNKNOWN)                          # §11
            result.add_error(ActionFailedError(
                "asset descargado NO pasa verificación de medios (§23) — "
                "p.ej. HTML de error disfrazado",
                details={"checks": [c.to_dict() for c in fv.checks]}))
            return finish(State.FAILED)
        except StoppedError as err:
            result.add_error(err)
            return finish(State.STOPPED)
        except PermissionDeniedError as err:                      # §16
            result.add_error(err)
            return finish(State.BLOCKED)
        except BlockedError as err:
            result.add_error(err)
            return finish(State.BLOCKED)
        except HandsError as err:
            result.add_error(err)
            return finish(State.FAILED)
        except Exception as err:                                      # noqa: BLE001
            from .contracts import error_from_exception
            result.add_error(error_from_exception(err))
            return finish(State.FAILED)

    def verify_result(self, asset_path: str | Path, kind: str = "image") -> OperationResult:
        media_kind = "png" if kind == "image" else "mp4"
        return self._op(
            FlowOp.VERIFY_RESULT.value,
            lambda: {"path": str(asset_path)},
            verify=lambda p: verify_file(
                asset_path, min_size=1, media_kind=media_kind).verdict,
        )

    def report_result(self, handle: dict[str, Any], *,
                      asset_path: str | None = None) -> OperationResult:
        def action() -> dict[str, Any]:
            return {"report": {
                "handle": {k: v for k, v in handle.items() if k != "_job"},
                "asset_path": asset_path,
                "driver": self.driver.kind,
                "reported_at": now_iso(),
            }}
        return self._op(FlowOp.REPORT_RESULT.value, action)

    def close(self) -> OperationResult:
        return self._op("CLOSE_FLOW_SESSION", self.driver.close_session)
