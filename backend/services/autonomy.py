"""
YOUTUBE AUTOMATION v2.0 — NIVELES DE AUTONOMÍA (§26)

Escalera L0..L5 que acota QUÉ puede ejecutar el sistema sin humano:

  L0_OBSERVE          solo lectura (métricas, estado)
  L1_RECOMMEND        recomienda; el humano decide
  L2_EXECUTE_SAFE     ejecuta operaciones INTERNAS seguras (cola, pipeline, QA)
  L3_EXECUTE_EXTERNAL además, acciones EXTERNAS controladas: publicar en
                      YouTube — SIEMPRE respetando la política de publicación
                      (FACTORY_AUTOPUBLISH + credenciales reales)
  L4_EXECUTE_SENSITIVE además, acciones SENSIBLES: reparaciones del doctor,
                      escritura de configuración, restaurar backups
  L5_SELF_IMPROVE     promoción de aprendizajes / auto-mejora — SIEMPRE con
                      humano en el bucle y batería de regresión en verde

Separación §26 (producir / publicar / auto-mejora):
  · PRODUCIR (L2) es operación normal de fábrica: cola, pasos, QA.
  · PUBLICAR (L3) toca el mundo exterior: respeta la policy y jamás se
    autoriza "en cascada" desde otro dominio.
  · SELF-IMPROVEMENT (L5) NUNCA puede saltarse la seguridad ni la política de
    publicación: ningún resultado de auto-mejora otorga permisos de publish/
    security. assert_no_bypass() lo hace INVIOABLE — se llama antes de
    conceder cualquier acción:
        autonomy.check(action)                      → ¿nivel alcanza?
        autonomy.assert_no_bypass(action, granted_by=origen) → ¿origen legítimo?
"""
import os

# ── Escalera de niveles (índice = valor del nivel) ──────────────────────────
LEVELS = ("L0_OBSERVE", "L1_RECOMMEND", "L2_EXECUTE_SAFE",
          "L3_EXECUTE_EXTERNAL", "L4_EXECUTE_SENSITIVE", "L5_SELF_IMPROVE")

ENV_VAR = "FACTORY_AUTONOMY_LEVEL"   # se lee en CADA llamada (os.getenv) →
DEFAULT_LEVEL = 2                    # los tests pueden monkeypatchear el env
MAX_LEVEL = 5

# ── Descripción de cada nivel (una línea, español) ──────────────────────────
DESCRIPTIONS = {
    "L0_OBSERVE": "Solo observación: métricas y estado de solo lectura; cero efectos sobre el sistema.",
    "L1_RECOMMEND": "Recomienda acciones con su evidencia, pero no ejecuta nada: decide el humano.",
    "L2_EXECUTE_SAFE": "Ejecuta operaciones internas seguras (cola, pipeline, QA, recuperación) sin tocar el exterior.",
    "L3_EXECUTE_EXTERNAL": "Además, acciones externas controladas: publicar en YouTube respetando la política de publicación.",
    "L4_EXECUTE_SENSITIVE": "Además, acciones sensibles: reparaciones del doctor, escritura de configuración y backups.",
    "L5_SELF_IMPROVE": "Promoción de aprendizajes y auto-mejora; siempre con humano en el bucle y regresión en verde.",
}

# ── Acción → nivel mínimo requerido (§26) ───────────────────────────────────
# producing (L2) / publishing (L3) / sensible (L4) / self-improvement (L5).
# Acción desconocida → MAX_LEVEL (fail-closed: lo que no está mapeado, lo
# decide el humano).
ACTION_LEVELS: dict[str, int] = {
    # L0 — observación pura
    "observe": 0,
    "metrics": 0,
    # L1 — recomendación
    "recommend": 1,
    # L2 — producir (interno y seguro)
    "queue_production": 2,
    "run_pipeline": 2,
    "recover_production": 2,
    "retry_step": 2,
    # L3 — publicar (externo; respeta policy de publicación)
    "publish_video": 3,
    "upload_external": 3,
    # L4 — sensible
    "doctor_fix": 4,
    "config_write": 4,
    "backup_restore": 4,
    # L5 — auto-mejora (humano en el bucle)
    "memory_promotion": 5,
    "self_improve": 5,
}

