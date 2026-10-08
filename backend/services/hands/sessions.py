"""
HANDS · Sesiones (§19).

Cada ejecución de HANDS vive en una sesión auditable con:

  session_id · operator · start_time · end_time · permissions (snapshot
  redactado) · current_state · actions (refs a OperationResult) · evidence
  (capa ligada) · errors · final_status.

La sesión se persiste en disco (JSON) al arrancar, en cada cambio de estado
y al cerrar — puede auditarse después aunque el proceso haya muerto
(§19: "una sesión debe poder auditarse posteriormente").

La máquina de estados usa contracts.check_transition: UNKNOWN nunca deviene
COMPLETED por arte de magia (§11).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import (OperationResult, State, ValidationError,
                        check_transition, new_id, now_iso)
from .evidence import EvidenceLayer


@dataclass
class Session:
    """Sesión auditable de ejecución de HANDS."""

    session_id: str
    operator: str
    start_time: str
    permissions_snapshot: dict[str, Any]
    current_state: State = State.IDLE
    end_time: str | None = None
    final_status: str | None = None          # COMPLETED | FAILED | STOPPED | ...
    actions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    evidence_dir: str = ""
    session_dir: str = ""
    lock_names: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    _closed: bool = field(default=False, repr=False)

    # ── ciclo de vida ────────────────────────────────────────────────────
    def set_state(self, target: State) -> State:
        """Transición validada + persistencia delegada en el manager."""
        self.current_state = check_transition(self.current_state, target)
        return self.current_state

    def add_action(self, result: OperationResult | dict[str, Any]) -> None:
        self.actions.append(result.to_dict() if isinstance(result, OperationResult)
                            else dict(result))

    def add_error(self, err: Any) -> None:
        self.errors.append(err.to_dict() if hasattr(err, "to_dict") else dict(err))

    def close(self, final_status: str = "COMPLETED") -> None:
        """Cierra la sesión (end_time + final_status + persist)."""
        if self._closed:
            return
        self._closed = True
        self.end_time = now_iso()
        if self.current_state not in (State.COMPLETED, State.STOPPED,
                                      State.FAILED, State.TIMEOUT, State.BLOCKED):
            try:
                target = {"STOPPED": State.STOPPED, "COMPLETED": State.COMPLETED,
                          "FAILED": State.FAILED}.get(final_status, State.COMPLETED)
                if self.current_state is State.UNKNOWN and target is State.COMPLETED:
                    # §11: UNKNOWN nunca deriva en COMPLETED — se registra
                    # FAILED honesto + conflicto en meta (auditable)
                    target = State.FAILED
                    final_status = "FAILED"
                    self.meta["close_state_conflict"] = {
                        "from": self.current_state.value,
                        "requested": "COMPLETED",
                        "resolved": "FAILED (UNKNOWN nunca → COMPLETED §11)"}
                self.set_state(target)
            except ValidationError:
                # estados imposibles desde el actual: registro honesto, sin drama
                self.meta["close_state_conflict"] = {
                    "from": self.current_state.value, "final_status": final_status}
        self.final_status = final_status

    @property
    def closed(self) -> bool:
        return self._closed

    # ── persistencia ─────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operator": self.operator,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "permissions": self.permissions_snapshot,
            "current_state": self.current_state.value,
            "actions": list(self.actions),
            "evidence": {"dir": self.evidence_dir, "count": len(self.actions)},
            "errors": list(self.errors),
            "final_status": self.final_status,
            "locks": list(self.lock_names),
            "meta": self.meta,
        }

    def save(self) -> Path:
        if not self.session_dir:
            raise ValidationError("sesión sin session_dir (no gestionada)")
        path = Path(self.session_dir) / f"{self.session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path


class SessionManager:
    """Carga/persistencia de sesiones bajo <workspace>/sessions/."""

    def __init__(self, sessions_dir: str | Path, evidence_root: str | Path):
        self.sessions_dir = Path(sessions_dir)
        self.evidence_root = Path(evidence_root)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def start(self, operator: str, permissions_snapshot: dict[str, Any],
              *, locks: list[str] | None = None, meta: dict[str, Any] | None = None
              ) -> tuple[Session, EvidenceLayer]:
        """Crea sesión + capa de evidencia ligada y persiste el arranque."""
        session_id = new_id("hands")
        session = Session(
            session_id=session_id,
            operator=operator,
            start_time=now_iso(),
            permissions_snapshot=permissions_snapshot,
            evidence_dir=str(self.evidence_root),
            session_dir=str(self.sessions_dir),
            lock_names=list(locks or []),
            meta=dict(meta or {}),
        )
        session.set_state(State.RUNNING)   # IDLE→RUNNING al arrancar la sesión
        session.save()
        evidence = EvidenceLayer(self.evidence_root, session_id, operator=operator)
        evidence.record("session_start", operator=operator,
                        result="UNKNOWN",
                        observed_state={"operator": operator,
                                        "locks": list(locks or [])})
        return session, evidence

    def get(self, session_id: str) -> Session | None:
        """Recarga una sesión desde disco (auditabilidad posterior, §19)."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        session = Session(
            session_id=data["session_id"],
            operator=data["operator"],
            start_time=data["start_time"],
            permissions_snapshot=data.get("permissions", {}),
            current_state=State(data.get("current_state", "UNKNOWN")),
            end_time=data.get("end_time"),
            final_status=data.get("final_status"),
            actions=list(data.get("actions", [])),
            errors=list(data.get("errors", [])),
            evidence_dir=data.get("evidence", {}).get("dir", ""),
            session_dir=str(self.sessions_dir),
            lock_names=list(data.get("locks", [])),
            meta=dict(data.get("meta", {})),
        )
        session._closed = session.end_time is not None
        return session

    def list_sessions(self) -> list[str]:
        return sorted(p.stem for p in self.sessions_dir.glob("hands_*.json"))

    def save_session(self, session: Session) -> Path:
        return session.save()
