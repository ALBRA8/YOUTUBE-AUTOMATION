# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS CONTRACT V1 — contracts.py
# ─────────────────────────────────────────────────────────────────────
# Contrato externo versionado del arnés de automatización audiovisual.
#
# Principio rector (mandato TRANSFORMACIÓN FINAL §1):
#   "El conocimiento operativo pertenece al puesto/empresa/arnés, no al
#    trabajador que actualmente ocupa el puesto."
#
# Este módulo define el idioma NEUTRO entre el host (AGENTE-GENERAL u
# otro) y la fábrica. NUNCA expone la estructura interna de SQLite ni
# los literales internos del pipeline como contrato: los estados
# internos se NORMALIZAN aquí (§9 del mandato).
#
# Agnosticidad (§15): este paquete NO importa agente-general, albra_seed
# ni ningún nombre del host. Solo conoce la fábrica existente.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# ── identidad del contrato ──────────────────────────────────────────
CONTRACT_VERSION = "1.0"
HARNESS_NAME = "youtube-harness"
CAPABILITY_ID = "youtube_automation"

# ── estados externos canónicos (mandato §9) ─────────────────────────
ACCEPTED = "ACCEPTED"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
WAITING = "WAITING"
VERIFYING = "VERIFYING"
READY = "READY"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
RECOVERABLE = "RECOVERABLE"
BLOCKED = "BLOCKED"
CANCELLED = "CANCELLED"

EXTERNAL_STATES: tuple[str, ...] = (
    ACCEPTED, QUEUED, RUNNING, WAITING, VERIFYING, READY,
    PUBLISHED, FAILED, RECOVERABLE, BLOCKED, CANCELLED,
)

# Mapeo mínimo obligatorio del mandato §9 + estados vecinos reales del
# pipeline (importing/processing/publishing existen en orchestrator;
# NO se inventan estados internos nuevos: solo se normalizan).
_PROJECT_STATE_MAP: dict[str, str] = {
    "draft": ACCEPTED,
    "queued": QUEUED,
    "scripting": RUNNING,
    "images": RUNNING,
    "tts": RUNNING,
    "align": RUNNING,
    "render": RUNNING,
    "importing": RUNNING,
    "processing": RUNNING,
    "subtitles": VERIFYING,
    "publishing": VERIFYING,
    "ready": READY,
    "published": PUBLISHED,
    "failed": FAILED,
    "cancelled": CANCELLED,
}

# Estados internos de la cola Flow (flow_jobs) — existentes, intactos.
_FLOW_STATE_MAP: dict[str, str] = {
    "queued": QUEUED,
    "claimed": RUNNING,
    "done": READY,
    "dead": FAILED,
}

# Estados internos de la tabla jobs (pipeline/publish) — existentes.
_JOB_STATE_MAP: dict[str, str] = {
    "running": RUNNING,
    "pending": QUEUED,
    "done": READY,
    "failed": FAILED,
    "cancelled": CANCELLED,
}

_UNKNOWN_STATE = WAITING  # estado interno no reconocido → WAITING (honesto)


def normalize_status(internal: str | None, *, kind: str = "project",
                     recoverable: bool = False) -> str:
    """Normaliza un estado interno → estado externo del contrato.

    kind: "project" | "flow" | "job"
    recoverable: hay evidencia de recuperación posible → FAILED→RECOVERABLE
      (mandato §9: "FAILED + recoverable = RECOVERABLE"). Nunca al revés.
    """
    raw = (internal or "").strip().lower()
    table = {"project": _PROJECT_STATE_MAP,
             "flow": _FLOW_STATE_MAP,
             "job": _JOB_STATE_MAP}.get(kind, _PROJECT_STATE_MAP)
    out = table.get(raw, _UNKNOWN_STATE)
    if out == FAILED and recoverable:
        return RECOVERABLE
    return out


# ── validación ──────────────────────────────────────────────────────
_EXEC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{3,127}$")
_PERM_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_*]+){0,3}$")
_SENSITIVE_KEY_RE = re.compile(
    r"pass|secret|token|api[_\-]?key|credential|cookie|authorization",
    re.IGNORECASE)


class HarnessValidationError(ValueError):
    """Solicitud inválida según el contrato. Nunca un fallo silencioso."""

    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass
