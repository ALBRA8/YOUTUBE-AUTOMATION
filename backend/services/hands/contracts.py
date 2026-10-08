"""
HANDS · Contratos — estados, errores, operaciones, acciones, targets y observación.

HANDS es la capa de EJECUCIÓN FÍSICA de YOUTUBE-AUTOMATION (§1-§5 del brief):
no decide QUÉ producir (eso es el orquestador/cerebro creativo), solo CÓMO
ejecutar operaciones controladas sobre Desktop y Google Flow.

Este módulo define los contratos estables e independientes del orquestador:

  · State        — los 9 estados inequívocos (§11). Regla dura: UNKNOWN nunca
                   transiciona a COMPLETED (primero re-observación → RUNNING).
  · ErrorCode    — taxonomía de 10 errores diferenciados (§29).
  · Op / FlowOp  — abstracción de operaciones (§6): OBSERVE…RECOVER y
                   OPEN_FLOW…REPORT_RESULT.
  · OperationRequest / OperationResult — resultado estructurado (§30).
  · ActionSpec   — modelo de acción OBSERVE→IDENTIFY→ACTION→OBSERVE→VERIFY (§7).
  · TargetSpec   — jerarquía de identificación semántico→a11y→texto→DOM→
                   visual→coordenadas (§8); coordenadas solo como último
                   recurso y bajo política explícita.
  · Observation  — modelo estructurado de observación (§9).

Todos los objetos son serializables a JSON (to_dict) para evidencia/auditoría.
Etiquetas de estado en inglés (convención del repo); documentación en español.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ── helpers de ids/tiempo compartidos por los contratos ──────────────────
def new_id(prefix: str) -> str:
    """Id corto determinista-único (uuid4 hex[:12], convención del repo)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    """Timestamp ISO-8601 UTC en segundos (misma convención que database.now)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ════════════════════════════════════════════════════════════════════════
# §11 · ESTADOS — inequívocos, con transiciones explícitas
# ════════════════════════════════════════════════════════════════════════
class State(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    STOPPED = "STOPPED"


# UNKNOWN → {RUNNING, FAILED, STOPPED}: la única forma de llegar a COMPLETED
# es re-observar (RUNNING) y verificar. NUNCA UNKNOWN→COMPLETED (§11).
_TRANSITIONS: dict[State, frozenset[State]] = {
    State.IDLE: frozenset({State.RUNNING, State.BLOCKED, State.STOPPED}),
    State.RUNNING: frozenset({
        State.RUNNING, State.WAITING, State.COMPLETED, State.FAILED,
        State.TIMEOUT, State.BLOCKED, State.UNKNOWN, State.STOPPED,
    }),
    State.WAITING: frozenset({
        State.RUNNING, State.COMPLETED, State.FAILED, State.TIMEOUT,
        State.BLOCKED, State.UNKNOWN, State.STOPPED,
    }),
    State.COMPLETED: frozenset(),  # terminal
    State.FAILED: frozenset({State.RUNNING, State.STOPPED}),      # reentrada por recovery
    State.TIMEOUT: frozenset({State.RUNNING, State.STOPPED}),     # ídem
    State.BLOCKED: frozenset({State.RUNNING, State.STOPPED}),     # ídem
    State.UNKNOWN: frozenset({State.RUNNING, State.FAILED, State.STOPPED}),
    State.STOPPED: frozenset(),  # terminal
}

TERMINAL_STATES: frozenset[State] = frozenset({
    State.COMPLETED, State.STOPPED,
})


def can_transition(current: State, target: State) -> bool:
    """True si current→target es una transición válida."""
    return target in _TRANSITIONS.get(current, frozenset())


def check_transition(current: State, target: State) -> State:
    """Valida la transición y devuelve el target; InvalidTransitionError si no."""
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"transición de estado prohibida: {current.value} → {target.value}",
            details={"from": current.value, "to": target.value},
        )
    return target


# ════════════════════════════════════════════════════════════════════════
# §29 · TAXONOMÍA DE ERRORES — 10 códigos, nunca un genérico
# ════════════════════════════════════════════════════════════════════════
class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    STOPPED = "STOPPED"


class HandsError(Exception):
    """Base de todos los errores de HANDS (código + mensaje + detalles)."""

    code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:  # pragma: no cover — presentación
        return f"[{self.code.value}] {self.message}"


class ValidationError(HandsError):
    code = ErrorCode.VALIDATION_ERROR


class InvalidTransitionError(ValidationError):
    """Transición de estado prohibida (p.ej. UNKNOWN→COMPLETED)."""


class PermissionDeniedError(HandsError):
    code = ErrorCode.PERMISSION_DENIED


class TargetNotFoundError(HandsError):
    code = ErrorCode.TARGET_NOT_FOUND


class HandsTimeoutError(HandsError):
    code = ErrorCode.TIMEOUT


class ActionFailedError(HandsError):
    code = ErrorCode.ACTION_FAILED


class VerificationFailedError(HandsError):
    code = ErrorCode.VERIFICATION_FAILED


class RecoveryFailedError(HandsError):
    code = ErrorCode.RECOVERY_FAILED


class BlockedError(HandsError):
    code = ErrorCode.BLOCKED


class UnknownStateError(HandsError):
    code = ErrorCode.UNKNOWN


class StoppedError(HandsError):
    code = ErrorCode.STOPPED


def error_from_exception(exc: BaseException) -> HandsError:
    """Normaliza cualquier excepción a la taxonomía (UNKNOWN como último recurso)."""
    if isinstance(exc, HandsError):
        return exc
    return UnknownStateError(f"excepción no clasificada: {type(exc).__name__}: {exc}",
                             details={"exception_type": type(exc).__name__})


# ════════════════════════════════════════════════════════════════════════
# §6 · OPERACIONES — abstracción equivalente al brief (nombres canónicos)
# ════════════════════════════════════════════════════════════════════════
class Op(str, Enum):
    """Operaciones genéricas de ejecución (Desktop/observación)."""
    OBSERVE = "OBSERVE"
    FOCUS = "FOCUS"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    TYPE = "TYPE"
    PASTE = "PASTE"
    HOTKEY = "HOTKEY"
    SCROLL = "SCROLL"
    DRAG = "DRAG"
    WAIT = "WAIT"
    VERIFY = "VERIFY"
    CAPTURE = "CAPTURE"
    DOWNLOAD = "DOWNLOAD"
    COPY = "COPY"
    MOVE = "MOVE"
    RENAME = "RENAME"
    EXECUTE_ALLOWED = "EXECUTE_ALLOWED"
    STOP = "STOP"
    RECOVER = "RECOVER"


class FlowOp(str, Enum):
    """Operaciones del especialista Google Flow (§14): HOW within Flow."""
    OPEN_FLOW = "OPEN_FLOW"
    OPEN_PROJECT = "OPEN_PROJECT"
    SELECT_PROJECT = "SELECT_PROJECT"
    SET_PROMPT = "SET_PROMPT"
    SET_CONFIGURATION = "SET_CONFIGURATION"
    START_GENERATION = "START_GENERATION"
    WAIT_GENERATION = "WAIT_GENERATION"
    DETECT_RESULT = "DETECT_RESULT"
    DOWNLOAD_RESULT = "DOWNLOAD_RESULT"
    VERIFY_RESULT = "VERIFY_RESULT"
    REPORT_RESULT = "REPORT_RESULT"


# Categoría de permiso que consume cada operación (§16).
OP_PERMISSION_CATEGORY: dict[str, str] = {
    Op.OPEN.value: "application", Op.CLOSE.value: "application",
    Op.FOCUS.value: "application",
    Op.CLICK.value: "browser", Op.DOUBLE_CLICK.value: "browser",
    Op.TYPE.value: "browser", Op.PASTE.value: "browser",
    Op.HOTKEY.value: "browser", Op.SCROLL.value: "browser",
    Op.DRAG.value: "browser",
    Op.COPY.value: "filesystem", Op.MOVE.value: "filesystem",
    Op.RENAME.value: "filesystem", Op.DOWNLOAD.value: "filesystem",
    Op.EXECUTE_ALLOWED.value: "command",
    Op.OBSERVE.value: "browser", Op.WAIT.value: "browser",
    Op.VERIFY.value: "filesystem", Op.CAPTURE.value: "browser",
    Op.STOP.value: "application", Op.RECOVER.value: "browser",
    FlowOp.OPEN_FLOW.value: "domain", FlowOp.OPEN_PROJECT.value: "domain",
    FlowOp.SELECT_PROJECT.value: "domain", FlowOp.SET_PROMPT.value: "domain",
    FlowOp.SET_CONFIGURATION.value: "domain",
    FlowOp.START_GENERATION.value: "domain",
    FlowOp.WAIT_GENERATION.value: "domain",
    FlowOp.DETECT_RESULT.value: "domain",
    FlowOp.DOWNLOAD_RESULT.value: "filesystem",
    FlowOp.VERIFY_RESULT.value: "filesystem",
    FlowOp.REPORT_RESULT.value: "domain",
}


# ════════════════════════════════════════════════════════════════════════
# §30 · RESULTADO DE OPERACIÓN — estructurado, serializable
# ════════════════════════════════════════════════════════════════════════
@dataclass
class OperationRequest:
    """Petición de una operación (lo que un plan externo pide ejecutar)."""
    operation_id: str
    name: str                       # Op.* / FlowOp.*
    operator: str                   # "desktop" | "flow"
    params: dict[str, Any] = field(default_factory=dict)
    target: "TargetSpec | None" = None
    timeout_s: float | None = None  # None → default de HandsConfig por op
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "name": self.name,
            "operator": self.operator,
            "params": self.params,
            "target": self.target.to_dict() if self.target else None,
            "timeout_s": self.timeout_s,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class OperationResult:
    """Resultado estructurado de toda operación (§30)."""
    operation_id: str
    name: str
    operator: str
    status: State
    result: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)   # {expected, observed, verdict}
    evidence_ids: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    started_at: str = ""
    finished_at: str = ""

    @property
    def ok(self) -> bool:
        return self.status is State.COMPLETED

    def add_error(self, err: HandsError | dict[str, Any]) -> None:
        self.errors.append(err.to_dict() if isinstance(err, HandsError) else dict(err))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "name": self.name,
            "operator": self.operator,
            "status": self.status.value,
            "result": self.result,
            "verification": self.verification,
            "evidence_ids": list(self.evidence_ids),
            "errors": list(self.errors),
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ════════════════════════════════════════════════════════════════════════
# §7/§8 · MODELO DE ACCIÓN Y TARGETS
# ════════════════════════════════════════════════════════════════════════
@dataclass
class TargetSpec:
    """Target de una acción: se rellenan SOLO los campos conocidos; el
    resolver aplica la jerarquía semántico→a11y→texto→DOM→visual→coords (§8).
    coords es (x, y) y SOLO se usa si la política global lo permite."""
    semantic: str | None = None
    accessibility: str | None = None
    text: str | None = None
    dom: str | None = None
    visual: dict[str, Any] | None = None      # p.ej. {"region": [...]} referencial
    coords: tuple[float, float] | None = None

    def strategies_available(self) -> list["TargetStrategy"]:
        """Estrategias aplicables en orden de jerarquía (sin contar coords)."""
        out: list[TargetStrategy] = []
        if self.semantic:
            out.append(TargetStrategy.SEMANTIC)
        if self.accessibility:
            out.append(TargetStrategy.ACCESSIBILITY)
        if self.text:
            out.append(TargetStrategy.TEXT)
        if self.dom:
            out.append(TargetStrategy.DOM)
        if self.visual:
            out.append(TargetStrategy.VISUAL)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic": self.semantic, "accessibility": self.accessibility,
            "text": self.text, "dom": self.dom, "visual": self.visual,
            "coords": list(self.coords) if self.coords else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TargetSpec | None":
        if not data:
            return None
        coords = data.get("coords")
        return cls(
            semantic=data.get("semantic"), accessibility=data.get("accessibility"),
            text=data.get("text"), dom=data.get("dom"), visual=data.get("visual"),
            coords=tuple(coords) if coords else None,   # type: ignore[arg-type]
        )


class TargetStrategy(str, Enum):
    SEMANTIC = "semantic"
    ACCESSIBILITY = "accessibility"
    TEXT = "text"
    DOM = "dom"
    VISUAL = "visual"
    COORDINATES = "coordinates"


TARGET_STRATEGY_ORDER: tuple[TargetStrategy, ...] = (
    TargetStrategy.SEMANTIC, TargetStrategy.ACCESSIBILITY, TargetStrategy.TEXT,
    TargetStrategy.DOM, TargetStrategy.VISUAL, TargetStrategy.COORDINATES,
)


@dataclass
class TargetMatch:
    """Resultado de identificar un target sobre una observación."""
    strategy: TargetStrategy
    value: str | tuple[float, float]
    element_ref: str | None = None     # ref_id del elemento, si aplica
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "value": list(self.value) if isinstance(self.value, tuple) else self.value,
            "element_ref": self.element_ref,
            "detail": self.detail,
        }


@dataclass
class ActionSpec:
    """Acción completa bajo el modelo §7: OBSERVE→IDENTIFY→ACTION→OBSERVE→VERIFY.

    verify    — spec de verificación para VerificationEngine (dict o callable).
    recovery  — RecoveryPolicy (dict) para el RecoveryEngine (§24).
    idempotency_check — callable(observation) -> bool: si True, la acción ya
                está satisfecha y NO se repite (§26: verificar estado existente
                antes de repetir).
    """
    name: str                                   # Op.* / FlowOp.*
    operator: str = "desktop"                   # "desktop" | "flow"
    params: dict[str, Any] = field(default_factory=dict)
    target: TargetSpec | None = None
    verify: Any = None
    recovery: dict[str, Any] | None = None
    timeout_s: float | None = None
    idempotency_check: Callable[[Any], bool] | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "operator": self.operator, "params": self.params,
            "target": self.target.to_dict() if self.target else None,
            "verify": _verify_to_dict(self.verify),
            "recovery": self.recovery, "timeout_s": self.timeout_s,
            "description": self.description,
        }


def _verify_to_dict(verify: Any) -> Any:
    if verify is None:
        return None
    if isinstance(verify, dict):
        return dict(verify)
    return {"kind": "callable", "name": getattr(verify, "__name__", "predicate")}


# ════════════════════════════════════════════════════════════════════════
# §9 · OBSERVACIÓN — modelo estructurado
# ════════════════════════════════════════════════════════════════════════
@dataclass
class ElementRef:
    """Elemento visible observado (con todos los identificadores conocidos)."""
    ref_id: str
    semantic: str | None = None          # identificador semántico estable
    accessibility: str | None = None     # a11y/UI identifier
    text: str | None = None              # texto visible
    dom: str | None = None               # selector DOM cuando aplique
    visual: dict[str, Any] | None = None # región/referencia visual
    clickable: bool = False
    editable: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id, "semantic": self.semantic,
            "accessibility": self.accessibility, "text": self.text,
            "dom": self.dom, "visual": self.visual,
            "clickable": self.clickable, "editable": self.editable,
            "extra": self.extra,
        }


@dataclass
class FileRef:
    path: str
    size: int | None = None
    modified_at: str | None = None
    exists: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size,
                "modified_at": self.modified_at, "exists": self.exists}


@dataclass
class ProcessRef:
    pid: int | None
    name: str
    state: str = "running"           # running | frozen | finished | unknown
    command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "name": self.name, "state": self.state,
                "command": self.command}


@dataclass
class DownloadRef:
    path: str
    status: str = "in_progress"      # in_progress | done | failed
    size: int | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "status": self.status,
                "size": self.size, "source": self.source}


@dataclass
class Observation:
    """Modelo estructurado de observación del entorno (§9)."""
    timestamp: str
    application: str | None = None
    window: str | None = None
    url: str | None = None
    tab: str | None = None
    state: str = "unknown"           # estado del entorno observado
    elements: list[ElementRef] = field(default_factory=list)
    downloads: list[DownloadRef] = field(default_factory=list)
    files: list[FileRef] = field(default_factory=list)
    processes: list[ProcessRef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    visual_digest: str | None = None  # huella del estado visual (cambio visual)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "application": self.application, "window": self.window,
            "url": self.url, "tab": self.tab, "state": self.state,
            "elements": [e.to_dict() for e in self.elements],
            "downloads": [d.to_dict() for d in self.downloads],
            "files": [f.to_dict() for f in self.files],
            "processes": [p.to_dict() for p in self.processes],
            "errors": list(self.errors),
            "visual_digest": self.visual_digest,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Observation":
        return cls(
            timestamp=data.get("timestamp", now_iso()),
            application=data.get("application"), window=data.get("window"),
            url=data.get("url"), tab=data.get("tab"),
            state=data.get("state", "unknown"),
            elements=[ElementRef(**e) for e in data.get("elements", [])],
            downloads=[DownloadRef(**d) for d in data.get("downloads", [])],
            files=[FileRef(**f) for f in data.get("files", [])],
            processes=[ProcessRef(**p) for p in data.get("processes", [])],
            errors=list(data.get("errors", [])),
            visual_digest=data.get("visual_digest"),
            extra=dict(data.get("extra", {})),
        )

    def find_element(self, predicate: Callable[[ElementRef], bool]) -> ElementRef | None:
        """Primer elemento que cumple el predicado (o None)."""
        for el in self.elements:
            try:
                if predicate(el):
                    return el
            except Exception:        # noqa: BLE001 — predicado roto no tumba la obs.
                continue
        return None
