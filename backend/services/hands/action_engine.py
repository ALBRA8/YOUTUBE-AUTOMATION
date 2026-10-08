"""
HANDS · Action Engine — el ciclo canónico de toda acción (§7).

    OBSERVE → IDENTIFY → ACTION → OBSERVE → VERIFY

Prohibido el patrón `click(x,y); sleep(n); click(x,y)`: toda acción pasa por
este motor, que garantiza (en orden):

  0. kill switch check  (§27 — cancelación dura)
  1. GATE DE PERMISOS   (§16 — deny by default; denegado ⇒ BLOCKED, jamás
     se intenta automáticamente)
  2. IDEMPOTENCIA       (§26 — idempotency_check sobre observación fresca:
     si el estado ya está satisfecho, NO se repite la acción)
  3. OBSERVE before     (observación estructurada pre-acción)
  4. IDENTIFY           (jerarquía §8 vía TargetResolver)
  5. ACTION             (backend.execute con timeout obligatorio)
  6. OBSERVE after      (observación estructurada post-acción)
  7. VERIFY             (§12 — PASS/FAIL/UNKNOWN; UNKNOWN jamás deriva en
     COMPLETED: la operación queda en estado UNKNOWN)
  8. EVIDENCE + AUDIT   (§21/§31 — registro hasheado y redactado)

Recovery opcional (§24): si spec.recovery declara una política, las fases
4-7 se ejecutan dentro del RecoveryEngine con reintentos ACOTADOS.
"""
from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from .clock import HandsClock
from .contracts import (ActionSpec, BlockedError, Op,
                        OperationResult, OP_PERMISSION_CATEGORY,
                        Observation, PermissionDeniedError,
                        State, StoppedError, TargetNotFoundError,
                        HandsTimeoutError, HandsError, error_from_exception,
                        new_id, now_iso)
from .evidence import AuditTrail, EvidenceLayer
from .identify import TargetResolver
from .killswitch import KillSwitch
from .permissions import PermissionModel
from .recovery import RecoveryEngine, RecoveryPolicy
from .verification import VerificationEngine, Verdict


@runtime_checkable
class ExecutionBackend(Protocol):
    """Backend que ejecuta acciones físicas (Desktop) o de driver (Flow)."""

    def observe(self) -> Observation: ...

    def perform(self, name: str, match: Any, params: dict[str, Any]) -> dict[str, Any]: ...

    def stop(self) -> None: ...