class HarnessRequest:
    """Solicitud de ejecución del host hacia el arnés (mandato §7).

    Ningún campo es obligatorio si la operación no lo necesita; los
    obligatorios transversales son: execution_id, requester, capability,
    operation. La validación es ESTRICTA: una operación desconocida
    jamás se acepta silenciosamente (la existencia se comprueba contra
    el registro de capabilities en harness.execute).
    """
    contract_version: str
    execution_id: str
    requester: str
    capability: str
    operation: str
    objective: str = ""
    input: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    resources: dict = field(default_factory=dict)
    deadline: str | None = None
    correlation_id: str | None = None
    parent_execution_id: str | None = None
    metadata: dict = field(default_factory=dict)

    # ── construcción estricta desde dict (payload HTTP) ─────────────
    @classmethod
    def from_dict(cls, data: dict) -> "HarnessRequest":
        if not isinstance(data, dict):
            raise HarnessValidationError(
                "INVALID_REQUEST", "el cuerpo debe ser un objeto JSON")
        req = cls(
            contract_version=str(data.get("contract_version") or ""),
            execution_id=str(data.get("execution_id") or "").strip(),
            requester=str(data.get("requester") or "").strip(),
            capability=str(data.get("capability") or "").strip(),
            operation=str(data.get("operation") or "").strip(),
            objective=str(data.get("objective") or "").strip()[:500],
            input=data.get("input") if isinstance(data.get("input"), dict) else {},
            constraints=(data.get("constraints")
                         if isinstance(data.get("constraints"), dict) else {}),
            permissions=data.get("permissions")
            if isinstance(data.get("permissions"), list) else [],
            resources=(data.get("resources")
                       if isinstance(data.get("resources"), dict) else {}),
            deadline=data.get("deadline"),
            correlation_id=data.get("correlation_id"),
            parent_execution_id=data.get("parent_execution_id"),
            metadata=(data.get("metadata")
                      if isinstance(data.get("metadata"), dict) else {}),
        )
        req.validate()
        return req

    # ── validación estricta (mandato §7) ────────────────────────────
    def validate(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise HarnessValidationError(
                "CONTRACT_VERSION",
                f"contrato soportado: {CONTRACT_VERSION!r}; "
                f"recibido: {self.contract_version!r}")
        if not _EXEC_ID_RE.match(self.execution_id):
            raise HarnessValidationError(
                "EXECUTION_ID",
                "execution_id requerido: 4-128 chars, "
                "[A-Za-z0-9._:-] (lo genera el host)")
        if not self.requester or len(self.requester) > 80:
            raise HarnessValidationError(
                "REQUESTER", "requester requerido (identidad del host, ≤80)")
        if self.capability != CAPABILITY_ID:
            raise HarnessValidationError(
                "CAPABILITY",
                f"capability soportada: {CAPABILITY_ID!r}; "
                f"recibida: {self.capability!r}")
        if not self.operation or len(self.operation) > 80:
            raise HarnessValidationError(
                "OPERATION", "operation requerida (≤80 chars)")
        if not isinstance(self.input, dict):  # defensa en profundidad
            raise HarnessValidationError("INPUT", "input debe ser un objeto")
        perms: list[str] = []
        for p in self.permissions:
            ps = str(p).strip()
            if not _PERM_RE.match(ps) or len(ps) > 80:
                raise HarnessValidationError(
                    "PERMISSIONS", f"permiso con formato inválido: {ps!r}")
            perms.append(ps)
        self.permissions = perms
        if len(self.permissions) > 32:
            raise HarnessValidationError(
                "PERMISSIONS", "máximo 32 permisos por solicitud")
        if self.deadline is not None:
            if not isinstance(self.deadline, str):
                raise HarnessValidationError(
                    "DEADLINE", "deadline debe ser ISO-8601 string")
            try:
                datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HarnessValidationError(
                    "DEADLINE", f"deadline no parseable: {exc}") from None
        for sid, sval in (("correlation_id", self.correlation_id),
                          ("parent_execution_id", self.parent_execution_id)):
            if sval is not None and (not str(sval).strip()
                                     or len(str(sval)) > 128):
                raise HarnessValidationError(
                    sid.upper(), f"{sid} inválido (1-128 chars)")
        self._validate_metadata()

    def _validate_metadata(self) -> None:
        for key in self.metadata:
            if _SENSITIVE_KEY_RE.search(str(key)):
                raise HarnessValidationError(
                    "METADATA_SENSIBLE",
                    f"metadata no puede contener claves sensibles: {key!r} "
                    "(usa el mecanismo de credenciales del transporte)")
        if len(str(self.metadata)) > 8000:
            raise HarnessValidationError(
                "METADATA", "metadata demasiado grande (≤8KB serializado)")


@dataclass
class HarnessResult:
    """Respuesta abstracta del arnés hacia el host (mandato §8).

    Nunca expone filas SQLite crudas: outputs/artifacts son diccionarios
    abstractos ya normalizados por el adaptador.
    """
    contract_version: str = CONTRACT_VERSION
    execution_id: str = ""
    status: str = ACCEPTED
    operation: str = ""
    project_id: str | None = None
    job_id: str | None = None
    outputs: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    recovery: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self, *, exclude_none: bool = True) -> dict:
        out: dict = {}
        for k, v in self.__dict__.items():
            if exclude_none and v is None:
                continue
            out[k] = v
        return out

    # ── fábricas semánticas ─────────────────────────────────────────
    @classmethod
    def for_request(cls, req: HarnessRequest) -> "HarnessResult":
        return cls(contract_version=req.contract_version,
                   execution_id=req.execution_id, operation=req.operation)

    def with_error(self, code: str, message: str, *,
                   status: str = FAILED) -> "HarnessResult":
        self.status = status
        self.errors.append({"code": code, "message": str(message)[:800]})
        return self
