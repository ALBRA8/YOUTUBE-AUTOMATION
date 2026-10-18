# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — harness.py
# ─────────────────────────────────────────────────────────────────────
# Fachada de dominio: valida la solicitud contra el contrato, autoriza
# por permisos, despacha al adaptador y lleva un LIBRO DE EJECUCIONES
# (idempotente por execution_id) persistido en el kv store existente.
#
# El host NUNCA toca orchestrator/db directamente: pasa por aquí.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import time
from typing import Any

import database as db

from . import adapter
from .capabilities import get_operation
from .contracts import (ACCEPTED, BLOCKED, CONTRACT_VERSION, FAILED,
                        RECOVERABLE, RUNNING, HarnessRequest, HarnessResult,
                        HarnessValidationError)
from .permissions import allowed_scopes_for_credential, authorize

_LEDGER_PREFIX = "harness_exec:"
_LEDGER_MAX_JSON = 32000  # tope de registro por ejecución (kv)


class Harness:
    """Ejecutor del contrato YouTube Harness Contract V1."""

    def __init__(self, *, ledger_prefix: str = _LEDGER_PREFIX):
        self._ledger_prefix = ledger_prefix

    # ── libro de ejecuciones (kv existente; sin tablas nuevas) ──────
    def _ledger_key(self, execution_id: str) -> str:
        return f"{self._ledger_prefix}{execution_id}"

    def _record(self, result: HarnessResult) -> None:
        try:
            payload = json.dumps(result.to_dict(), ensure_ascii=False)
            if len(payload) > _LEDGER_MAX_JSON:
                payload = json.dumps(
                    {**result.to_dict(),
                     "outputs": {"truncated": True}}, ensure_ascii=False)
            db.kv_set(self._ledger_key(result.execution_id), payload)
        except Exception:  # noqa: BLE001 — el libro nunca rompe la ejecución
            pass

    def get_execution(self, execution_id: str) -> dict | None:
        raw = db.kv_get(self._ledger_key(execution_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    # ── ejecución ───────────────────────────────────────────────────
    async def execute(self, req: HarnessRequest, *,
                      credential_scopes: set[str] | None = None) -> HarnessResult:
        started = time.monotonic()
        result = HarnessResult.for_request(req)
        result.metadata = {"requester": req.requester}
        if req.correlation_id:
            result.metadata["correlation_id"] = req.correlation_id

        spec = get_operation(req.operation)
        if spec is None:
            # NUNCA aceptar una operación desconocida silenciosamente (§7)
            return result.with_error(
                "OPERATION_UNKNOWN",
                f"operación desconocida: {req.operation!r}. "
                "Consulta GET /api/harness/v1/manifest",
                status=BLOCKED)

        # idempotencia de ejecución: mismo execution_id → mismo resultado
        previo = self.get_execution(req.execution_id)
        if previo is not None:
            replay = HarnessResult(**{k: v for k, v in previo.items()
                                      if k in HarnessResult.__dataclass_fields__})
            replay.metadata = {**(replay.metadata or {}),
                               "replayed": True}
            return replay

        # autorización (§18): permisos declarados ⊇ requeridos por la op
        scopes = credential_scopes if credential_scopes is not None \
            else allowed_scopes_for_credential()
        try:
            authorize(req.permissions, spec, credential_scopes=scopes)
        except HarnessValidationError as exc:
            return result.with_error(exc.code, exc.reason, status=BLOCKED)

        # despacho al adaptador
        try:
            out = await self._dispatch(req, spec.name)
        except adapter.AdapterError as exc:
            result.with_error(exc.code, exc.message, status=exc.status)
            result.recovery = ({"recoverable": exc.recoverable,
                                "hint": "youtube.recover o "
                                        "youtube.production_doctor"}
                               if exc.recoverable else {})
            self._record(result)
            return result
        except HarnessValidationError as exc:
            result.with_error(exc.code, exc.reason, status=BLOCKED)
            self._record(result)
            return result
        except Exception as exc:  # noqa: BLE001 — frontera del contrato
            result.with_error("INTERNAL", f"{type(exc).__name__}: {exc}")
            self._record(result)
            return result

        result.status = self._final_status(spec.name, out)
        result.outputs = out if isinstance(out, dict) else {"value": out}
        if isinstance(out, dict):
            result.project_id = out.get("project_id")
            if result.project_id is None and isinstance(out.get("project"), dict):
                result.project_id = out["project"].get("project_id")
            result.job_id = out.get("job_id")
        if isinstance(out, dict) and out.get("warnings"):
            result.warnings = list(out["warnings"])[:20]
        if spec.destructive:
            result.evidence.append({"kind": "destructive_operation",
                                    "operation": spec.name,
                                    "requester": req.requester})
        result.metrics = {"duration_ms":
                          int((time.monotonic() - started) * 1000)}
        self._record(result)
        return result

    # ── despacho con flags del contrato ─────────────────────────────
    async def _dispatch(self, req: HarnessRequest, op: str) -> dict:
        if op == "youtube.launch":
            autopublish = bool((req.constraints or {}).get("autopublish"))
            return await adapter.op_launch(req.input, autopublish=autopublish)
        if op == "youtube.submit_production":
            launch = bool((req.constraints or {}).get("launch"))
            return await adapter.op_submit_production(req.input, launch=launch)
        fn = adapter.OPS.get(op)
        if fn is None:  # defensa: registry y OPS desalineados
            raise adapter.AdapterError(
                "OPERATION_UNKNOWN",
                f"operación registrada sin adaptador: {op}", status=BLOCKED)
        return fn(req.input)

    # ── estado externo final por operación ──────────────────────────
    @staticmethod
    def _final_status(op: str, out: Any) -> str:
        if not isinstance(out, dict):
            return ACCEPTED
        if op == "youtube.launch":
            return RUNNING
        if op == "youtube.submit_production":
            return RUNNING if out.get("job_id") else ACCEPTED
        if op == "youtube.cancel":
            return ACCEPTED
        if op == "youtube.recover":
            return ACCEPTED
        if op == "youtube.validate_production":
            return ACCEPTED if out.get("valid") else BLOCKED
        if op == "youtube.flow_preflight":
            return ACCEPTED if out.get("preflight") == "PASS" else BLOCKED
        if op == "youtube.publish":
            return out.get("external_status") or FAILED
        if "project" in out and isinstance(out["project"], dict):
            return out["project"].get("status") or ACCEPTED
        if "projects" in out or "niches" in out or "styles" in out \
                or "avatars" in out or "counts" in out or "qa" in out:
            return out.get("external_status") or ACCEPTED
        return ACCEPTED


# Instancia única del arnés (el resto del backend la consume del módulo).
harness = Harness()
