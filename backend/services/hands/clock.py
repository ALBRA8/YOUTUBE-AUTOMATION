"""
HANDS · Reloj — abstracción de tiempo inyectable y parámetros de timeout.

Toda operación potencialmente bloqueante usa el reloj inyectado (§25):
* HandsClock  — reloj real (monotónico + wall clock + sleep).
* FakeClock   — reloj determinista para tests (sleep() avanza el tiempo al
  instante: los timeouts se prueban sin esperar de verdad).

Ninguna espera es infinita: todo timeout viene de HandsConfig o del propio
WaitSpec, y se valida > 0.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .contracts import ValidationError, now_iso


class HandsClock:
    """Reloj real del sistema."""

    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def iso_now(self) -> str:
        return now_iso()


@dataclass
class FakeClock(HandsClock):
    """Reloj determinista: sleep() avanza el tiempo virtual sin esperar.

    auto_sleep=True (default) hace que sleep(s) llame a advance(s) — así un
    WaitEngine con poll interval recorre su ciclo completo de forma síncrona
    y los timeouts saltan exactamente cuando deben.
    """

    _t: float = 0.0
    _wall: float = 0.0
    auto_sleep: bool = True
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self._t

    def wall(self) -> float:
        return self._wall

    def advance(self, seconds: float) -> None:
        self._t += float(seconds)
        self._wall += float(seconds)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        if self.auto_sleep and seconds > 0:
            self.advance(seconds)

    def iso_now(self) -> str:
        return time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall if self._wall else time.time())
        )


# ── §25 · defaults de timeout configurables (nunca hardcodeados en ops) ──
@dataclass
class TimeoutsConfig:
    """Timeouts por familia de operación (segundos). Todos > 0 y obligatorios."""
    action_s: float = 30.0          # acción de escritorio/driver puntual
    wait_s: float = 60.0            # WaitEngine por defecto
    download_s: float = 600.0       # descarga de asset Flow
    process_s: float = 300.0        # proceso permitido (EXECUTE_ALLOWED)
    lock_s: float = 10.0            # adquisición de locks
    poll_interval_s: float = 0.5    # intervalo de sondeo de waits
    recover_backoff_s: float = 1.0  # backoff base del RecoveryEngine

    def validate(self) -> None:
        fields = {
            "action_s": self.action_s, "wait_s": self.wait_s,
            "download_s": self.download_s, "process_s": self.process_s,
            "lock_s": self.lock_s, "poll_interval_s": self.poll_interval_s,
            "recover_backoff_s": self.recover_backoff_s,
        }
        for name, value in fields.items():
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValidationError(
                    f"timeout {name} debe ser > 0 (recibido: {value!r})")
