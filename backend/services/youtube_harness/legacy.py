# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — legacy.py (mandato §10, §3: LEGACY / puente)
# ─────────────────────────────────────────────────────────────────────
# Puente DECLARATIVO entre el trabajador legacy (VÓRTICE, agent.py) y el
# arnés. VÓRTICE sigue siendo el trabajador actual: /api/chat y sus 10
# acciones NO cambian (comportamiento DO_NOT_TOUCH); este módulo solo
# documenta y garantiza la EQUIVALENCIA semántica para que el día que
# VÓRTICE se retire, el arnés reproduzca su capacidad (§12).
#
# Clasificación: agent.py = LEGACY · este módulo = puente de-equivalencia
# · /api/chat = DO_NOT_TOUCH (los tests de seguridad M9 lo ejercitan).
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

from .capabilities import OPERATIONS

# Acciones VÓRTICE (agent.py VALID_ACTIONS) → operación(es) del arnés
# que reproducen el mismo efecto. None = acción de interfaz del
# trabajador (sin efecto de fábrica) o cubierta por otra superficie.
VORTICE_ACTION_TO_OPERATION: dict[str, str | None] = {
    "create_video": "youtube.create",       # + youtube.launch (VÓRTICE
    #   lanzaba inline; el contrato separa crear y lanzar — el host
    #   coordinante encadena ambas; equivalencia documentada)
    "create_niche": None,                    # gestión de plantillas hoy vía
    #   API de nichos; el arnés la expone de solo-lectura (list_niches):
    #   crear/borrar plantillas es administración del puesto, no capacidad
    #   del contrato v1 (REMOVE_LATER si se pide).
    "delete_niche": None,                    # ídem (destructiva de catálogo)
    "delete_project": "youtube.delete",      # destructiva equivalente (M9)
    "cleanup_failed": None,                  # VÓRTICE borra TODOS los failed
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
# agent.py conserva su implementación (DO_NOT_TOUCH) hasta retiro.

# Estados simplificados del brain de VÓRTICE → reales (auditoría P2-a):
# el brain decía "draft → processing → ready → published"; el esquema
# real (database.py:38-39) y el mapeo del contrato están en
# contracts.normalize_status. knowledge.py documenta la diferencia.


def operation_for_vortice_action(action: str) -> str | None:
    """Equivalencia VÓRTICE → arnés (None si es de interfaz)."""
    return VORTICE_ACTION_TO_OPERATION.get(action)


def equivalence_report() -> dict:
    """Informe de equivalencia para el retiro futuro de VÓRTICE (§12)."""
    covered, uncovered = [], []
    for action, op in VORTICE_ACTION_TO_OPERATION.items():
        item = {"action": action, "operation": op,
                "operation_exists": bool(op and op in OPERATIONS)}
        (covered if op else uncovered).append(item)
    return {
        "legacy_worker": "VÓRTICE (services/agent.py)",
        "legacy_actions_total": len(VORTICE_ACTION_TO_OPERATION),
        "covered_by_harness": covered,
        "not_in_contract_v1": uncovered,
        "note": "Las no cubiertas son de interfaz del trabajador o "
                "administración de catálogo fuera del contrato v1; la "
                "capacidad de PRODUCIR/recuperar/QA/publicar está "
                "íntegramente cubierta por el arnés.",
    }
