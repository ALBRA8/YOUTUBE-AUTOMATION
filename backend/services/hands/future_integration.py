"""
HANDS · Contrato de integración FUTURA con YOUTUBE-AUTOMATION (§37).

ESTADO OFICIAL (FASE 7):  PARTIAL CONNECTED — capa Execution Contract V1.0

Este módulo deja PREPARADA —y desde FASE 7 PARCIALMENTE CONECTADA en su
CAPA DE CONTRATO— la interfaz por la que el orquestador hablará con HANDS:

    YOUTUBE-AUTOMATION → HAND_REQUEST → [HandAdapter] → HANDS → HAND_RESULT

Dos adaptadores:
  * NotConnectedAdapter        — puerta cerrada por defecto (§36/§37): toda
                                 llamada es BLOCKED. SIGUE SIENDO EL DEFAULT.
  * ExecutionContractHandAdapter — adaptador REAL de la capa contrato V1.0:
                                 ejecuta flow.discover_capabilities /
                                 flow.configure_from_spec / flow.start_generation
                                 contra un FlowOperator con controls_adapter
                                 (gate de configuración §6, evidencia job_id).
                                 Probado sobre mocks; E2E con Flow real: PENDIENTE.

Prohibido (§36): importar internals del orquestador, engancharse a scheduler/
publishing/factory/pipeline, o activar ejecución física sobre producción.
ExtensionBridgeDriver sigue enabled=False por defecto (§37).

Lista de pasos pendientes para la integración completa (§48.K): ver
integration_checklist() — el paso de la capa contrato está DONE; el resto,
documentación como código.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .contracts import BlockedError, ValidationError, now_iso

# ── estado oficial (§48.J) — constante única, citada por tests y docs ────
INTEGRATION_STATUS = ("PARTIAL CONNECTED: Execution Contract V1.0 contract "
                      "layer (FlowOperator+ConfigGate+MockFlowControlAdapter "
                      "TESTED; ExtensionBridgeDriver enabled=False por defecto; "
                      "E2E real pendiente)")

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
    SIGUE SIENDO EL DEFAULT: la capa Execution Contract V1.0 se usa vía
    ExecutionContractHandAdapter, no por aquí.
    """

    name = "not_connected"

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        ok, errors = validate_hand_request(request)
        raise BlockedError(
            "HANDS integration NOT CONNECTED (V1.0 §37): ningún HAND_REQUEST "
            "puede ejecutarse todavía",
            # Esta PUERTA concreta sigue cerrada: su estado propio no cambia
            # con el estado de la capa (comportamiento congelado del contrato).
            details={"integration_status": "NOT CONNECTED",
                     "request_valid": ok,
                     "validation_errors": errors})

    def status(self) -> dict[str, Any]:
        return {"integration_status": INTEGRATION_STATUS, "adapter": self.name}


# Operaciones soportadas por el adaptador de la capa Execution Contract V1.0.
EXECUTION_CONTRACT_OPS = {
    "flow.discover_capabilities", "flow.configure_from_spec",
    "flow.start_generation",
}


class ExecutionContractHandAdapter:
    """HandAdapter REAL de la capa Execution Contract V1.0 (FASE 7).

    Ejecuta operaciones flow.* contra un FlowOperator inyectado en el
    constructor (con controls_adapter → ConfigGate + FlowControlAdapter):
      * flow.discover_capabilities  → DISCOVER_CAPABILITIES (honesto)
      * flow.configure_from_spec    → VERIFY_CONTROLS (gate §6 con job_id)
      * flow.start_generation       → START_GENERATION (refusa si gate != ALLOW)

    Cada submit devuelve un HAND_RESULT bien formado (make_hand_result) con
    results = [OperationResult.to_dict()]. Operación desconocida ⇒
    BlockedError honesto (nada se inventa ni se degrada a no-op).
    NO activa ejecución física real: sobre Flow real el E2E sigue pendiente.
    """

    name = "execution_contract"

    def __init__(self, flow_operator: Any, evidence: Any | None = None):
        self.flow = flow_operator          # FlowOperator (inyección, sin imports)
        self.evidence = evidence

    def status(self) -> dict[str, Any]:
        return {"integration_status": INTEGRATION_STATUS, "adapter": self.name}

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        ok, errors = validate_hand_request(request)
        if not ok:
            raise ValidationError(
                "HAND_REQUEST inválido: " + "; ".join(errors),
                details={"validation_errors": errors})
        results: list[dict[str, Any]] = []
        for op in request.get("operations", []):
            op_name = op.get("op", "")
            if op_name == "flow.discover_capabilities":
                result = self.flow.discover_capabilities()
            elif op_name == "flow.configure_from_spec":
                result = self.flow.configure_from_spec(op.get("spec") or {},
                                                       job_id=op.get("job_id"))
            elif op_name == "flow.start_generation":
                result = self.flow.start_generation()
            else:
                raise BlockedError(
                    f"operación no soportada por {self.name}: {op_name!r} — "
                    "nada se ejecuta ni se inventa",
                    details={"supported": sorted(EXECUTION_CONTRACT_OPS),
                             "integration_status": INTEGRATION_STATUS})
            results.append(result.to_dict())
        status = "COMPLETED" \
            if all(r.get("status") == "COMPLETED" for r in results) else "FAILED"
        return make_hand_result(request["request_id"], status, results,
                                evidence_manifest=self.evidence.manifest()
                                if self.evidence is not None else None,
                                errors=[r["errors"][0] for r in results
                                        if r.get("errors")])


def integration_checklist() -> list[dict[str, str]]:
    """Pasos para la integración completa (§48.K). Paso 0 = capa contrato
    Execution Contract V1.0: HECHO (TESTED en mock). El resto: NO ejecutarlos
    todavía."""
    return [
        {"step": "0", "status": "DONE",
         "task": "Capa Execution Contract V1.0 conectada a HANDS (HECHO): "
                 "FlowOp de controles + FlowOperator.controls_adapter + "
                 "discover_capabilities/configure_from_spec + GATE en "
                 "start_generation (refusa sin ALLOW_GENERATE) + evidencia "
                 "refs job_id — TESTED en mock (tests/test_hands_contract.py)"},
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
