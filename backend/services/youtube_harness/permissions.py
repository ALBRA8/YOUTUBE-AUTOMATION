# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — permissions.py (mandato §13 y §18)
# ─────────────────────────────────────────────────────────────────────
# Modelo de permisos del arnés.
#
# Regla de oro (§18): "no aceptes permisos arbitrarios enviados por el
# cliente; los permisos solicitados deben ser validados contra la
# identidad/credencial del caller."
#
# Infraestructura existente: NO hay multi-tenant ni service accounts en
# la fábrica (una única clave maestra con verificación en tiempo
# constante). Por eso, sin inventar identidad nueva:
#   1. El transporte (/api/harness/v1) reutiliza la autenticación
#      existente (auth_guard + csrf_guard + límites de body).
#   2. La solicitud debe DECLARAR los permisos que ejerce; el arnés
#      verifica que la operación exija un subconjunto de lo declarado.
#   3. Opcionalmente, la credencial del servicio puede RESTRINGIR los
#      scopes disponibles vía env HARNESS_ALLOWED_PERMISSIONS
#      (lista separada por comas): si está definida, un permiso
#      requerido fuera de esa lista → BLOCKED (fail-closed).
# Declarar MENOS permisos de los requeridos → rechazo. Declarar de más
# no otorga nada: el permiso efectivo SIEMPRE lo fija la operación.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import os

from .capabilities import OperationSpec
from .contracts import HarnessValidationError, BLOCKED

# ── catálogo de permisos del arnés ──────────────────────────────────
P_READ = "youtube.read"
P_CREATE = "youtube.production.create"
P_LAUNCH = "youtube.production.launch"
P_PUBLISH = "youtube.publish"
P_DESTROY = "youtube.destroy"
P_ADMIN = "youtube.admin"

KNOWN_PERMISSIONS: tuple[str, ...] = (
    P_READ, P_CREATE, P_LAUNCH, P_PUBLISH, P_DESTROY, P_ADMIN,
)

# youtube.admin implica todos los scopes (para hosts completos).
_ADMIN_EXPANSION: dict[str, tuple[str, ...]] = {
    P_ADMIN: (P_READ, P_CREATE, P_LAUNCH, P_PUBLISH, P_DESTROY),
}


def effective_permissions(declared: list[str]) -> set[str]:
    """Expande admin y devuelve el set de permisos efectivos."""
    eff: set[str] = set()
    for p in declared:
        eff.add(p)
        eff.update(_ADMIN_EXPANSION.get(p, ()))
    return eff


def allowed_scopes_for_credential() -> set[str] | None:
    """Scopes permitidos para la credencial en uso (§18).

    HARNESS_ALLOWED_PERMISSIONS=perm1,perm2 (env) restringe qué puede
    ejercer esta credencial concreto. None = sin restricción adicional
    (la autenticación del transporte ya es la frontera).
    """
    raw = (os.environ.get("HARNESS_ALLOWED_PERMISSIONS") or "").strip()
    if not raw:
        return None
    scopes = {p.strip() for p in raw.split(",") if p.strip()}
    if not scopes:
        return None
    return scopes


def authorize(req_permissions: list[str], spec: OperationSpec, *,
              credential_scopes: set[str] | None = None) -> None:
    """Valida permisos para ejecutar `spec`. Lanza HarnessValidationError.

    1. Todo permiso declarado debe ser conocido (nada arbitrario).
    2. El permiso requerido por la operación debe estar declarado
       (directamente o vía youtube.admin).
    3. Si la credencial tiene scopes restringidos, el permiso requerido
       debe estar dentro (fail-closed → estado BLOCKED).
    """
    eff = effective_permissions(req_permissions)
    for p in req_permissions:
        if p not in KNOWN_PERMISSIONS:
            raise HarnessValidationError(
                "PERMISSION_UNKNOWN",
                f"permiso desconocido: {p!r} (catálogo: "
                f"{', '.join(KNOWN_PERMISSIONS)})")
    if spec.required_permission not in eff:
        raise HarnessValidationError(
            "PERMISSION_MISSING",
            f"la operación {spec.name} requiere {spec.required_permission!r}; "
            f"declara permissions explícitamente "
            f"(recibidos: {req_permissions or '[]'})")
    if credential_scopes is not None and spec.required_permission not in credential_scopes:
        raise HarnessValidationError(
            "PERMISSION_NOT_GRANTED",
            f"la credencial del caller no habilita {spec.required_permission!r} "
            "(HARNESS_ALLOWED_PERMISSIONS)",)


def blocked_result_code() -> str:
    """Estado externo para denegación por scopes de credencial."""
    return BLOCKED
