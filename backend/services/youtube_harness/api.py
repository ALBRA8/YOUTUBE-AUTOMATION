# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — api.py · interfaz HTTP machine-to-machine (§16-§18)
# ─────────────────────────────────────────────────────────────────────
# Router versionado bajo /api/harness/v1. NUNCA es un bypass de
# seguridad: al ser incluido en la app principal, hereda los middlewares
# existentes (auth_guard por prefijo /api/, csrf_guard por método,
# techo global de Content-Length). No hay rutas públicas nuevas.
#
# Para tráfico m2m sin Origin/Referer (curl/hosts/servicios) el CSRF
# existente ya lo permite por diseño (decisión documentada en main.py);
# un navegador con Origin externo sigue bloqueado. No se desactiva ni
# relaja NADA.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import database as db

from .capabilities import manifest as capabilities_manifest
from .contracts import (CONTRACT_VERSION, HARNESS_NAME, HarnessRequest,
                        HarnessValidationError)
from .harness import harness
from .knowledge import KNOWLEDGE_VERSION, knowledge_manifest
from .legacy import equivalence_report

HARNESS_VERSION = "1.0.0"          # semver propio del arnés
COMPAT_HOSTS = "host-agnostic"     # ningún import del host; contrato puro
SUPPORTED_TRANSPORTS = ["http"]

router = APIRouter(prefix="/api/harness/v1")


def _system_version() -> str:
    # import diferido: main.py importa este módulo al final del arranque
    import main as _main
    return getattr(_main.app, "version", "unknown")


# ───────────────────────────────────────────────────────── /manifest ─
@router.get("/manifest")
async def harness_manifest(knowledge: bool = False):
    """Manifiesto del arnés: identidad, contrato, operaciones, riesgo,
    transportes, salud. Sin secretos, jamás (§16)."""
    capa = capabilities_manifest()
    out = {
        "harness": HARNESS_NAME,
        "version": HARNESS_VERSION,
        "contract_version": CONTRACT_VERSION,
        "system_version": _system_version(),
        "capability": capa["capability"],
        "operations": capa["operations"],
        "risk_levels": capa["risk_levels"],
        "destructive_operations": capa["destructive_operations"],
        "supported_transports": SUPPORTED_TRANSPORTS,
        "compatibility": {
            "contract": f"youtube-harness-contract/{CONTRACT_VERSION}",
            "hosts": COMPAT_HOSTS,
            "notes": "cualquier host que hable Harness Contract V1 "
                     "(AGENTE-GENERAL, Hermes, OpenClaw, …) sin acoplarse",
        },
        "health": _health_snapshot(),
        "knowledge_version": KNOWLEDGE_VERSION,
    }
    if knowledge:
        out["knowledge"] = knowledge_manifest()
        out["legacy_equivalence"] = equivalence_report()
    return out


# ────────────────────────────────────────────────────────── /execute ─
@router.post("/execute")
async def harness_execute(body: dict):
    """Ejecuta una operación del contrato y devuelve un HarnessResult.

    Validación ESTRICTA (§7): contrato/ids/permisos/operación; una
    operación desconocida nunca se acepta silenciosamente (404
    estructurado). Los errores de la operación viajan DENTRO del
    HarnessResult (status FAILED/BLOCKED/RECOVERABLE + errors[]).
    """
    try:
        req = HarnessRequest.from_dict(body)
    except HarnessValidationError as exc:
        raise HTTPException(status_code=400, detail={
            "error": {"code": exc.code, "reason": exc.reason}}) from None
    result = await harness.execute(req)
    # operación desconocida → 404 estructurado (no silencioso, §7)
    for err in result.errors:
        if err.get("code") == "OPERATION_UNKNOWN":
            raise HTTPException(status_code=404, detail={
                "error": err,
                "hint": "GET /api/harness/v1/manifest"})
    return result.to_dict()


# ────────────────────────────────────────── /executions/{id} (§16) ──
@router.get("/executions/{execution_id}")
async def harness_execution(execution_id: str):
    rec = harness.get_execution(execution_id)
    if rec is None:
        raise HTTPException(404, "ejecución no encontrada")
    return rec


# ─────────────────────────────────────────────────────────── /health ─
@router.get("/health")
async def harness_health():
    """Salud del arnés para orquestadores (autenticada: bajo /api/)."""
    return _health_snapshot()


def _health_snapshot() -> dict:
    db_ok = True
    try:
        db.kv_get("harness_health_probe")
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "ok": db_ok,
        "harness": HARNESS_NAME,
        "harness_version": HARNESS_VERSION,
        "contract_version": CONTRACT_VERSION,
        "system_version": _system_version(),
        "checks": {"database": db_ok},
    }