class ActionEngine:
    """Motor de acciones — puertas de seguridad + ciclo §7 + evidencia."""

    def __init__(self, *, permissions: PermissionModel,
                 resolver: TargetResolver, verification: VerificationEngine,
                 recovery: RecoveryEngine, clock: HandsClock,
                 killswitch: KillSwitch, evidence: EvidenceLayer,
                 audit: AuditTrail, action_timeout_s: float = 30.0,
                 allow_coordinate_fallback: bool = False,
                 on_result: Any = None):
        self.permissions = permissions
        self.resolver = resolver
        self.verification = verification
        self.recovery = recovery
        self.clock = clock
        self.killswitch = killswitch
        self.evidence = evidence
        self.audit = audit
        self.action_timeout_s = action_timeout_s
        self.allow_coordinate_fallback = allow_coordinate_fallback
        self.on_result = on_result        # p.ej. session.add_action (§19)

    # ════════════════════════════════════════════════════════════════════
    # ejecución
    # ════════════════════════════════════════════════════════════════════
    def execute(self, spec: ActionSpec, backend: ExecutionBackend) -> OperationResult:
        """Ejecuta la acción bajo el modelo §7 y devuelve OperationResult.

        Nunca lanza HandsError hacia fuera: el error viaja dentro del
        resultado (status + errors[]) — la sesión siempre queda auditable.
        """
        operation_id = new_id("op")
        result = OperationResult(operation_id=operation_id, name=spec.name,
                                 operator=spec.operator, status=State.RUNNING,
                                 started_at=now_iso())
        start = time.monotonic()
        self.audit.append("action_start", action=spec.name,
                          operator=spec.operator,
                          params=spec.params, operation_id=operation_id)
        try:
            self.killswitch.check()                                   # §27
            self._gate_permissions(spec, backend, result)             # §16
            if result.status is State.RUNNING:
                self._run_pipeline(spec, backend, result)             # §7
        except StoppedError as err:
            result.status = State.STOPPED
            result.add_error(err)
        except PermissionDeniedError as err:                          # §16: BLOCKED
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
            normalized = error_from_exception(err)
            result.status = State.FAILED
            result.add_error(normalized)

        result.finished_at = now_iso()
        result.duration_ms = int((time.monotonic() - start) * 1000)

        # §21: evidencia de la operación (éxito o fallo — siempre)
        result.evidence_ids.append(self.evidence.record(
            action=spec.name,
            target=spec.target.to_dict() if spec.target else None,
            expected_state=_verify_brief(spec.verify),
            observed_state=(result.verification.get("observed")
                            if result.verification else result.result),
            result=result.status.value,
            refs={"operation_id": operation_id,
                  "verification": result.verification or None},
            error=(result.errors[0] if result.errors else None),
            operator=spec.operator,
        )["evidence_id"])
        self.audit.append("action_end", action=spec.name,
                          operation_id=operation_id,
                          status=result.status.value,
                          duration_ms=result.duration_ms)
        if self.on_result is not None:
            try:
                self.on_result(result)          # §19: acción → sesión auditable
            except Exception:                   # noqa: BLE001 — listener no tumba
                pass
        return result

    # ════════════════════════════════════════════════════════════════════
    # fases
    # ════════════════════════════════════════════════════════════════════
    def _run_pipeline(self, spec: ActionSpec, backend: ExecutionBackend,
                      result: OperationResult) -> None:
        policy = RecoveryPolicy.from_dict(spec.recovery) if spec.recovery else None

        def attempt() -> dict[str, Any]:
            return self._single_pass(spec, backend, result)

        if policy is not None:
            # §24: reintentos acotados con re-observación entre intentos.
            # _single_pass ya acumula observaciones/verificación en
            # result.result — NO se sobreescribe (historia completa).
            self.recovery.run(
                attempt, policy,
                observe=lambda: backend.observe(),
                precheck=(lambda: bool(spec.idempotency_check(backend.observe())))
                if spec.idempotency_check else None,
                description=f"acción {spec.name}",
            )
        else:
            attempt()

        # estado final según verificación (fase VERIFY decide §11/§12)
        verdict = result.verification.get("verdict") if result.verification else None
        if verdict == Verdict.PASS.value or verdict == "NOT_SPECIFIED":
            result.status = State.COMPLETED
        elif verdict == Verdict.UNKNOWN.value:
            result.status = State.UNKNOWN        # §11: UNKNOWN nunca → COMPLETED
        else:
            result.status = State.FAILED
            if not result.errors:
                result.add_error(_verification_error(spec, result.verification))

    def _single_pass(self, spec: ActionSpec, backend: ExecutionBackend,
                     result: OperationResult) -> dict[str, Any]:
        # §26 idempotencia: ¿el estado ya está satisfecho?
        if spec.idempotency_check is not None:
            fresh = backend.observe()
            try:
                if spec.idempotency_check(fresh):
                    result.verification = {
                        "verdict": Verdict.PASS.value,
                        "expected": "estado ya satisfecho (idempotencia §26)",
                        "observed": fresh.to_dict(),
                    }
                    result.result["already_satisfied"] = True
                    result.result["observation"] = fresh.to_dict()
                    return result.result
            except Exception as exc:              # noqa: BLE001 — check roto no skip
                result.result["idempotency_check_error"] = \
                    f"{type(exc).__name__}: {exc}"

        # §7 fase 1: OBSERVE before
        obs_before = backend.observe()
        result.result["observation_before"] = obs_before.to_dict()

        # §7 fase 2: IDENTIFY
        match = None
        if spec.target is not None:
            match = self.resolver.resolve(spec.target, obs_before)
            result.result["target_match"] = match.to_dict()

        # §7 fase 3: ACTION (timeout obligatorio propagado al backend)
        params = dict(spec.params)
        params["_timeout_s"] = spec.timeout_s or self.action_timeout_s
        outcome = backend.perform(spec.name, match, params)
        if not isinstance(outcome, dict):
            outcome = {"outcome": outcome}

        # §7 fase 4: OBSERVE after
        obs_after = backend.observe()
        result.result["observation_after"] = obs_after.to_dict()
        result.result["action_outcome"] = outcome

        # §7 fase 5: VERIFY
        if spec.verify is not None:
            vres = self.verification.verify(spec.verify, obs_after)
            result.verification = vres.to_dict()
            if vres.verdict is Verdict.FAIL:
                from .contracts import VerificationFailedError
                raise VerificationFailedError(
                    f"verificación FALLIDA tras {spec.name}",
                    details=vres.to_dict())
            if vres.verdict is Verdict.UNKNOWN:
                # estado incierto: se registra y la operación NO es COMPLETED
                result.result["verification_unknown"] = vres.to_dict()
        else:
            result.verification = {"verdict": "NOT_SPECIFIED",
                                   "expected": None,
                                   "observed": obs_after.to_dict()}
        return outcome

    # ════════════════════════════════════════════════════════════════════
    # permisos (§16) — deny by default por categoría
    # ════════════════════════════════════════════════════════════════════
    def _gate_permissions(self, spec: ActionSpec, backend: ExecutionBackend,
                          result: OperationResult) -> None:
        name = spec.name
        category = OP_PERMISSION_CATEGORY.get(name)
        if category is None:
            raise PermissionDeniedError(
                f"operación \"{name}\" sin categoría de permiso conocida",
                details={"category": None})
        decision = None
        params = spec.params
        if category == "application":
            decision = self.permissions.check_application(
                str(params.get("application") or params.get("name")
                    or params.get("window") or ""))
        elif category == "domain":
            target_host = (params.get("domain") or params.get("url")
                           or getattr(backend, "host", None) or "")
            decision = self.permissions.check_domain(str(target_host))
        elif category == "browser":
            url = params.get("url")
            decision = (self.permissions.check_browser(str(url)) if url else
                        _decision_browser_no_url())
        elif category == "filesystem":
            for key in ("path", "src", "dst", "from", "to", "dir"):
                if params.get(key):
                    decision = self.permissions.check_path(params[key])
                    if decision.denied:
                        break
            if decision is None:
                decision = _decision_fs_no_path()
        elif category == "command":
            decision = self.permissions.check_command(list(params.get("argv", [])))
        if decision is None or decision.denied:
            reason = decision.reason if decision else "sin decisión de permisos"
            raise PermissionDeniedError(reason, details={"category": category,
                                                         "operation": name})
        result.result["permission"] = decision.to_dict()

    # backend.stop util (kill switch propagado a los operadores)
    def stop_backend(self, backend: ExecutionBackend) -> None:
        try:
            backend.stop()
        except Exception:                     # noqa: BLE001 — stop nunca explota
            pass


# ── helpers locales ──────────────────────────────────────────────────────
def _decision_browser_no_url():
    from .permissions import PermissionDecision
    return PermissionDecision(
        True, "browser", "acción de navegador sin URL específica "
        "(regida por la allowlist de aplicación/dominio del entorno)")


def _decision_fs_no_path():
    from .permissions import PermissionDecision
    return PermissionDecision(
        True, "filesystem", "acción sin ruta específica (nada que validar)")


def _verify_brief(verify: Any) -> Any:
    if verify is None:
        return None
    if isinstance(verify, dict):
        return {"kind": verify.get("kind")}
    return {"kind": "callable"}


def _verification_error(spec: ActionSpec, verification: dict[str, Any]) -> HandsError:
    from .contracts import VerificationFailedError
    return VerificationFailedError(
        f"verificación FALLIDA tras {spec.name}",
        details={"verification": verification})
