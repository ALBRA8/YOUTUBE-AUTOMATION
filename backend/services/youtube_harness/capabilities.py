# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — capabilities.py (mandato §13)
# ─────────────────────────────────────────────────────────────────────
# Registro explícito de capabilities y operaciones del arnés.
# Una operación desconocida NUNCA se ejecuta silenciosamente: si no
# está en este registro, no existe para el host.
#
# Riesgo: LOW (lectura) · MEDIUM (mutación reversible) ·
#         HIGH (efecto externo o de cola) · CRITICAL (destructiva).
# Las destructivas (delete/cleanup) tienen riesgo elevado y requieren
# su permiso propio: no bastan los permisos de producción (§13).
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import CAPABILITY_ID

# Riesgos
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class OperationSpec:
    """Especificación declarativa de una operación del arnés."""
    name: str                      # p.ej. "youtube.create"
    summary: str                   # qué hace, en una línea
    risk: str                      # LOW/MEDIUM/HIGH/CRITICAL
    required_permission: str       # permiso que DEBE declarar el host
    destructive: bool = False      # borra datos de la fábrica
    idempotent: bool = False       # misma solicitud → mismo efecto
    input_fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    #   input_fields: (nombre, descripción) de las claves esperadas en input

    def describe(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "risk": self.risk,
            "destructive": self.destructive,
            "idempotent": self.idempotent,
            "required_permission": self.required_permission,
            "input_fields": [{"name": n, "description": d}
                             for n, d in self.input_fields],
        }


def _op(name: str, summary: str, risk: str, perm: str, *,
        destructive: bool = False, idempotent: bool = False,
        fields: tuple[tuple[str, str], ...] = ()) -> OperationSpec:
    return OperationSpec(name=f"youtube.{name}", summary=summary, risk=risk,
                         required_permission=perm, destructive=destructive,
                         idempotent=idempotent, input_fields=fields)


