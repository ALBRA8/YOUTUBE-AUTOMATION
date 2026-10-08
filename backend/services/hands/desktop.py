"""
HANDS · Desktop Operator — especialista de escritorio (§13).

Componentes:

* DesktopBackend      — protocolo del backend físico (observe/perform/stop).
* MockDesktopBackend  — simulación completa y determinista: ventanas,
  elementos, clipboard, filesystem SANDBOX, procesos, descargas, capturas y
  HOOKS DE CAOS (ventana desaparece, proceso se congela, fichero tarda,
  UI cambia, fallo puntual). Permite probar HANDS sin PC real (§34).
* PhysicalDesktopBackend — soporte de ejecución física REAL (§35) bajo tres
  candados: consentimiento explícito + mapeo declarado de operaciones a
  comandos + allowlist de comandos (deny-by-default). MATURIDAD honesta:
  NOT_VERIFIED (nunca se ha probado en un PC real).
* DesktopOperator     — fachada operacional: apps, input, filesystem,
  procesos, evidencia. TODA operación pasa por ActionEngine (§7) y por el
  modelo de permisos (§16). HANDS ejecuta; no decide (§5).
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from .action_engine import ActionEngine
from .clock import HandsClock
from .contracts import (ActionSpec, ActionFailedError, BlockedError,
                        HandsError, Observation, ElementRef, DownloadRef,
                        FileRef, ProcessRef, Op, PermissionDeniedError,
                        State, TargetMatch, TargetNotFoundError,
                        TargetSpec, ValidationError, new_id, now_iso)
from .evidence import EvidenceLayer, sha256_bytes
from .permissions import PermissionModel
from .verification import (CaptureCapability, FileVerificationResult,
                           NullCapture, Verdict, verify_file)
from .waits import WaitEngine, WaitOutcome
from .workspace import HandsWorkspace, PathBoundary

# bytes PNG mínimos válidos (firma real) para capturas simuladas
_FAKE_PNG = (b"\x89PNG\r\n\x1a\n" + b"mock-screenshot-" + uuid.uuid4().hex.encode())


# ════════════════════════════════════════════════════════════════════════
# Mock backend — entorno de escritorio simulado (§34)
# ════════════════════════════════════════════════════════════════════════
class MockDesktopBackend:
    """Escritorio simulado determinista con hooks de caos inyectables."""

    kind = "mock"

    def __init__(self, clock: HandsClock, root_dir: str | Path):
        self.clock = clock
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.boundary = PathBoundary(self.root)
        self.stopped = False
        # estado simulado
        self.windows: dict[str, dict[str, Any]] = {}
        self.focused: str | None = None
        self.clipboard: str = ""
        self.processes: dict[str, dict[str, Any]] = {}
        self.downloads: list[DownloadRef] = []
        self.errors: list[str] = []
        self.last_click: dict[str, Any] | None = None
        self.command_handlers: dict[str, Callable[[list[str]], dict[str, Any]]] = {}
        # hooks de caos
        self._fail_once: dict[str, HandsError] = {}
        self._delayed_files: list[dict[str, Any]] = []
        self._pids = 1000

    # ── hooks de caos (§33/§34) ──────────────────────────────────────────
    def fail_next(self, op: str, error: HandsError) -> None:
        """Próxima ejecución de `op` falla una vez con ese error."""
        self._fail_once[op] = error

    def remove_window(self, title: str) -> None:
        """CAOS: la ventana desaparece (crash/cierre externo)."""
        self.windows.pop(title, None)
        if self.focused == title:
            self.focused = next(iter(self.windows), None)

    def freeze_process(self, name: str) -> None:
        """CAOS: el proceso se congela."""
        if name in self.processes:
            self.processes[name]["state"] = "frozen"

    def register_delayed_file(self, path: str | Path, delay_s: float,
                              content: bytes = b"delayed") -> None:
        """CAOS: fichero tarda — aparece cuando el reloj avance delay_s."""
        self._delayed_files.append({"path": Path(path), "at": self.clock.monotonic() + delay_s,
                                    "content": content})

    def materialize_due_files(self) -> None:
        """Materializa ficheros vencidos (el proveedor de observación lo llama)."""
        now = self.clock.monotonic()
        due = [d for d in self._delayed_files if d["at"] <= now]
        for d in due:
            d["path"].parent.mkdir(parents=True, exist_ok=True)
            d["path"].write_bytes(d["content"])
            self._delayed_files.remove(d)

    def ui_change(self, mutator: Callable[[list[ElementRef]], None]) -> None:
        """CAOS: la UI cambia a mitad de flujo (mutador sobre los elementos)."""
        for window in self.windows.values():
            mutator(window["elements"])

    # ── observación (§9) ─────────────────────────────────────────────────
    def observe(self) -> Observation:
        self.materialize_due_files()
        focused = self.windows.get(self.focused) if self.focused else None
        elements: list[ElementRef] = []
        for window in self.windows.values():
            elements.extend(window["elements"])
        files = [FileRef(path=str(p), size=p.stat().st_size if p.is_file() else None)
                 for p in sorted(self.root.rglob("*")) if p.is_file()]
        procs = [ProcessRef(pid=p["pid"], name=n, state=p["state"],
                            command=p.get("command"))
                 for n, p in self.processes.items()]
        return Observation(
            timestamp=now_iso(),
            application=(focused or {}).get("app"),
            window=self.focused,
            state="stopped" if self.stopped else ("running" if self.windows else "idle"),
            elements=elements,
            downloads=list(self.downloads),
            files=files,
            processes=procs,
            errors=list(self.errors),
            visual_digest=self._visual_digest(),
        )

    def _visual_digest(self) -> str:
        import hashlib
        parts = []
        for title, window in sorted(self.windows.items()):
            parts.append(title)
            for el in window["elements"]:
                parts.append(f"{el.ref_id}:{el.semantic}:{el.text}:{el.extra.get('value')}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    # ── ejecución de operaciones ─────────────────────────────────────────
    def perform(self, name: str, match: TargetMatch | None,
                params: dict[str, Any]) -> dict[str, Any]:
        if self.stopped:
            raise BlockedError("backend simulado detenido (stop)")
        injected = self._fail_once.pop(name, None)
        if injected is not None:
            raise injected
        handler = getattr(self, f"_op_{name.lower()}", None)
        if handler is None:
            raise ActionFailedError(f"operación no soportada por el mock: {name}")
        return handler(match, params)

    def stop(self) -> None:
        self.stopped = True

    def capture(self) -> CaptureCapability:
        backend = self

        class _MockCapture(NullCapture):
            def screenshot(self) -> bytes | None:
                return _FAKE_PNG

            def window_state(self) -> dict[str, Any] | None:
                return {"focused": backend.focused,
                        "windows": sorted(backend.windows)}

        return _MockCapture()

    # ── operaciones individuales ─────────────────────────────────────────
    def _op_observe(self, match, params) -> dict[str, Any]:
        return {"observation": self.observe().to_dict()}

    def _op_open(self, match, params) -> dict[str, Any]:
        app = str(params.get("application") or params.get("name") or "").strip()
        if not app:
            raise ValidationError("OPEN exige params.application")
        title = f"{app} — Ventana principal"
        if title not in self.windows:
            self.windows[title] = {"app": app, "elements": self._default_elements(app)}
        self.focused = title
        return {"opened": app, "window": title}

    def _op_close(self, match, params) -> dict[str, Any]:
        app = str(params.get("application") or params.get("name") or "").strip()
        titles = [t for t, w in self.windows.items() if w["app"] == app]
        if not titles:
            raise TargetNotFoundError(f"aplicación \"{app}\" no está abierta",
                                      details={"app": app})
        for t in titles:
            self.windows.pop(t)
            if self.focused == t:
                self.focused = next(iter(self.windows), None)
        return {"closed": app, "windows_remaining": list(self.windows)}

    def _op_focus(self, match, params) -> dict[str, Any]:
        title = params.get("window") or (match.element_ref if match else None)
        if title and title not in self.windows:
            # match por título parcial
            candidates = [t for t in self.windows
                          if str(title).lower() in t.lower()]
            title = candidates[0] if candidates else None
        if not title or title not in self.windows:
            raise TargetNotFoundError(f"ventana no encontrada: {title!r}",
                                      details={"windows": list(self.windows)})
        self.focused = title
        return {"focused": title}

    def _op_click(self, match, params) -> dict[str, Any]:
        self.last_click = {"match": match.to_dict() if match else None,
                           "button": params.get("button", "left"),
                           "ts": now_iso()}
        if match is None:
            raise TargetNotFoundError("CLICK sin match de target")
        if match.element_ref:
            el = self._find_by_ref(match.element_ref)
            if el is None:
                raise TargetNotFoundError(f"elemento desaparecido: {match.element_ref}")
            self.last_click["element"] = el.semantic
            return {"clicked": el.semantic, "strategy": match.strategy.value}
        if match.strategy.value == "coordinates":
            self.last_click["coords"] = list(match.value)   # fallback controlado
            return {"clicked_coords": list(match.value)}
        raise ActionFailedError("CLICK sin elemento ni coordenadas válidas")

    def _op_double_click(self, match, params) -> dict[str, Any]:
        result = self._op_click(match, params)
        result["double"] = True
        return result

    def _op_type(self, match, params) -> dict[str, Any]:
        text = str(params.get("text", ""))
        el = self._resolve_editable(match)
        el.extra["value"] = el.extra.get("value", "") + text
        return {"typed": len(text), "ref": el.ref_id,
                "value": el.extra["value"]}

    def _op_paste(self, match, params) -> dict[str, Any]:
        el = self._resolve_editable(match)
        el.extra["value"] = el.extra.get("value", "") + self.clipboard
        return {"pasted": len(self.clipboard), "ref": el.ref_id}

    def _op_hotkey(self, match, params) -> dict[str, Any]:
        combo = params.get("combo") or params.get("keys")
        if not combo:
            raise ValidationError("HOTKEY exige params.combo")
        return {"hotkey": combo, "focused": self.focused}

    def _op_scroll(self, match, params) -> dict[str, Any]:
        return {"scrolled": params.get("amount", 0),
                "direction": params.get("direction", "down")}

    def _op_drag(self, match, params) -> dict[str, Any]:
        src = params.get("from") or (match.value if match else None)
        dst = params.get("to")
        if not src or not dst:
            raise ValidationError("DRAG exige params.from y params.to")
        return {"dragged_from": src, "dragged_to": dst}

    def _op_copy(self, match, params) -> dict[str, Any]:
        return self._fs_transfer(params, move=False)

    def _op_move(self, match, params) -> dict[str, Any]:
        return self._fs_transfer(params, move=True)

    def _op_rename(self, match, params) -> dict[str, Any]:
        src = self.boundary.resolve_within(params["src"], must_exist=True)
        dst = self.boundary.resolve_within(params["dst"])
        src.rename(dst)
        return {"renamed": str(src), "to": str(dst)}

    def _op_download(self, match, params) -> dict[str, Any]:
        """Descarga simulada: bytes → downloads/ (contenido determinista)."""
        name = str(params.get("dest_name") or f"download_{new_id('dl')}.bin")
        dest = self.boundary.resolve_within(Path(self.root) / "downloads" / name)
        content = params.get("content")
        if content is None:
            content = b"mock-download:" + name.encode()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and params.get("skip_if_exists"):
            return {"downloaded": str(dest), "skipped": True,
                    "size": dest.stat().st_size}
        dest.write_bytes(content)
        ref = DownloadRef(path=str(dest), status="done",
                          size=len(content), source=params.get("source"))
        self.downloads.append(ref)
        return {"downloaded": str(dest), "size": len(content),
                "sha256": sha256_bytes(content)}

    def _op_execute_allowed(self, match, params) -> dict[str, Any]:
        argv = [str(a) for a in params.get("argv", [])]
        if not argv:
            raise ValidationError("EXECUTE_ALLOWED exige params.argv")
        binary = argv[0]
        handler = self.command_handlers.get(binary)
        if handler is None:
            raise ActionFailedError(
                f"comando \"{binary}\" sin handler en el entorno simulado",
                details={"registered": sorted(self.command_handlers)})
        timeout_s = params.get("_timeout_s")
        self._register_process(binary)
        try:
            out = handler(argv)
        finally:
            proc = self.processes.get(binary)
            if proc is not None:
                proc["state"] = "finished"
        return {"returncode": out.get("returncode", 0),
                "stdout": out.get("stdout", ""),
                "stderr": out.get("stderr", ""),
                "timeout_s": timeout_s}

    def _op_wait(self, match, params) -> dict[str, Any]:
        return {"waited": params.get("timeout_s", 0)}

    def _op_verify(self, match, params) -> dict[str, Any]:
        return {"verified": True}

    def _op_capture(self, match, params) -> dict[str, Any]:
        shot = self.capture().screenshot()
        return {"screenshot_sha256": sha256_bytes(shot) if shot else None,
                "available": shot is not None}

    def _op_stop(self, match, params) -> dict[str, Any]:
        self.stop()
        return {"stopped": True}

    def _op_recover(self, match, params) -> dict[str, Any]:
        return {"recovered": True, "note": "mock recovery no-op"}

    # ── internals ────────────────────────────────────────────────────────
    def _default_elements(self, app: str) -> list[ElementRef]:
        return [
            ElementRef(ref_id=new_id("el"), semantic=f"{app}.prompt_input",
                       accessibility="role=textarea name=prompt",
                       text="", dom=f"textarea#{app}-prompt", editable=True,
                       extra={"value": ""}),
            ElementRef(ref_id=new_id("el"), semantic=f"{app}.send_button",
                       accessibility="role=button name=Enviar",
                       text="Enviar", dom=f"button#{app}-send", clickable=True),
            ElementRef(ref_id=new_id("el"), semantic=f"{app}.status_bar",
                       text="Listo"),
        ]

    def _find_by_ref(self, ref_id: str) -> ElementRef | None:
        for window in self.windows.values():
            for el in window["elements"]:
                if el.ref_id == ref_id:
                    return el
        return None

    def _resolve_editable(self, match: TargetMatch | None) -> ElementRef:
        if match is None or not match.element_ref:
            raise TargetNotFoundError("TYPE/PASTE exige un elemento editable identificado")
        el = self._find_by_ref(match.element_ref)
        if el is None:
            raise TargetNotFoundError(f"elemento desaparecido: {match.element_ref}")
        if not el.editable:
            raise ActionFailedError(f"el elemento {el.ref_id} no es editable")
        return el

    def _fs_transfer(self, params: dict[str, Any], *, move: bool) -> dict[str, Any]:
        src = self.boundary.resolve_within(params["src"], must_exist=True)
        dst = self.boundary.resolve_within(params["dst"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))
        return {"from": str(src), "to": str(dst), "moved": move}

    def _register_process(self, name: str) -> None:
        self._pids += 1
        self.processes[name] = {"pid": self._pids, "state": "running",
                                "command": name}


# ════════════════════════════════════════════════════════════════════════
# Backend físico (§35) — preparado, NO VERIFICADO
# ════════════════════════════════════════════════════════════════════════
class PhysicalDesktopBackend:
    """Ejecución física REAL sobre el PC — DESACTIVADA POR DEFECTO (§28/§35).

    Triple candado:
      1. consent_token debe coincidir EXACTAMENTE con el declarado por el
         configurador humano (sin consentimiento ⇒ PermissionDeniedError);
      2. cada operación exige un mapeo declarado op→plantilla argv en
         `command_map` (sin mapeo ⇒ la operación no está disponible);
      3. el argv resultante pasa por PermissionModel.check_command
         (deny-by-default, sin shell jamás).

    MATURIDAD: NOT_VERIFIED — la arquitectura está preparada, pero NINGÚN
    método ha sido probado contra un escritorio real. Los métodos fs usan
    PathBoundary; observe() devuelve una observación mínima HONESTA
    (state=physical_not_verified) hasta implementar sondeos reales.
    """

    kind = "physical"
    MATURITY = "NOT_VERIFIED"

    def __init__(self, *, consent_token: str, expected_consent: str,
                 command_map: dict[str, list[str]],
                 permissions: PermissionModel, root_dir: str | Path,
                 executor: Callable[[list[str], float], dict[str, Any]] | None = None):
        if consent_token != expected_consent or not expected_consent:
            raise PermissionDeniedError(
                "PhysicalDesktopBackend exige consentimiento físico explícito "
                "(consent_token != expected_consent) — §35: capacidad NO_VERIFIED",
                details={"category": "application"})
        self.consent = True
        self.command_map = {k: list(v) for k, v in command_map.items()}
        self.permissions = permissions
        self.boundary = PathBoundary(root_dir)
        self.executor = executor
        self.stopped = False

    # ── observación honesta mínima ───────────────────────────────────────
    def observe(self) -> Observation:
        return Observation(
            timestamp=now_iso(),
            state="physical_not_verified",
            errors=["observación física no implementada (NOT_VERIFIED §35)"],
            extra={"maturity": self.MATURITY},
        )

    def capture(self) -> CaptureCapability:
        return NullCapture()

    def stop(self) -> None:
        self.stopped = True

    # ── ejecución ────────────────────────────────────────────────────────
    def perform(self, name: str, match: TargetMatch | None,
                params: dict[str, Any]) -> dict[str, Any]:
        if self.stopped:
            raise BlockedError("backend físico detenido")
        template = self.command_map.get(name)
        if template is None:
            raise PermissionDeniedError(
                f"operación física \"{name}\" sin mapeo declarado en command_map "
                "(deny-by-default §16)",
                details={"category": "command", "mapped": sorted(self.command_map)})
        argv = [self._substitute(part, match, params) for part in template]
        decision = self.permissions.check_command(argv)
        if decision.denied:
            raise PermissionDeniedError(decision.reason,
                                        details={"category": "command", "argv": argv})
        timeout_s = float(params.get("_timeout_s") or 30.0)
        if self.executor is None:
            raise BlockedError(
                "PhysicalDesktopBackend sin executor configurado — nada se "
                "ejecuta en el PC real sin un executor explícito",
                details={"category": "command"})
        outcome = self.executor(argv, timeout_s)
        return {"argv": argv, "timeout_s": timeout_s, **outcome}

    # ── internals ────────────────────────────────────────────────────────
    @staticmethod
    def _substitute(part: str, match: TargetMatch | None,
                    params: dict[str, Any]) -> str:
        out = part
        for key, value in params.items():
            if key.startswith("_"):
                continue
            out = out.replace("{" + key + "}", str(value))
        if match is not None:
            if match.element_ref:
                out = out.replace("{target}", str(match.element_ref))
            elif isinstance(match.value, (tuple, list)):
                out = out.replace("{target}", ",".join(str(v) for v in match.value))
            else:
                out = out.replace("{target}", str(match.value))
        return out


# ════════════════════════════════════════════════════════════════════════
# Desktop Operator — fachada operacional (§13)
# ════════════════════════════════════════════════════════════════════════
class DesktopOperator:
    """Especialista de escritorio: TODA operación pasa por ActionEngine."""

    name = "desktop"

    def __init__(self, *, engine: ActionEngine, backend,
                 permissions: PermissionModel, workspace: HandsWorkspace,
                 waits: WaitEngine):
        self.engine = engine
        self.backend = backend
        self.permissions = permissions
        self.workspace = workspace
        self.waits = waits

    # ── observación / captura ────────────────────────────────────────────
    def observe(self) -> Observation:
        return self.backend.observe()

    def capture(self) -> CaptureCapability:
        return self.backend.capture()

    def capture_to_evidence(self, evidence: EvidenceLayer) -> dict[str, Any]:
        """Captura (§22) referenciada en evidencia con hash (no solo screenshot)."""
        shot = self.backend.capture().screenshot()
        window = self.backend.capture().window_state()
        if shot:
            path = self.workspace.path_for("evidence", f"shot_{new_id('cap')}.png")
            path.write_bytes(shot)
            return {"screenshot": str(path), "sha256": sha256_bytes(shot),
                    "window_state": window}
        return {"screenshot": None, "window_state": window,
                "note": "captura no disponible (honesto §22)"}

    # ── aplicaciones ─────────────────────────────────────────────────────
    def open_app(self, app: str, *, timeout_s: float | None = None,
                 recovery: dict[str, Any] | None = None) -> Any:
        spec = ActionSpec(
            name=Op.OPEN.value, params={"application": app},
            target=None,
            idempotency_check=lambda obs: bool(obs.window)
            and app.lower() in obs.window.lower(),
            verify={"kind": "window_contains", "value": app},
            timeout_s=timeout_s, recovery=recovery,
            description=f"abrir aplicación {app}",
        )
        return self.engine.execute(spec, self.backend)

    def close_app(self, app: str, *, timeout_s: float | None = None) -> Any:
        spec = ActionSpec(name=Op.CLOSE.value, params={"application": app},
                          timeout_s=timeout_s, description=f"cerrar {app}")
        return self.engine.execute(spec, self.backend)

    def focus_window(self, title: str, *, timeout_s: float | None = None) -> Any:
        spec = ActionSpec(name=Op.FOCUS.value, params={"window": title},
                          verify={"kind": "window_contains", "value": title},
                          timeout_s=timeout_s)
        return self.engine.execute(spec, self.backend)

    def detect_windows(self) -> Observation:
        return self.backend.observe()

    # ── input ────────────────────────────────────────────────────────────
    def click(self, target: TargetSpec, *, timeout_s: float | None = None,
              **params: Any) -> Any:
        spec = ActionSpec(name=Op.CLICK.value, target=target,
                          params=params, timeout_s=timeout_s)
        return self.engine.execute(spec, self.backend)

    def double_click(self, target: TargetSpec, *, timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.DOUBLE_CLICK.value, target=target,
                       timeout_s=timeout_s), self.backend)

    def type_text(self, target: TargetSpec, text: str, *,
                  timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.TYPE.value, target=target, params={"text": text},
                       timeout_s=timeout_s), self.backend)

    def paste(self, target: TargetSpec, *, timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.PASTE.value, target=target,
                       timeout_s=timeout_s), self.backend)

    def hotkey(self, combo: str, *, timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.HOTKEY.value, params={"combo": combo},
                       timeout_s=timeout_s), self.backend)

    def scroll(self, amount: int, direction: str = "down", *,
               timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.SCROLL.value,
                       params={"amount": amount, "direction": direction},
                       timeout_s=timeout_s), self.backend)

    def drag(self, src: TargetSpec, dst: TargetSpec, *,
             timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.DRAG.value, target=src,
                       params={"to": dst.to_dict()}, timeout_s=timeout_s),
            self.backend)

    # ── filesystem (dentro del workspace autorizado) ─────────────────────
    def copy_file(self, src: str | Path, dst: str | Path, *,
                  timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.COPY.value, params={"src": str(src), "dst": str(dst)},
                       verify={"kind": "file_exists", "path": str(dst)},
                       timeout_s=timeout_s), self.backend)

    def move_file(self, src: str | Path, dst: str | Path, *,
                  timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.MOVE.value, params={"src": str(src), "dst": str(dst)},
                       verify={"kind": "file_exists", "path": str(dst)},
                       timeout_s=timeout_s), self.backend)

    def rename_file(self, src: str | Path, dst: str | Path, *,
                    timeout_s: float | None = None) -> Any:
        return self.engine.execute(
            ActionSpec(name=Op.RENAME.value, params={"src": str(src), "dst": str(dst)},
                       verify={"kind": "file_exists", "path": str(dst)},
                       timeout_s=timeout_s), self.backend)

    # ── procesos (§13) ───────────────────────────────────────────────────
    def execute_allowed(self, argv: list[str], *, timeout_s: float | None = None,
                        recovery: dict[str, Any] | None = None) -> Any:
        """§16: solo comandos de la allowlist; deny-by-default."""
        return self.engine.execute(
            ActionSpec(name=Op.EXECUTE_ALLOWED.value, params={"argv": [str(a) for a in argv]},
                       timeout_s=timeout_s, recovery=recovery,
                       description="ejecutar comando permitido"), self.backend)

    def wait_for_process(self, name: str, *, state: str | None = None,
                         timeout_s: float, poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.waits.wait_for_process(
            name=name, state=state, timeout_s=timeout_s,
            provider=self.backend.observe, poll_interval_s=poll_interval_s)

    # ── esperas y verificación delegadas ─────────────────────────────────
    def wait_for_window(self, title: str, *, timeout_s: float,
                        poll_interval_s: float = 0.5) -> WaitOutcome:
        return self.waits.wait_for_window(
            title, timeout_s=timeout_s, provider=self.backend.observe,
            poll_interval_s=poll_interval_s)

    def wait_for_element(self, target: TargetSpec, *, timeout_s: float) -> WaitOutcome:
        return self.waits.wait_for_element(
            target, timeout_s=timeout_s, provider=self.backend.observe)

    def verify_file(self, path: str | Path, **kwargs: Any) -> FileVerificationResult:
        return verify_file(path, **kwargs)

    # ── parada ───────────────────────────────────────────────────────────
    def stop(self) -> None:
        self.backend.stop()
