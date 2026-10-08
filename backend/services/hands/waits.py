"""
HANDS · Wait Engine — espera basada en condiciones (§10).

Kinds soportados (equivalentes conceptuales del brief):

  WAIT_FOR_WINDOW · WAIT_FOR_ELEMENT · WAIT_FOR_FILE · WAIT_FOR_DOWNLOAD ·
  WAIT_FOR_PROCESS · WAIT_FOR_STATE · WAIT_FOR_VISUAL_CHANGE · WAIT_UNTIL

Cada espera lleva: condición, timeout (OBLIGATORIO, > 0 — nunca infinito),
intervalo de sondeo, resultado (WaitOutcome), error (taxonomía) y detalle
para evidencia. El kill switch se comprueba en CADA intervalo: una espera
en curso es cancelable (§27).

El tiempo viene del reloj inyectado (HandsClock/FakeClock): los tests de
timeout son deterministas y no duermen de verdad.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .clock import HandsClock
from .contracts import (HandsTimeoutError, StoppedError,
                        TargetSpec, ValidationError, now_iso)
from .killswitch import KillSwitch

WAIT_KINDS: tuple[str, ...] = (
    "WAIT_FOR_WINDOW", "WAIT_FOR_ELEMENT", "WAIT_FOR_FILE", "WAIT_FOR_DOWNLOAD",
    "WAIT_FOR_PROCESS", "WAIT_FOR_STATE", "WAIT_FOR_VISUAL_CHANGE", "WAIT_UNTIL",
)


@dataclass
class WaitSpec:
    """Especificación de una espera (condición + timeouts obligatorios)."""
    kind: str
    timeout_s: float
    poll_interval_s: float = 0.5
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def validate(self) -> None:
        if self.kind not in WAIT_KINDS:
            raise ValidationError(f"wait kind desconocido: \"{self.kind}\"",
                                  details={"valid": list(WAIT_KINDS)})
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0:
            raise ValidationError(
                f"WAIT {self.kind}: timeout_s obligatorio y > 0 (recibido {self.timeout_s!r}) "
                "— no existen esperas infinitas en HANDS")
        if not isinstance(self.poll_interval_s, (int, float)) or self.poll_interval_s <= 0:
            raise ValidationError("poll_interval_s debe ser > 0")


@dataclass
class WaitOutcome:
    """Resultado estructurado de una espera."""
    ok: bool
    kind: str
    timeout_s: float
    elapsed_s: float
    polls: int
    observed: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "kind": self.kind, "timeout_s": self.timeout_s,
            "elapsed_s": round(self.elapsed_s, 3), "polls": self.polls,
            "observed": self.observed, "error": self.error,
            "detail": self.detail, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def raise_if_failed(self) -> "WaitOutcome":
        """Convierte un timeout en excepción (útil para flujos que abortan)."""
        if self.ok:
            return self
        raise HandsTimeoutError(
            self.error.get("message", "wait timeout") if self.error else "wait timeout",
            details={"kind": self.kind, "detail": self.detail})


ObservationProvider = Callable[[], Any]


class WaitEngine:
    """Motor de espera por condiciones (tiempo y kill switch inyectables)."""

    def __init__(self, clock: HandsClock, *, killswitch: KillSwitch | None = None,
                 listeners: list[Callable[[WaitOutcome], None]] | None = None):
        self.clock = clock
        self.killswitch = killswitch
        self.listeners = list(listeners or [])

    # ── núcleo ───────────────────────────────────────────────────────────
    def wait(self, spec: WaitSpec, *,
             provider: ObservationProvider | None = None) -> WaitOutcome:
        """Ejecuta la espera. Timeout → WaitOutcome(ok=False, error=TIMEOUT).

        Kill switch activo → StoppedError (cancelación dura, §27).
        """
        spec.validate()
        started_at = self.clock.iso_now()
        start = self.clock.monotonic()
        polls = 0
        last_obs: Any = None
        outcome: WaitOutcome | None = None

        while True:
            if self.killswitch is not None:
                self.killswitch.check()          # cancelación dura
            polls += 1
            if provider is not None:
                last_obs = provider()
            ok, detail = self._evaluate(spec, last_obs)
            elapsed = self.clock.monotonic() - start
            if ok:
                outcome = WaitOutcome(ok=True, kind=spec.kind,
                                      timeout_s=spec.timeout_s, elapsed_s=elapsed,
                                      polls=polls, detail=detail,
                                      started_at=started_at,
                                      finished_at=now_iso())
                break
            if elapsed >= spec.timeout_s:
                err = HandsTimeoutError(
                    f"WAIT {spec.kind} timeout tras {spec.timeout_s}s "
                    f"({polls} sondeos){' — ' + spec.description if spec.description else ''}",
                    details={"kind": spec.kind, "detail": detail})
                outcome = WaitOutcome(ok=False, kind=spec.kind,
                                      timeout_s=spec.timeout_s, elapsed_s=elapsed,
                                      polls=polls,
                                      observed=_obs_dict(last_obs),
                                      error=err.to_dict(), detail=detail,
                                      started_at=started_at,
                                      finished_at=now_iso())
                break
            self.clock.sleep(spec.poll_interval_s)

        for listener in self.listeners:
            try:
                listener(outcome)
            except Exception:                     # noqa: BLE001 — listener nunca tumba
                continue
        return outcome

    # ── evaluación por kind ──────────────────────────────────────────────
    def _evaluate(self, spec: WaitSpec, obs: Any) -> tuple[bool, dict[str, Any]]:
        params = spec.params
        if spec.kind == "WAIT_FOR_WINDOW":
            expected = params.get("name")
            actual = getattr(obs, "window", None)
            matched = bool(actual) and _fnmatch_any(str(actual), [expected])
            return matched, {"expected_window": expected, "actual_window": actual}

        if spec.kind == "WAIT_FOR_ELEMENT":
            target = TargetSpec.from_dict(params.get("target"))
            if target is None:
                raise ValidationError("WAIT_FOR_ELEMENT exige params.target")
            matched_el = _match_element(obs, target)
            return (matched_el is not None,
                    {"matched_ref": matched_el.ref_id if matched_el else None})

        if spec.kind == "WAIT_FOR_FILE":
            path = Path(params["path"])
            min_size = int(params.get("min_size", 0))
            exists = path.is_file()
            size = path.stat().st_size if exists else 0
            return (exists and size >= min_size,
                    {"path": str(path), "exists": exists, "size": size,
                     "min_size": min_size})

        if spec.kind == "WAIT_FOR_DOWNLOAD":
            directory = Path(params["dir"])
            pattern = params.get("pattern", "*")
            min_size = int(params.get("min_size", 1))
            matches = [p for p in directory.glob(pattern) if p.is_file()
                       and p.stat().st_size >= min_size]
            return bool(matches), {
                "dir": str(directory), "pattern": pattern,
                "found": [p.name for p in matches]}

        if spec.kind == "WAIT_FOR_PROCESS":
            name = params.get("name")
            pid = params.get("pid")
            expected_state = params.get("state")
            procs = list(getattr(obs, "processes", []) or [])
            for proc in procs:
                if name and proc.name != name:
                    continue
                if pid is not None and proc.pid != pid:
                    continue
                if expected_state and proc.state != expected_state:
                    continue
                return True, {"matched": proc.to_dict()}
            return False, {"expected": {"name": name, "pid": pid,
                                        "state": expected_state},
                           "seen": [p.to_dict() for p in procs]}

        if spec.kind == "WAIT_FOR_STATE":
            expected = params.get("state")
            actual = getattr(obs, "state", None) or (obs if isinstance(obs, str) else None)
            return (actual == expected,
                    {"expected_state": expected, "actual_state": actual})

        if spec.kind == "WAIT_FOR_VISUAL_CHANGE":
            baseline = params.get("baseline_digest")
            current = getattr(obs, "visual_digest", None)
            changed = bool(baseline) and current is not None and current != baseline
            return changed, {"baseline": baseline, "current": current}

        if spec.kind == "WAIT_UNTIL":
            predicate = params.get("predicate")
            if not callable(predicate):
                raise ValidationError("WAIT_UNTIL exige params.predicate callable")
            value = predicate(obs)
            return bool(value), {"predicate_result": bool(value)}

        raise ValidationError(f"wait kind sin evaluador: {spec.kind}")

    # ── helpers con nombre (§10) ─────────────────────────────────────────
    def wait_for_window(self, name: str, *, timeout_s: float, provider=None,
                        poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_WINDOW", timeout_s, poll_interval_s,
                                  {"name": name}, f"ventana \"{name}\""), provider=provider)

    def wait_for_element(self, target: TargetSpec, *, timeout_s: float,
                         provider=None, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_ELEMENT", timeout_s, poll_interval_s,
                                  {"target": target.to_dict()}), provider=provider)

    def wait_for_file(self, path: str | Path, *, timeout_s: float,
                      min_size: int = 0, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_FILE", timeout_s, poll_interval_s,
                                  {"path": str(path), "min_size": min_size}))

    def wait_for_download(self, directory: str | Path, *, timeout_s: float,
                          pattern: str = "*", min_size: int = 1,
                          poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_DOWNLOAD", timeout_s, poll_interval_s,
                                  {"dir": str(directory), "pattern": pattern,
                                   "min_size": min_size}))

    def wait_for_process(self, *, name: str | None = None, pid: int | None = None,
                         state: str | None = None, timeout_s: float,
                         provider=None, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_PROCESS", timeout_s, poll_interval_s,
                                  {"name": name, "pid": pid, "state": state}),
                         provider=provider)

    def wait_for_state(self, expected: str, *, timeout_s: float,
                       provider=None, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_STATE", timeout_s, poll_interval_s,
                                  {"state": expected}), provider=provider)

    def wait_for_visual_change(self, baseline_digest: str, *, timeout_s: float,
                               provider=None, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_FOR_VISUAL_CHANGE", timeout_s,
                                  poll_interval_s, {"baseline_digest": baseline_digest}),
                         provider=provider)

    def wait_until(self, predicate: Callable[[Any], bool], *, timeout_s: float,
                   provider=None, poll_interval_s: float = 0.5,
                   description: str = "") -> WaitOutcome:
        return self.wait(WaitSpec("WAIT_UNTIL", timeout_s, poll_interval_s,
                                  {"predicate": predicate}, description),
                         provider=provider)


# ── helpers locales ──────────────────────────────────────────────────────
def _fnmatch_any(value: str, patterns: list[Any]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatchcase(value, str(p)) for p in patterns if p)


def _match_element(obs: Any, target: TargetSpec):
    finder = getattr(obs, "find_element", None)
    if finder is None:
        return None

    def predicate(el) -> bool:
        if target.semantic and el.semantic != target.semantic:
            return False
        if target.accessibility and el.accessibility != target.accessibility:
            return False
        if target.text and (el.text or "") != target.text:
            return False
        if target.dom and el.dom != target.dom:
            return False
        return True

    return finder(predicate)


def _obs_dict(obs: Any) -> dict[str, Any] | None:
    if obs is None:
        return None
    if hasattr(obs, "to_dict"):
        return obs.to_dict()
    if isinstance(obs, dict):
        return obs
    return {"state": str(obs)}