# ── Guardas anti-bypass (§26: self-improvement jamás salta seguridad ni ──────
#    política de publicación) ────────────────────────────────────────────────
# Acciones de publish/seguridad que NINGÚN origen de auto-mejora puede otorgar.
_SIN_BYPASS_EXACTAS = {"publish_video", "upload_external", "config_write"}
_SIN_BYPASS_PREFIJOS = ("publish_", "security_")
# Origenes "SELF-IMPROVEMENT-ish": su output JAMÁS autoriza lo protegido.
_OTORGADORES_SELF = {"self_improve", "self_improvement", "memory_promotion",
                     "learning"}


def _norma(texto) -> str:
    """Normaliza identificadores de acción/origen ('self-improvement' ==
    'self_improvement')."""
    return str(texto or "").strip().lower().replace("-", "_")


def current_level() -> int:
    """Nivel de autonomía ACTUAL: parsea FACTORY_AUTONOMY_LEVEL del entorno en
    cada llamada (default "2") con clamping 0..5; valor inválido → default."""
    raw = os.getenv(ENV_VAR)
    if raw is None or not str(raw).strip():
        return DEFAULT_LEVEL
    try:
        nivel = int(str(raw).strip())
    except ValueError:
        return DEFAULT_LEVEL
    return max(0, min(MAX_LEVEL, nivel))


def required_level(action: str) -> int:
    """Nivel mínimo requerido por una acción. Fail-closed: acción no mapeada
    → MAX_LEVEL (la decide el humano, no el sistema)."""
    requerido = ACTION_LEVELS.get(_norma(action))
    return MAX_LEVEL if requerido is None else requerido


def check(action: str) -> dict:
    """¿Puede el sistema (nivel actual) ejecutar `action`?
    Devuelve {allowed, action, required, current, motivo} — NUNCA lanza."""
    requerido = required_level(action)
    actual = current_level()
    permitida = actual >= requerido
    if permitida:
        motivo = (f"permitida: nivel actual {actual} ({LEVELS[actual]}) ≥ "
                  f"requerido {requerido} ({LEVELS[requerido]}) para "
                  f"'{action}'")
    else:
        motivo = (f"bloqueada: '{action}' requiere nivel {requerido} "
                  f"({LEVELS[requerido]}) y el sistema corre en nivel "
                  f"{actual} ({LEVELS[actual]}) — sube {ENV_VAR} o actúa el "
                  f"humano")
    return {"allowed": permitida, "action": action, "required": requerido,
            "current": actual, "motivo": motivo}


def require(action: str) -> dict:
    """Igual que check() pero EXIGE el permiso: lanza PermissionError con
    mensaje en español citando ambos niveles si no se alcanza el requerido."""
    veredicto = check(action)
    if not veredicto["allowed"]:
        raise PermissionError(
            f"Permiso denegado: la acción '{action}' requiere nivel "
            f"{veredicto['required']} ({LEVELS[veredicto['required']]}) y el "
            f"sistema corre en nivel {veredicto['current']} "
            f"({LEVELS[veredicto['current']]}). Sube {ENV_VAR} o ejecútala "
            f"como humano.")
    return veredicto


def assert_no_bypass(action: str, granted_by: str | None = None) -> bool:
    """Guarda §26: el auto-mejora NUNCA otorga publish/security.

    Lanza ValueError si `granted_by` es un origen SELF-IMPROVEMENT-ish
    (self_improve, self-improvement, memory_promotion, learning) y `action`
    es una acción de publicación/seguridad (publish_video, upload_external,
    config_write, o cualquier publish_*/security_*).

    Devuelve True cuando no hay bypass (origen legítimo o acción no
    protegida). Uso antes de conceder:
        autonomy.check("publish_video")                     → ¿nivel alcanza?
        autonomy.assert_no_bypass("publish_video",
                                  granted_by="self_improve") → ValueError ✓
    """
    if granted_by is None:
        return True
    origen = _norma(granted_by)
    if origen not in _OTORGADORES_SELF:
        return True
    accion = _norma(action)
    protegida = (accion in _SIN_BYPASS_EXACTAS
                 or any(accion.startswith(p) for p in _SIN_BYPASS_PREFIJOS))
    if protegida:
        raise ValueError(
            f"BYPASS PROHIBIDO (§26): '{origen}' (auto-mejora) NUNCA puede "
            f"autorizar la acción '{accion}' (publicación/seguridad). El "
            f"self-improvement no salta la security ni la publishing policy: "
            f"lo concede un humano o un nivel L3+ legítimo, jamás un "
            f"aprendizaje automático.")
    return True
