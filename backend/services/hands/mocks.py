"""
HANDS · Mock Environment — entorno completo simulado (§34).

Objetivo: HANDS puede probarse SIN depender del PC real. MockEnvironment
ensambla en un directorio temporal:

  * FakeClock        — tiempo determinista (timeouts instantáneos)
  * HandsWorkspace   — workspace aislado real (tmp)
  * MockDesktopBackend — escritorio simulado (ventanas/elementos/fs/procesos)
  * MockFlowDriver   — ciclo de generación Flow simulado (magic bytes reales)
  * HandsRuntime     — runtime completo con inyección de los mocks

Los hooks de caos (ventana desaparece, proceso congelado, fichero que tarda,
UI cambia, fallo puntual, rate limit) viven en los mocks y se exponen aquí
como la puerta única para las baterías FAILURE/CHAOS.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .clock import FakeClock
from .desktop import MockDesktopBackend
from .flow_operator import MockFlowDriver
from .permissions import PermissionModel
from .runtime import HandsConfig, HandsRuntime
from .workspace import HandsWorkspace

DEFAULT_ALLOWLIST: dict[str, Any] = {
    "applications": ["notepad-mock", "browser-mock", "files-mock"],
    "domains": ["flow.google.com", "labs.google.com", "127.0.0.1"],
    "browser_urls": ["https://flow.google.com/*", "https://labs.google.com/*"],
    "commands": [],          # sin comandos por defecto: deny-by-default
}


class MockEnvironment:
    """Entorno mock completo para tests unitarios/integración/chaos."""

    def __init__(self, *, root: str | Path, allowlist: dict[str, Any] | None = None,
                 clock: FakeClock | None = None,
                 allow_coordinate_fallback: bool = False,
                 controls_state: dict[str, Any] | None = None,
                 controls_missing: tuple = (), controls_frozen: tuple = (),
                 controls_stale: tuple = ()):
        self.clock = clock or FakeClock()
        self.workspace = HandsWorkspace(root)
        self.allowlist = dict(allowlist if allowlist is not None
                              else DEFAULT_ALLOWLIST)
        self.desktop_mock = MockDesktopBackend(self.clock, self.workspace.workspace)
        # Execution Contract V1.0 (FASE 7): los parámetros de controles se
        # delegan en MockFlowDriver (que construye su MockFlowControlAdapter);
        # el FlowOperator los hereda vía driver.controls_adapter. NADA más
        # cambia: defaults ⇒ comportamiento idéntico al legacy.
        self.flow_mock = MockFlowDriver(
            self.clock, controls_state=controls_state,
            controls_missing=controls_missing, controls_frozen=controls_frozen,
            controls_stale=controls_stale)
        config = HandsConfig.from_dict({
            "workspace_root": str(self.workspace.root),
            "permissions": self.allowlist,
            "allow_coordinate_fallback": allow_coordinate_fallback,
            "desktop_backend": "mock",
            "flow_driver": "mock",
        })
        self.runtime = HandsRuntime(
            config, clock=self.clock,
            desktop_backend=self.desktop_mock,
            flow_driver=self.flow_mock,
        )

    # ── puertas de caos (§33) ────────────────────────────────────────────
    def chaos_fail_next(self, op: str, error: Any) -> None:
        self.desktop_mock.fail_next(op, error)

    def chaos_window_disappears(self, title: str) -> None:
        self.desktop_mock.remove_window(title)

    def chaos_freeze_process(self, name: str) -> None:
        self.desktop_mock.freeze_process(name)

    def chaos_delayed_file(self, path: str | Path, delay_s: float,
                           content: bytes = b"late") -> None:
        self.desktop_mock.register_delayed_file(path, delay_s, content)

    def chaos_ui_change(self, mutator) -> None:
        self.desktop_mock.ui_change(mutator)

    def chaos_flow_freeze(self) -> None:
        self.flow_mock.frozen = True

    def chaos_flow_fail_submit(self) -> None:
        self.flow_mock.fail_submit = True

    def chaos_flow_rate_limit(self, after: int) -> None:
        self.flow_mock.rate_limit_after = after

    def chaos_corrupt_flow_results(self, keys: set[str]) -> None:
        self.flow_mock.corrupt_results |= set(keys)

    # ── utilidades ───────────────────────────────────────────────────────
    def permissions(self) -> PermissionModel:
        return self.runtime.permissions

    def seed_file(self, area: str, name: str, content: bytes) -> Path:
        path = self.workspace.path_for(area, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path
