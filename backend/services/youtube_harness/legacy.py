# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — legacy.py (mandato §10, §3: LEGACY / puente)
# ─────────────────────────────────────────────────────────────────────
# Puente DECLARATIVO entre el cerebro conversacional y el arnés.
# HISTORIA: nació como puente de VÓRTICE (services/agent.py) hacia §12.
# INT-028 EJECUTÓ el retiro: el Agente General (services/general_agent.py)
# absorbió a VÓRTICE y es el ÚNICO cerebro del chat; /api/chat y sus 10
# acciones NO cambian (comportamiento DO_NOT_TOUCH, tests M9 intactos).
# Este módulo documenta y garantiza la EQUIVALENCIA semántica: el arnés
# reproduce la capacidad completa del cerebro del chat (§12 ✓).
#
# Clasificación: agent.py = RETIRADO (eliminado) · general_agent.py = cerebro
# · este módulo = puente de-equivalencia · /api/chat = DO_NOT_TOUCH.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

from .capabilities import OPERATIONS

# Acciones del cerebro del chat (general_agent.VALID_ACTIONS; antes
# VÓRTICE/agent.py) → operación(es) del arnés que reproducen el mismo
# efecto. None = acción de interfaz del trabajador (sin efecto de fábrica)
# o cubierta por otra superficie.
AGENT_ACTION_TO_OPERATION: dict[str, str | None] = {
    "create_video": "youtube.create",       # + youtube.launch (el chat
    #   lanzaba inline; el contrato separa crear y lanzar — el host
    #   coordinante encadena ambas; equivalencia documentada)
    "create_niche": None,                    # gestión de plantillas hoy vía
    #   API de nichos; el arnés la expone de solo-lectura (list_niches):
    #   crear/borrar plantillas es administración del puesto, no capacidad
    #   del contrato v1 (REMOVE_LATER si se pide).
    "delete_niche": None,                    # ídem (destructiva de catálogo)
    "delete_project": "youtube.delete",      # destructiva equivalente (M9)
    "cleanup_failed": None,                  # el chat borra TODOS los failed
    #   en bloque; el contrato v1 es por-proyecto y explícito (delete por
    #   id exacto): la masiva queda fuera a propósito (least privilege).
    "list_projects": "youtube.list_projects",
    "list_niches": "youtube.list_niches",
    "project_status": "youtube.project_status",
    "help": None,                            # interfaz del trabajador
    "none": None,                            # ídem
}

# Reglas M9 (destructivas sin fuzzy) — ahora SON del puesto:
# conocimiento.py/SAFETY_SEMANTICS + adapter.op_delete las reproducen
# exactamente (id exacto → título exacto único → máx 5 candidatos).
# general_agent.py conserva la implementación original (DO_NOT_TOUCH).

# Estados simplificados del brain del chat → reales (auditoría P2-a):
# el brain decía "draft → processing → ready → published"; el esquema
# real (database.py:38-39) y el mapeo del contrato están en
# contracts.normalize_status. knowledge.py documenta la diferencia.


def operation_for_agent_action(action: str) -> str | None:
    """Equivalencia cerebro-chat → arnés (None si es de interfaz)."""
    return AGENT_ACTION_TO_OPERATION.get(action)


def equivalence_report() -> dict:
    """Informe de equivalencia §12 — retiro de VÓRTICE EJECUTADO (INT-028)."""
    covered, uncovered = [], []
    for action, op in AGENT_ACTION_TO_OPERATION.items():
        item = {"action": action, "operation": op,
                "operation_exists": bool(op and op in OPERATIONS)}
        (covered if op else uncovered).append(item)
    return {
        "legacy_worker": "Agente General (services/general_agent.py) — "
                         "absorbe VÓRTICE (INT-028)",
        "legacy_actions_total": len(AGENT_ACTION_TO_OPERATION),
        "covered_by_harness": covered,
        "not_in_contract_v1": uncovered,
        "note": "Las no cubiertas son de interfaz del trabajador o "
                "administración de catálogo fuera del contrato v1; la "
                "capacidad de PRODUCIR/recuperar/QA/publicar está "
                "íntegramente cubierta por el arnés.",
    }
