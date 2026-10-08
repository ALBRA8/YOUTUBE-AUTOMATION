"""
HANDS — capa de EJECUCIÓN FÍSICA de YOUTUBE-AUTOMATION (V1.0 aislada).

═══════════════════════════════════════════════════════════════════════════
CONTRATO DE LA CAPA (§1-§5 del brief):

    YOUTUBE-AUTOMATION = WHAT (qué historia, qué prompt, qué escena)
    HANDS              = EXECUTION (ejecutar operaciones controladas)
    FLOW OPERATOR      = HOW within Google Flow
    DESKTOP OPERATOR   = HOW within Desktop

HANDS NO es un agente creativo: no inventa prompts, historias, escenas ni
estilos. Ejecuta operaciones bajo permisos explícitos (deny-by-default),
con observación→identificación→acción→observación→verificación, esperas con
timeout, verificación de resultados, recovery acotado, locks, evidencia
hasheada, audit trail, sesiones auditables y kill switch.

ESTADO DE INTEGRACIÓN (§36/§37/§48.J):

    YOUTUBE-AUTOMATION INTEGRATION: NOT CONNECTED

HANDS vive AL LADO del sistema, no ENCIMA: no importa nada del orquestador
(solo stdlib + módulos hands) y nada del orquestador importa a hands.
La puerta futura está descrita en future_integration.py.

Módulos (mapa del brief §4 → código):
    contracts          estados/errores/operaciones/acciones/targets/observación
    clock              tiempo inyectable + timeouts configurables (§25)
    permissions        permisos + 5 allowlists (§16/§17)
    workspace          workspace aislado + frontera fs (§18)
    evidence           evidencia + audit + redacción de secretos (§21/§31/§32)
    locks              locks de entorno + file lock (§20)
    killswitch         parada segura (§27)
    sessions           sesiones auditables (§19)
    waits              espera por condiciones (§10)
    verification       veredictos + file verification + captura (§12/§22/§23)
    recovery           recuperación controlada (§24)
    identify           jerarquía de identificación (§8)
    action_engine      motor OBSERVE→IDENTIFY→ACTION→OBSERVE→VERIFY (§7)
    desktop            Desktop Operator (§13, backend mock + físico NOT_VERIFIED)
    flow_operator      Flow Operator (§14, driver mock + adaptador bridge §47)
    runtime            ensamblado + sesiones + kill switch global
    mocks              entorno simulado completo (§34)
    future_integration puerta futura NOT CONNECTED (§37)
    selfaudit          auditoría automática (§40)
    cleanroom          validación clean-room (§42)

Uso canónico:
    from services.hands import HandsRuntime
    runtime = HandsRuntime({"permissions": {...}, "workspace_root": ...})
    with runtime.session(operator="desktop", locks=("desktop",)) as h:
        result = h.desktop.open_app("notepad-mock")
CLI:
    python3 -m services.hands info|selfaudit|cleanroom
"""
from __future__ import annotations

from pathlib import Path

# ── versión y estado ─────────────────────────────────────────────────────
HANDS_VERSION = "1.0.0"
HANDS_PACKAGE_DIR = Path(__file__).resolve().parent

from .future_integration import INTEGRATION_STATUS          # noqa: E402,F401

# ── contratos ────────────────────────────────────────────────────────────
from .contracts import (                                    # noqa: E402,F401
    ActionSpec, ErrorCode, FlowOp, HandsError, Observation, Op,
    OperationResult, State, TargetSpec, TargetStrategy, new_id, now_iso,
    ActionFailedError, BlockedError, HandsTimeoutError, InvalidTransitionError,
    PermissionDeniedError, RecoveryFailedError, StoppedError, TargetNotFoundError,
    UnknownStateError, ValidationError, VerificationFailedError,
)

# ── componentes ──────────────────────────────────────────────────────────
from .clock import FakeClock, HandsClock, TimeoutsConfig    # noqa: E402,F401
from .permissions import Allowlists, CommandRule, PermissionModel        # noqa: E402,F401
from .workspace import HandsWorkspace, PathBoundary         # noqa: E402,F401
from .evidence import AuditTrail, EvidenceLayer, redact     # noqa: E402,F401
from .locks import FileLock, LockManager                    # noqa: E402,F401
from .killswitch import KillSwitch                          # noqa: E402,F401
from .sessions import Session, SessionManager               # noqa: E402,F401
from .waits import WaitEngine, WaitOutcome, WaitSpec        # noqa: E402,F401
from .verification import (VerificationEngine, Verdict, verify_file)  # noqa: E402,F401
from .recovery import RecoveryEngine, RecoveryPolicy        # noqa: E402,F401
from .identify import TargetResolver                        # noqa: E402,F401

# ── operadores y runtime ─────────────────────────────────────────────────
from .action_engine import ActionEngine                     # noqa: E402,F401
from .desktop import (DesktopOperator, MockDesktopBackend,  # noqa: E402,F401
                      PhysicalDesktopBackend)
from .flow_operator import (ExtensionBridgeDriver, FlowJobSpec,  # noqa: E402,F401
                            FlowOperator, MockFlowDriver)
from .runtime import HandsConfig, HandsRuntime, HANDS_VERSION  # noqa: E402,F401
from .mocks import MockEnvironment                          # noqa: E402,F401
from .future_integration import NotConnectedAdapter         # noqa: E402,F401

__all__ = [
    # metadatos
    "HANDS_VERSION", "HANDS_PACKAGE_DIR", "INTEGRATION_STATUS",
    # contratos
    "ActionSpec", "ErrorCode", "FlowOp", "HandsError", "Observation", "Op",
    "OperationResult", "State", "TargetSpec", "TargetStrategy", "new_id",
    "now_iso",
    "ActionFailedError", "BlockedError", "HandsTimeoutError",
    "InvalidTransitionError", "PermissionDeniedError", "RecoveryFailedError",
    "StoppedError", "TargetNotFoundError", "UnknownStateError",
    "ValidationError", "VerificationFailedError",
    # componentes
    "FakeClock", "HandsClock", "TimeoutsConfig",
    "Allowlists", "CommandRule", "PermissionModel",
    "HandsWorkspace", "PathBoundary",
    "AuditTrail", "EvidenceLayer", "redact",
    "FileLock", "LockManager", "KillSwitch", "Session", "SessionManager",
    "WaitEngine", "WaitOutcome", "WaitSpec",
    "VerificationEngine", "Verdict", "verify_file",
    "RecoveryEngine", "RecoveryPolicy", "TargetResolver",
    # operadores y runtime
    "ActionEngine", "DesktopOperator", "MockDesktopBackend",
    "PhysicalDesktopBackend", "ExtensionBridgeDriver", "FlowJobSpec",
    "FlowOperator", "MockFlowDriver", "HandsConfig", "HandsRuntime",
    "MockEnvironment", "NotConnectedAdapter",
]
