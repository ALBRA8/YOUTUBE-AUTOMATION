"""
HANDS · Recovery Engine — recuperación controlada (§24).

Modelo del brief:  OBSERVE → WAIT → VERIFY → RETRY → RECOVER → RETRY →
STOP → BLOCKED. Implementación:

    RecoveryEngine.run(attempt, policy, ...) ejecuta `attempt` con un
    presupuesto ACOTADO de reintentos (total = 1 + max_retries — jamás
    infinito). Entre intento e intento aplica el ciclo:

      observe()  — re-observar el entorno (callback inyectado)
      wait(backoff) — espera exponencial con el reloj inyectado
      precheck() — VERIFY del estado existente (p.ej. ¿ya se resolvió solo?)
      recover()  — acciones de recuperación declaradas (callbacks)

    Si el error no es reintentable (PERMISSION_DENIED, BLOCKED, STOPPED,
    VALIDATION_ERROR...) se propaga INMEDIATAMENTE — no tiene sentido
    reintentar un permiso denegado.
    Al agotar el presupuesto: RecoveryFailedError con el historial completo
    de intentos (auditable) — el llamador decide STOP/BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .clock import HandsClock
from .contracts import (ErrorCode, HandsError,
                        PermissionDeniedError, RecoveryFailedError,
                        StoppedError, BlockedError, ValidationError,
                        error_from_exception)
from .killswitch import KillSwitch

# errores que NUNCA se reintentan (§24: recovery controlado, no ciego)
NON_RETRYABLE: frozenset[ErrorCode] = frozenset({
    ErrorCode.PERMISSION_DENIED, ErrorCode.BLOCKED, ErrorCode.STOPPED,
    ErrorCode.VALIDATION_ERROR,
})

RETRYABLE_DEFAULT: frozenset[ErrorCode] = frozenset({
    ErrorCode.TIMEOUT, ErrorCode.ACTION_FAILED, ErrorCode.TARGET_NOT_FOUND,
    ErrorCode.VERIFICATION_FAILED, ErrorCode.RECOVERY_FAILED, ErrorCode.UNKNOWN,
})


@dataclass
class RecoveryPolicy:
    """Presupuesto de recuperación (§24-§25) — valores acotados."""
    max_retries: int = 2
    backoff_s: float = 1.0
    backoff_multiplier: float = 2.0
    retry_on: tuple[ErrorCode, ...] | None = None   # None → RETRYABLE_DEFAULT

    def validate(self) -> None:
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValidationError("max_retries debe ser int >= 0 (acotado por diseño)")
        if self.backoff_s < 0 or self.backoff_multiplier < 1.0:
            raise ValidationError("backoff_s >= 0 y backoff_multiplier >= 1.0")

    @property
    def total_attempts(self) -> int:
        return self.max_retries + 1

    def retryable(self, code: ErrorCode) -> bool:
        allowed = self.retry_on or tuple(RETRYABLE_DEFAULT)
        return code in allowed and code not in NON_RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {"max_retries": self.max_retries, "backoff_s": self.backoff_s,
                "backoff_multiplier": self.backoff_multiplier,
                "retry_on": [c.value for c in (self.retry_on or tuple(RETRYABLE_DEFAULT))]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RecoveryPolicy":
        data = data or {}
        retry_on = data.get("retry_on")
        return cls(
            max_retries=int(data.get("max_retries", 2)),
            backoff_s=float(data.get("backoff_s", 1.0)),
            backoff_multiplier=float(data.get("backoff_multiplier", 2.0)),
            retry_on=tuple(ErrorCode(c) for c in retry_on) if retry_on else None,
        )


@dataclass
class AttemptRecord:
    index: int
    ok: bool
    error: dict[str, Any] | None = None
    recovered_with: list[str] = field(default_factory=list)
    backoff_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "ok": self.ok, "error": self.error,
                "recovered_with": self.recovered_with, "backoff_s": self.backoff_s}


class RecoveryEngine:
    """Ejecución con reintentos acotados y ciclo OBSERVE→WAIT→VERIFY→RECOVER."""

    def __init__(self, clock: HandsClock, *, killswitch: KillSwitch | None = None):
        self.clock = clock
        self.killswitch = killswitch

    def run(self,
            attempt: Callable[[], Any],
            policy: RecoveryPolicy,
            *,
            observe: Callable[[], Any] | None = None,
            precheck: Callable[[], bool] | None = None,
            recover: Callable[[HandsError], list[str] | None] | None = None,
            description: str = "") -> tuple[Any, list[AttemptRecord]]:
        """Ejecuta `attempt` con recovery. Devuelve (resultado, historial).

        attempt    — operación a intentar (lanza HandsError si falla)
        observe    — §24 OBSERVE: re-observación entre intentos (callback)
        precheck   — §24 VERIFY: True si el problema se resolvió solo
        recover    — §24 RECOVER: acciones de recuperación; devuelve nombres
                     de acciones aplicadas (para evidencia)
        """
        policy.validate()
        history: list[AttemptRecord] = []
        backoff = policy.backoff_s

        for index in range(policy.total_attempts):
            if self.killswitch is not None:
                self.killswitch.check()
            try:
                result = attempt()
                history.append(AttemptRecord(index=index, ok=True))
                return result, history
            except StoppedError:
                raise                      # el kill switch no se "recupera"
            except HandsError as err:
                record = AttemptRecord(index=index, ok=False, error=err.to_dict())
                history.append(record)
                last_err: HandsError = err
            except Exception as exc:       # noqa: BLE001 — normalizado a taxonomía
                err = error_from_exception(exc)
                record = AttemptRecord(index=index, ok=False, error=err.to_dict())
                history.append(record)
                last_err = err

            # ¿vale la pena reintentar?
            if not policy.retryable(last_err.code):
                raise last_err          # no reintentable: propaga el original
            if index == policy.max_retries:
                break                    # presupuesto agotado: RecoveryFailedError

            # ── ciclo §24 entre intentos ─────────────────────────────────
            if self.killswitch is not None:
                self.killswitch.check()
            if observe is not None:
                try:
                    observe()
                except Exception:          # noqa: BLE001 — observar no debe matar
                    pass
            if backoff > 0:
                self.clock.sleep(backoff)
                record.backoff_s = backoff
                backoff *= policy.backoff_multiplier
            if precheck is not None:
                try:
                    if precheck():
                        record.recovered_with.append("precheck:solved")
                        continue            # siguiente intento con estado saneado
                except Exception:           # noqa: BLE001
                    pass
            if recover is not None:
                try:
                    applied = recover(last_err) or []
                    record.recovered_with.extend(str(a) for a in applied)
                except Exception as exc:    # noqa: BLE001 — recover fallido es info
                    record.recovered_with.append(f"recover_error:{type(exc).__name__}")

        raise RecoveryFailedError(
            f"recovery agotado ({len(history)} intentos)"
            f"{f' — {description}' if description else ''}: "
            f"[{last_err.code.value}] {last_err.message}",
            details={"attempts": [h.to_dict() for h in history],
                     "policy": policy.to_dict(),
                     "last_error": last_err.to_dict()},
        )