# ── registro canónico de operaciones (mandato §13) ──────────────────
_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    # ── lectura (LOW) ───────────────────────────────────────────────
    _op("list_projects", "Lista proyectos de la fábrica con estado normalizado.",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("limit", "máximo de proyectos a devolver (default 40, tope 200)"),)),
    _op("project_status", "Estado detallado de un proyecto (intento + Flow + QA).",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("project_id", "id canónico del proyecto (12 hex)"),)),
    _op("list_niches", "Lista plantillas de nicho registradas.",
        RISK_LOW, "youtube.read", idempotent=True),
    _op("list_styles", "Lista el catálogo de estilos visuales.",
        RISK_LOW, "youtube.read", idempotent=True),
    _op("list_avatars", "Lista avatares (personajes DNA) registrados.",
        RISK_LOW, "youtube.read", idempotent=True),
    _op("system_status", "Salud del sistema: proveedores, contadores, versión.",
        RISK_LOW, "youtube.read", idempotent=True),
    _op("flow_status", "Estado de la cola Flow de un proyecto (jobs + exec).",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("project_id", "id canónico del proyecto"),)),
    _op("flow_preflight", "REAL FLOW PREFLIGHT: barrera antes de gastar una "
        "prueba real con Google Flow.",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("project_id", "opcional: proyecto concreto a pre-chequear"),)),
    _op("production_doctor", "Diagnóstico por capas A-I: audit | fix | "
        "verify | report (reparaciones solo lista blanca).",
        RISK_LOW, "youtube.read",
        fields=(("action", "audit (default) | fix | verify | report"),
                ("deep", "diagnóstico profundo (bool)"),)),
    _op("validate_production", "Valida un Creative Production JSON sin crear "
        "nada: errores estructurales + avisos + normalizaciones.",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("production_json", "payload del contrato creativo"),)),
    _op("video_qa", "QA forense del video final (pantalla negra/azul, audio "
        "silencioso, warns).",
        RISK_LOW, "youtube.read", idempotent=True,
        fields=(("project_id", "id canónico del proyecto"),)),

    # ── mutación (MEDIUM) ───────────────────────────────────────────
    _op("create", "Crea un proyecto (modo idea o nicho-plantilla) SIN "
        "lanzarlo. El lanzamiento es youtube.launch.",
        RISK_MEDIUM, "youtube.production.create",
        fields=(("idea", "tema/idea del video (≤180 chars)"),
                ("nicho", "nombre EXACTO de nicho-plantilla (opcional)"),
                ("format", "short | long"),
                ("style", "id del catálogo o 'auto'"),
                ("avatar", "nombre del avatar DNA (opcional)"),
                ("platforms", "lista ⊆ youtube|tiktok|instagram|facebook"),)),
    _op("submit_production", "Ingiere un Creative Production JSON (crea el "
        "proyecto y opcionalmente lanza con constraints.launch=true).",
        RISK_MEDIUM, "youtube.production.create",
        fields=(("production_json", "payload del contrato creativo"),
                ("launch", "true → lanza el pipeline tras ingerir"),)),
    _op("cancel", "Cancela el trabajo activo de un proyecto (job_id o pid).",
        RISK_MEDIUM, "youtube.production.launch",
        fields=(("job_id", "id del job a cancelar (o project_id)"),
                ("project_id", "alternativa: cancela el job activo del proyecto"),)),
    _op("recover", "Recupera leases Flow vencidas (anti-zombie) y devuelve "
        "cuántos jobs re-encoló.",
        RISK_MEDIUM, "youtube.production.launch", idempotent=True),

    # ── efecto externo / de cola (HIGH) ─────────────────────────────
    _op("launch", "Lanza el pipeline de producción de un proyecto "
        "(guion → imágenes → TTS → render).",
        RISK_HIGH, "youtube.production.launch",
        fields=(("project_id", "id canónico del proyecto"),)),
    _op("publish", "Publica el video terminado en YouTube (side effect "
        "EXTERNO, idempotente por proyecto, con QA gate).",
        RISK_HIGH, "youtube.publish",
        fields=(("project_id", "id canónico del proyecto"),
                ("title", "título del upload (default: título del proyecto)"),
                ("description", "descripción del upload"),
                ("tags", "etiquetas"),
                ("private", "publicación privada (default true)"),
                ("publish_at", "programación ISO-8601 (opcional)"),)),

    # ── destructivas (CRITICAL; permiso propio, §13) ────────────────
    _op("delete", "BORRA un proyecto: carpeta de salida + escenas + jobs + "
        "flow_jobs. Irreversible; exige permiso youtube.destroy.",
        RISK_CRITICAL, "youtube.destroy", destructive=True,
        fields=(("project_id", "id canónico EXACTO (12 hex); nunca fuzzy"),)),
    _op("cleanup", "Libera disco: borra intermedios del proyecto (conserva "
        "MP4 final). Destructiva para artefactos intermedios.",
        RISK_HIGH, "youtube.destroy", destructive=True,
        fields=(("project_id", "id canónico del proyecto"),)),
)

OPERATIONS: dict[str, OperationSpec] = {s.name: s for s in _OPERATION_SPECS}


def get_operation(name: str) -> OperationSpec | None:
    return OPERATIONS.get(name)


def require_operation(name: str) -> OperationSpec:
    spec = OPERATIONS.get(name)
    if spec is None:
        raise KeyError(name)
    return spec


def list_operations() -> list[dict]:
    return [OPERATIONS[k].describe() for k in sorted(OPERATIONS)]


def manifest() -> dict:
    """Bloque capabilities/operations del /manifest (sin secretos)."""
    return {
        "capability": CAPABILITY_ID,
        "operations": list_operations(),
        "risk_levels": [RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL],
        "destructive_operations": sorted(
            name for name, spec in OPERATIONS.items() if spec.destructive),
    }
