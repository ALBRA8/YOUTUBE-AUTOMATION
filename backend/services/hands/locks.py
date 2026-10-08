"""
HANDS · Locks — protección contra carreras peligrosas (§20).

Dos niveles complementarios:

* LockManager (in-process) — locks con nombre por entorno ("desktop",
  "browser", "flow"). Un lock por nombre; mientras está tomado, cualquier
  otro propietario recibe BLOCKED (nunca espera infinito: timeout obligatorio).
  Re-adquisición por el MISMO propietario se rechaza (señal de bug, no de
  concurrencia) — evita dobles claims silenciosos dentro de una sesión.

* FileLock (cross-process) — lock de fichero atómico (O_CREAT|O_EXCL) con
  dueño y caducidad (stale_s): si el proceso dueño murió, el lock expira y
  puede reclaimarse con nota honesta. Sirve para coordinar HANDS con otros
  procesos del PC sobre el mismo entorno físico.

La arquitectura impide carreras peligrosas: los operadores de un runtime
adquieren su lock ANTES de tocar el entorno (lo cablea HandsRuntime).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import BlockedError, ValidationError, new_id, now_iso

DEFAULT_LOCKS: tuple[str, ...] = ("desktop", "browser", "flow")


# ════════════════════════════════════════════════════════════════════════
# Locks in-process con nombre
# ════════════════════════════════════════════════════════════════════════
@dataclass
class LockHandle:
    name: str
    owner: str
    acquired_at: str
    _manager: "LockManager | None" = field(default=None, repr=False, compare=False)

    def release(self) -> None:
        if self._manager is not None:
            self._manager.release(self)
            self._manager = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "owner": self.owner,
                "acquired_at": self.acquired_at}


class LockManager:
    """Locks con nombre, deny-if-busy con timeout, dueño explícito."""

    def __init__(self, lock_names: tuple[str, ...] = DEFAULT_LOCKS):
        self._names = tuple(lock_names) or DEFAULT_LOCKS
        self._mutex = threading.Lock()
        self._conditions: dict[str, threading.Condition] = {}
        self._holders: dict[str, LockHandle] = {}
        for name in self._names:
            self._conditions[name] = threading.Condition(self._mutex)

    # ── adquisición ──────────────────────────────────────────────────────
    def acquire(self, name: str, owner: str, *, timeout_s: float = 10.0) -> LockHandle:
        """Adquiere el lock; BlockedError si sigue busy al agotar el timeout."""
        if name not in self._conditions:
            raise ValidationError(f"lock desconocido: \"{name}\"",
                                  details={"valid": list(self._names)})
        if timeout_s <= 0:
            raise ValidationError("lock timeout_s debe ser > 0 (no hay esperas infinitas)")
        deadline = time.monotonic() + timeout_s
        cond = self._conditions[name]
        with cond:
            while True:
                holder = self._holders.get(name)
                if holder is None:
                    handle = LockHandle(name=name, owner=owner, acquired_at=now_iso(),
                                        _manager=self)
                    self._holders[name] = handle
                    return handle
                if holder.owner == owner:
                    raise ValidationError(
                        f"re-adquisición del lock \"{name}\" por el mismo dueño "
                        f"\"{owner}\" (doble claim — probable bug de sesión)")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BlockedError(
                        f"lock \"{name}\" ocupado por \"{holder.owner}\" "
                        f"(timeout {timeout_s}s)",
                        details={"lock": name, "holder": holder.owner})
                cond.wait(timeout=remaining)

    # ── liberación ───────────────────────────────────────────────────────
    def release(self, handle: LockHandle) -> None:
        cond = self._conditions[handle.name]
        with cond:
            holder = self._holders.get(handle.name)
            if holder is None or holder.owner != handle.owner:
                return        # release idempotente / de otro dueño: no-op honesto
            del self._holders[handle.name]
            cond.notify_all()

    def release_all(self, owner: str) -> list[str]:
        """Libera todos los locks de un dueño (kill switch / cierre de sesión)."""
        released: list[str] = []
        with self._mutex:
            for name, handle in list(self._holders.items()):
                if handle.owner == owner:
                    del self._holders[name]
                    released.append(name)
            for cond in self._conditions.values():
                cond.notify_all()
        return released

    # ── inspección ───────────────────────────────────────────────────────
    def held(self) -> dict[str, str]:
        with self._mutex:
            return {name: h.owner for name, h in self._holders.items()}

    def is_held(self, name: str) -> bool:
        with self._mutex:
            return name in self._holders


# ════════════════════════════════════════════════════════════════════════
# File lock cross-process (O_EXCL + staleness)
# ════════════════════════════════════════════════════════════════════════
@dataclass
class FileLockHandle:
    path: Path
    owner: str
    acquired_at: float

    def release(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("owner") == self.owner:
                    self.path.unlink()
        except (OSError, json.JSONDecodeError):
            pass          # release best-effort: nunca tumba al llamador


class FileLock:
    """Lock de fichero atómico entre procesos con caducidad (stale_s)."""

    def __init__(self, path: str | Path, *, stale_s: float = 300.0):
        self.path = Path(path)
        self.stale_s = stale_s

    def acquire(self, owner: str, *, timeout_s: float = 10.0,
                poll_s: float = 0.05) -> FileLockHandle:
        if timeout_s <= 0:
            raise ValidationError("file lock timeout_s debe ser > 0")
        deadline = time.monotonic() + timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            self._reap_if_stale()
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pass
            except OSError as exc:
                raise BlockedError(f"file lock no adquirible: {exc}",
                                   details={"path": str(self.path)})
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"owner": owner, "acquired_at": now_iso()}, fh)
                return FileLockHandle(path=self.path, owner=owner,
                                      acquired_at=time.monotonic())
            if time.monotonic() >= deadline:
                raise BlockedError(
                    f"file lock ocupado (timeout {timeout_s}s)",
                    details={"path": str(self.path),
                             "holder": self._holder_name()})
            time.sleep(poll_s)

    # ── internals ────────────────────────────────────────────────────────
    def _holder_name(self) -> str | None:
        try:
            return str(json.loads(self.path.read_text(encoding="utf-8")).get("owner"))
        except (OSError, json.JSONDecodeError):
            return None

    def _reap_if_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return
        if age > self.stale_s:
            try:
                self.path.unlink()
            except OSError:
                pass

    def is_locked(self) -> bool:
        return self.path.exists()


def new_owner_token(prefix: str = "owner") -> str:
    """Token de dueño único para locks/sesiones."""
    return new_id(prefix)
