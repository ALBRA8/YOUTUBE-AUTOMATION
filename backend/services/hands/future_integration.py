"""
HANDS · Contrato de integración FUTURA con YOUTUBE-AUTOMATION (§37).

ESTADO OFICIAL:  YOUTUBE-AUTOMATION INTEGRATION: NOT CONNECTED

Este módulo deja PREPARADA —y solo preparada— la interfaz por la que el
orquestador hablará con HANDS en el futuro:

    YOUTUBE-AUTOMATION → HAND_REQUEST → [HandAdapter] → HANDS → HAND_RESULT

Se crean SOLO: schemas (validación de DTOs), protocolo (HandAdapter) y un
adaptador explícitamente NO CONECTADO (NotConnectedAdapter). Prohibido en
V1.0 (§36): importar internals del orquestador, engancharse a scheduler/
publishing/factory/pipeline, o activar ejecución física sobre producción.

Lista de pasos pendientes para la futura integración (§48.K): ver
integration_checklist() — documentación como código, nada ejecutable hoy.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .contracts import BlockedError, now_iso

# ── estado oficial (§48.J) — constante única, citada por tests y docs ────
INTEGRATION_STATUS = "NOT CONNECTED"

HAND_REQUEST_FIELDS = {
    "request_id": str, "requested_by": str, "operations": list,
    "created_at": str,
}
HAND_REQUEST_OPTIONAL = {"constraints": dict, "context": dict}
HAND_RESULT_FIELDS = {
    "request_id": str, "status": str, "results": list, "started_at": str,
    "finished_at": str,
}
HAND_RESULT_OPTIONAL = {"evidence_manifest": dict, "errors": list,
                        "session_id": str}

VALID_REQUEST_OPERATORS = {"desktop", "flow"}


def validate_hand_request(obj: Any) -> tuple[bool, list[str]]:
    """Valida un HAND_REQUEST (schema §37). Devuelve (ok, errores)."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["HAND_REQUEST debe ser un objeto JSON"]
    for name, kind in HAND_REQUEST_FIELDS.items():
        if name not in obj:
            errors.append(f"campo obligatorio ausente: {name}")
        elif not isinstance(obj[name], kind):
            errors.append(f"campo {name} debe ser {kind.__name__}")
    for name in HAND_REQUEST_OPTIONAL:
        if name in obj and not isinstance(obj[name], dict):
            errors.append(f"campo opcional {name} debe ser dict")
    for i, op in enumerate(obj.get("operations", []) if isinstance(obj, dict) else []):
        if not isinstance(op, dict):
            errors.append(f"operations[{i}] debe ser un objeto")
            continue
        if not op.get("op"):
            errors.append(f"operations[{i}].op ausente")
        if op.get("operator") not in VALID_REQUEST_OPERATORS:
            errors.append(f"operations[{i}].operator debe ser "
                          f"{sorted(VALID_REQUEST_OPERATORS)}")
    return (not errors), errors


def make_hand_result(request_id: str, status: str, results: list[dict[str, Any]],
                     *, session_id: str | None = None,
                     evidence_manifest: dict[str, Any] | None = None,
                     errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Construye un HAND_RESULT bien formado (schema §37)."""
    out: dict[str, Any] = {
        "request_id": request_id,
        "status": status,
        "results": list(results),
        "started_at": now_iso(),
        "finished_at": now_iso(),
    }
    if session_id:
        out["session_id"] = session_id
    if evidence_manifest:
        out["evidence_manifest"] = evidence_manifest
    if errors:
        out["errors"] = errors
    return out


@runtime_checkable
class HandAdapter(Protocol):
    """Protocolo de la futura puerta YOUTUBE-AUTOMATION → HANDS."""

    def submit(self, request: dict[str, Any]) -> dict[str, Any]: ...


class NotConnectedAdapter:
    """Adaptador EXPLÍCITAMENTE no conectado (§36/§37).

    Toda llamada es BLOCKED con el estado oficial. Existe para que el
    contrato tenga implementación referenciable sin abrir la puerta.
    """

    name = "not_connected"

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        ok, errors = validate_hand_request(request)
        raise BlockedError(
            "HANDS integration NOT CONNECTED (V1.0 §37): ningún HAND_REQUEST "
            "puede ejecutarse todavía",
            details={"integration_status": INTEGRATION_STATUS,
                     "request_valid": ok,
                     "validation_errors": errors})

    def status(self) -> dict[str, Any]:
        return {"integration_status": INTEGRATION_STATUS, "adapter": self.name}


def integration_checklist() -> list[dict[str, str]]:
    """Pasos pendientes para la FUTURA integración (§48.K) — NO ejecutarlos."""
    return [
        {"step": "1", "task": "Decidir política de autonomía física (niveles L0-L5 "
                              "del repo) aplicada a HANDS y documentarla"},
        {"step": "2", "task": "Activar ExtensionBridgeDriver (enabled=true) contra "
                              "el backend real y validar el contrato HTTP en vivo"},
        {"step": "3", "task": "Implementar/consentir un executor físico para "
                              "PhysicalDesktopBackend y validar en el PC real"},
        {"step": "4", "task": "Wiring del orquestador: HAND_REQUEST → HandAdapter "
                              "(scheduler/publishing/factory siguen intactos)"},
        {"step": "5", "task": "Elevar madurez de capacidades a INTEGRATION_READY / "
                              "REAL_WORLD_VERIFIED SOLO con evidencia real"},
        {"step": "6", "task": "Prueba de producción real end-to-end con HANDS "
                              "(fase posterior, autorización explícita)"},
    ]
