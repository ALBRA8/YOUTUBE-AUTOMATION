# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — paquete del arnés especializado (mandato §6)
# ─────────────────────────────────────────────────────────────────────
# Fachada de dominio sobre la fábrica existente. Agnóstico del host:
# NINGÚN módulo de este paquete importa el host (albra_seed,
# agente-general, Hermes, …). El flujo es SIEMPRE:
#
#   Host → Harness Contract → YouTube Harness → EXISTING ENGINE
#
# Módulos:
#   contracts     HarnessRequest / HarnessResult / estados externos
#   capabilities  registro de operaciones youtube.* y niveles de riesgo
#   permissions   modelo de permisos (destructivas con permiso propio)
#   knowledge     conocimiento estructurado del puesto (sin VÓRTICE)
#   adapter       fachada fina sobre la fábrica existente
#   harness       ejecutor + libro de ejecuciones idempotente
#   legacy        puente declarativo VÓRTICE → arnés (retiro futuro)
#   api           router HTTP versionado /api/harness/v1
# ─────────────────────────────────────────────────────────────────────
from .contracts import (CONTRACT_VERSION, HARNESS_NAME, CAPABILITY_ID,
                        EXTERNAL_STATES, HarnessRequest, HarnessResult,
                        HarnessValidationError, normalize_status)
from .harness import Harness, harness

__all__ = [
    "CONTRACT_VERSION", "HARNESS_NAME", "CAPABILITY_ID", "EXTERNAL_STATES",
    "HarnessRequest", "HarnessResult", "HarnessValidationError",
    "normalize_status", "Harness", "harness",
]
