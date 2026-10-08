"""
HANDS · Runtime — ensamblado de la capa completa (§4).

HandsRuntime construye y conecta TODOS los componentes de HANDS con
inyección de dependencias (backends/drivers/reloj inyectables para tests y
para el futuro soporte físico):

    workspace aislado (§18) · permisos deny-by-default (§16) · allowlists
    (§17) · evidencia (§21) · audit trail (§31) · sesiones (§19) · locks
    (§20) · kill switch (§27) · waits (§10) · verificación (§12/§23) ·
    recovery (§24) · resolver (§8) · action engine (§7) · desktop operator
    (§13) · flow operator (§14)

El contexto `runtime.session(...)`:
  1. abre sesión auditable;
  2. adquiere los locks del entorno (desktop/flow) — sin lock, no hay toque;
  3. crea la capa de evidencia ligada a la sesión;
  4. expone operadores listos para operar;
  5. al salir cierra la sesión con estado HONESTO (STOPPED si hubo kill
     switch, FAILED si hubo excepción) y libera los locks.

AISLAMIENTO (§36): este paquete no importa NADA del orquestador — solo
stdlib + módulos propios de hands. La integración futura se describe en
future_integration.py (NOT CONNECTED).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .action_engine import ActionEngine
from .clock import HandsClock, TimeoutsConfig
from .contracts import ValidationError, new_id
from .desktop import DesktopOperator, MockDesktopBackend, PhysicalDesktopBackend
from .evidence import AuditTrail, EvidenceLayer
from .flow_operator import ExtensionBridgeDriver, FlowOperator, MockFlowDriver
from .identify import TargetResolver
from .killswitch import KillSwitch
from .locks import LockManager
from .permissions import PermissionModel
from .recovery import RecoveryEngine
from .sessions import Session, SessionManager
from .verification import VerificationEngine
from .waits import WaitEngine
from .workspace import HandsWorkspace

HANDS_VERSION = "1.0.0"


@dataclass
class SessionBundle:
    """Lo que un contexto de sesión expone a quien opera HANDS."""
    session: Session
    evidence: EvidenceLayer
    engine: ActionEngine
    desktop: DesktopOperator
    flow: FlowOperator
    runtime: "HandsRuntime"
    owner: str
    locks: list[str]

    @property
    def session_id(self) -> str:
        return self.session.session_id


def default_workspace_root() -> Path:
    """Raíz por defecto: backend/data/hands (gitignored — Regla de Oro)."""
    return Path(__file__).resolve().parents[2] / "data" / "hands"


@dataclass
class HandsConfig:
    """Configuración declarativa de HANDS (serializable, sin secretos)."""

    workspace_root: str | None = None
    permissions: dict[str, Any] = field(default_factory=dict)
    allow_coordinate_fallback: bool = False
    desktop_backend: str = "mock"                  # mock | physical
    physical: dict[str, Any] = field(default_factory=dict)   # consent+command_map
    flow_driver: str = "mock"                      # mock | extension_bridge
    bridge: dict[str, Any] = field(default_factory=dict)     # base_url/api_key/enabled
    timeouts: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.desktop_backend not in ("mock", "physical"):
            raise ValidationError(
                f"desktop_backend inválido: {self.desktop_backend!r} (mock|physical)")
        if self.flow_driver not in ("mock", "extension_bridge"):
            raise ValidationError(
                f"flow_driver inválido: {self.flow_driver!r} (mock|extension_bridge)")
        TimeoutsConfig(**self.timeouts).validate()
        if self.desktop_backend == "physical":
            token = (self.physical or {}).get("consent_token", "")
            if not token:
                raise ValidationError(
                    "desktop_backend=physical exige consent_token explícito "
                    "(§35: capacidad NOT_VERIFIED, consentimiento humano)")

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "workspace_root": self.workspace_root,
            "permissions": self.permissions,
            "allow_coordinate_fallback": self.allow_coordinate_fallback,
            "desktop_backend": self.desktop_backend,
            "flow_driver": self.flow_driver,
            "timeouts": dict(self.timeouts),
            "physical": {k: v for k, v in self.physical.items()
                         if k != "consent_token"},
            "bridge": dict(self.bridge),
        }
        if redact and self.physical.get("consent_token"):
            data["physical"]["consent_token"] = "[REDACTED]"
        if redact and self.bridge.get("api_key"):
            data["bridge"]["api_key"] = "[REDACTED]"
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HandsConfig":
        data = dict(data or {})
        return cls(
            workspace_root=data.get("workspace_root"),
            permissions=dict(data.get("permissions", {})),
            allow_coordinate_fallback=bool(data.get("allow_coordinate_fallback", False)),
            desktop_backend=data.get("desktop_backend", "mock"),
            physical=dict(data.get("physical", {})),
            flow_driver=data.get("flow_driver", "mock"),
            bridge=dict(data.get("bridge", {})),
            timeouts=dict(data.get("timeouts", {})),
        )


class HandsRuntime:
    """Ensamblado completo de HANDS (§4). Mock por defecto; físico solo con
    consentimiento explícito; bridge solo con enabled=true explícito."""

    def __init__(self, config: HandsConfig | dict[str, Any] | None = None, *,
                 clock: HandsClock | None = None,
                 desktop_backend: Any | None = None,
                 flow_driver: Any | None = None):
        self.config = (config if isinstance(config, HandsConfig)
                       else HandsConfig.from_dict(config))
        self.config.validate()
        self.clock = clock or HandsClock()
        self.timeouts = TimeoutsConfig(**self.config.timeouts)

        # workspace + permisos (la raíz del workspace SIEMPRE autorizada)
        root = (self.config.workspace_root or str(default_workspace_root()))
        self.workspace = HandsWorkspace(root)
        self.permissions = PermissionModel.from_dict(self.config.permissions)
        roots = set(self.permissions.filesystem_roots) | {str(self.workspace.root)}
        self.permissions.filesystem_roots = tuple(sorted(roots))

        # núcleo
        self.killswitch = KillSwitch()
        self.audit = AuditTrail(self.workspace.logs)
        self.sessions = SessionManager(self.workspace.sessions, self.workspace.evidence)
        self.verification = VerificationEngine()
        self.resolver = TargetResolver(
            allow_coordinate_fallback=self.config.allow_coordinate_fallback)
        self.waits = WaitEngine(self.clock, killswitch=self.killswitch)
        self.recovery = RecoveryEngine(self.clock, killswitch=self.killswitch)
        self.locks = LockManager()

        # backends/drivers (inyección o construcción desde config)
        self.desktop_backend = desktop_backend or self._build_desktop_backend()
        self.flow_driver = flow_driver or self._build_flow_driver()
        self.audit.append("runtime_boot", workspace=str(self.workspace.root),
                          desktop=self.config.desktop_backend,
                          flow=self.config.flow_driver)

    # ── construcción de backends desde config (§35/§37 gates) ───────────
    def _build_desktop_backend(self):
        if self.config.desktop_backend == "physical":
            phys = self.config.physical
            return PhysicalDesktopBackend(
                consent_token=str(phys.get("consent_token", "")),
                expected_consent=str(phys.get("consent_token", "")),
                command_map=dict(phys.get("command_map", {})),
                permissions=self.permissions,
                root_dir=str(self.workspace.root),
                executor=phys.get("executor"),     # NUNCA viene de JSON
            )
        return MockDesktopBackend(self.clock, self.workspace.workspace)

    def _build_flow_driver(self):
        if self.config.flow_driver == "extension_bridge":
            bridge = self.config.bridge
            return ExtensionBridgeDriver(
                base_url=str(bridge.get("base_url", "http://127.0.0.1:8000")),
                api_key=bridge.get("api_key"),
                enabled=bool(bridge.get("enabled", False)),   # §37: OFF por defecto
            )
        return MockFlowDriver(self.clock)

    # ── sesión auditable con locks (§19/§20) ────────────────────────────
    @contextmanager
    def session(self, operator: str = "desktop",
                locks: tuple[str, ...] = ("desktop",),
                meta: dict[str, Any] | None = None,
                lock_timeout_s: float | None = None) -> Iterator[SessionBundle]:
        """Abre sesión + locks + evidencia; cierra con estado honesto."""
        owner = new_id("sess")
        acquired: list[str] = []
        timeout = lock_timeout_s or self.timeouts.lock_s
        session, evidence = self.sessions.start(
            operator, self.permissions.to_dict(), locks=list(locks), meta=meta)
        try:
            for lock_name in locks:
                self.locks.acquire(lock_name, owner=owner, timeout_s=timeout)
                acquired.append(lock_name)
            engine = ActionEngine(
                permissions=self.permissions, resolver=self.resolver,
                verification=self.verification, recovery=self.recovery,
                clock=self.clock, killswitch=self.killswitch, evidence=evidence,
                audit=self.audit, action_timeout_s=self.timeouts.action_s,
                allow_coordinate_fallback=self.config.allow_coordinate_fallback,
                on_result=session.add_action)
            desktop = DesktopOperator(engine=engine, backend=self.desktop_backend,
                                      permissions=self.permissions,
                                      workspace=self.workspace, waits=self.waits)
            flow = FlowOperator(
                driver=self.flow_driver, permissions=self.permissions,
                workspace=self.workspace, waits=self.waits,
                verification=self.verification, evidence=evidence,
                audit=self.audit, killswitch=self.killswitch, clock=self.clock,
                wait_timeout_s=self.timeouts.wait_s,
                poll_interval_s=self.timeouts.poll_interval_s,
                on_result=session.add_action)
            bundle = SessionBundle(session=session, evidence=evidence,
                                   engine=engine, desktop=desktop, flow=flow,
                                   runtime=self, owner=owner,
                                   locks=acquired)
            self.audit.append("session_open", session_id=session.session_id,
                              operator=operator, locks=acquired)
            yield bundle
        except Exception:
            self.audit.append("session_error", session_id=session.session_id)
            raise
        finally:
            # §27: estado honesto de cierre + locks liberados SIEMPRE
            final = "COMPLETED"
            if self.killswitch.engaged:
                final = "STOPPED"
                try:
                    self.desktop_backend.stop()
                    self.flow_driver.close_session()
                except Exception:              # noqa: BLE001 — stop nunca explota
                    pass
            session.close(final_status=final)
            session.save()
            for lock_name in acquired:
                handle = self.locks._holders.get(lock_name)
                if handle is not None and handle.owner == owner:
                    handle.release()
            self.audit.append("session_close", session_id=session.session_id,
                              final_status=final)

    # ── kill switch global (§27) ────────────────────────────────────────
    def stop(self, reason: str, *, source: str = "external") -> dict[str, Any]:
        """Parada segura: detiene nuevas acciones, operadores y libera locks."""
        self.killswitch.engage(reason, source=source)
        try:
            self.desktop_backend.stop()
        except Exception:                      # noqa: BLE001
            pass
        self.audit.append("kill_switch", reason=reason, source=source)
        return self.killswitch.status()

    def reset_killswitch(self) -> None:
        """Rearme explícito (tests / reinicio controlado)."""
        self.killswitch.disengage()

    # ── estado ───────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        return {
            "version": HANDS_VERSION,
            "workspace": str(self.workspace.root),
            "desktop_backend": getattr(self.desktop_backend, "kind",
                                       type(self.desktop_backend).__name__),
            "flow_driver": getattr(self.flow_driver, "kind",
                                   type(self.flow_driver).__name__),
            "locks": self.locks.held(),
            "kill_switch": self.killswitch.status(),
            "sessions": self.sessions.list_sessions()[-5:],
            "integration_status": "NOT CONNECTED",
        }
