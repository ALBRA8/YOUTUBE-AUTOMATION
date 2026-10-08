"""
HANDS · Kill Switch — parada segura global (§27).

Un único objeto KillSwitch por runtime. `engage()`:

  1. detiene NUEVAS acciones (todo motor hace killswitch.check() antes de actuar);
  2. cancela operaciones cancelables (los waits comprueban el switch en cada
     intervalo de sondeo y lanzan StoppedError);
  3. los operadores detienen sus backends (backend.stop());
  4. los locks del propietario se liberan (HandsRuntime.stop);
  5. la evidencia ya persistida permanece intacta (append-only);
  6. la sesión se cierra con final_status=STOPPED;
  7. el estado devuelto es STOPPED.

Es independiente de la lógica creativa (§27): no sabe nada de producción.
Thread-safe, idempotente y con razón registrada.
"""
from __future__ import annotations

import threading
from typing import Any

from .contracts import StoppedError, now_iso


class KillSwitch:
    """Interruptor de parada segura (thread-safe, idempotente)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._mutex = threading.Lock()
        self._reason: str | None = None
        self._engaged_at: str | None = None
        self._source: str | None = None

    # ── estado ───────────────────────────────────────────────────────────
    @property
    def engaged(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._mutex:
            return self._reason

    @property
    def engaged_at(self) -> str | None:
        with self._mutex:
            return self._engaged_at

    def source(self) -> str | None:
        with self._mutex:
            return self._source

    # ── acciones ─────────────────────────────────────────────────────────
    def engage(self, reason: str, *, source: str = "external") -> None:
        """Activa la parada (idempotente: la primera razón queda registrada)."""
        with self._mutex:
            if self._event.is_set():
                return
            self._reason = reason
            self._engaged_at = now_iso()
            self._source = source
        self._event.set()

    def disengage(self) -> None:
        """Rearme explícito (tests / reinicio controlado)."""
        with self._mutex:
            self._reason = None
            self._engaged_at = None
            self._source = None
        self._event.clear()

    def check(self) -> None:
        """Lanza StoppedError si está activado — llamar antes/durante cada paso."""
        if self._event.is_set():
            raise StoppedError(
                f"kill switch activo: {self._reason or 'sin razón declarada'}",
                details={"source": self._source, "engaged_at": self._engaged_at},
            )

    def wait_cancelable(self, timeout_s: float) -> bool:
        """Espera cancelable: True si se activó el switch, False si venció el timeout."""
        return self._event.wait(timeout=timeout_s)

    def status(self) -> dict[str, Any]:
        with self._mutex:
            return {
                "engaged": self._event.is_set(),
                "reason": self._reason,
                "engaged_at": self._engaged_at,
                "source": self._source,
            }
