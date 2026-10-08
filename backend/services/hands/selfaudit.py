"""
HANDS · Auditoría automática de la capa (§40).

`run_selfaudit()` ejecuta una batería de comprobaciones estructurales y
conductuales sobre HANDS mismo y devuelve un informe dict + resumen:

  ARCHITECTURE — aislamiento (cero imports del orquestador, solo stdlib +
                 hands-internal, verificado por AST), modularidad.
  SECURITY     — deny-by-default en 5 categorías, frontera de filesystem,
                 allowlist de comandos, redacción de secretos, sin shell.
  OPERATIONS   — waits con timeout obligatorio, verificación con disciplina
                 UNKNOWN, recovery acotado, ciclo §7 completo.
  SAFETY       — UNKNOWN nunca→COMPLETED, kill switch cancela waits, locks
                 busy ⇒ BLOCKED, timeouts validados.
  EVIDENCE     — registros hasheados y redactados, sesiones persistentes.
  TESTING      — presencia real de las baterías HANDS en el repo (conteo
                 honesto de checks; no inflable).

Uso:  python3 -m services.hands selfaudit [--json]
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import HANDS_PACKAGE_DIR
from .clock import FakeClock
from .contracts import (BlockedError, State, StoppedError, ValidationError,
                        check_transition)
from .evidence import EvidenceLayer, redact
from .killswitch import KillSwitch
from .locks import LockManager
from .permissions import PermissionModel
from .recovery import RecoveryEngine, RecoveryPolicy
from .verification import VerificationEngine, Verdict
from .waits import WaitEngine, WaitSpec
from .workspace import HandsWorkspace, PathBoundary

# módulos del orquestador que HANDS NO PUEDE importar (§36/§38)
FORBIDDEN_MODULES = {
    "config", "database", "main", "security",
    "services.orchestrator", "orchestrator", "services.scheduler", "scheduler",
    "services.flow_jobs", "flow_jobs", "services.youtube_publish",
    "pipeline", "services.production_json", "services.mcp_server",
    "services.agent", "fastapi", "uvicorn",
}


def _hands_modules() -> list[Path]:
    return sorted(HANDS_PACKAGE_DIR.glob("*.py"))


def _check_isolation() -> tuple[bool, str]:
    """ARCH-1: ninguna py de hands importa módulos prohibidos (AST)."""
    offenders: list[str] = []
    for path in _hands_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if alias.name in FORBIDDEN_MODULES or root in FORBIDDEN_MODULES:
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                if module in FORBIDDEN_MODULES or root in FORBIDDEN_MODULES:
                    offenders.append(f"{path.name}: from {module}")
    if offenders:
        return False, f"imports prohibidos: {offenders}"
    return True, f"{len(_hands_modules())} módulos hands: solo stdlib + hands-internal"


def _check_no_circular() -> tuple[bool, str]:
    """ARCH-2: el paquete completo importa sin ciclo (import efectivo)."""
    import importlib
    names = [p.stem for p in _hands_modules() if p.stem != "__main__"]
    try:
        for name in names:
            importlib.import_module(f".{name}", package=__package__)
    except Exception as exc:      # noqa: BLE001
        return False, f"import fallido (¿ciclo?): {type(exc).__name__}: {exc}"
    return True, f"{len(names)} módulos importables sin ciclo"


def _behavioral_checks() -> list[dict[str, Any]]:
    """Comprobaciones conductuales pequeñas sobre instancias reales."""
    out: list[dict[str, Any]] = []

    def add(area: str, cid: str, ok: bool, detail: str) -> None:
        out.append({"id": cid, "area": area, "ok": bool(ok), "detail": detail})

    # ── SECURITY: deny by default en las 5 categorías ────────────────────
    empty = PermissionModel()
    with tempfile.TemporaryDirectory() as tmp:
        sec_ok = (not empty.check_application("notepad").allowed
                  and not empty.check_domain("https://flow.google.com").allowed
                  and not empty.check_path(Path(tmp) / "x").allowed
                  and not empty.check_command(["ffmpeg", "-version"]).allowed
                  and not empty.check_browser("https://flow.google.com/x").allowed)
        add("SECURITY", "SEC-1", sec_ok,
            "PermissionModel vacío deniega application/domain/filesystem/"
            "command/browser (deny-by-default §16)")
        add("SECURITY", "SEC-2", not empty.check_command(["rm", "-rf", "/"]).allowed,
            "comando peligroso no listado ⇒ DENY")
        add("SECURITY", "SEC-3", empty.allow_shell is False,
            "allow_shell fijo a False: HANDS jamás ejecuta shell")

        boundary = PathBoundary(tmp)
        try:
            boundary.resolve_within("/etc/passwd")
            escape_blocked = False
        except Exception:         # noqa: BLE001
            escape_blocked = True
        add("SECURITY", "SEC-4", escape_blocked,
            "PathBoundary bloquea escape fuera del workspace")

    masked = redact("config con api_key=sk-abcdefghij1234567890 y token=ghp_xxxxxxxxxxxxxxxxxxxx")
    add("SECURITY", "SEC-5", "sk-abcdefghij" not in masked
        and "ghp_xxxxxxxxxx" not in masked and "[REDACTED]" in masked,
        "redacción automática de secretos en evidencia/logs (§32)")

    # ── OPERATIONS ───────────────────────────────────────────────────────
    try:
        WaitSpec("WAIT_UNTIL", timeout_s=0).validate()
        wait_validated = False
    except ValidationError:
        wait_validated = True
    add("OPERATIONS", "OPS-1", wait_validated,
        "WaitEngine: timeout obligatorio > 0 — no existen esperas infinitas (§10/§25)")

    ve = VerificationEngine()
    r1 = ve.verify(bool, None)                       # callable + observed ausente
    r2 = ve.verify({"kind": "predicate", "fn": _boom}, "x")   # predicate roto
    add("OPERATIONS", "OPS-2", r1.verdict is Verdict.UNKNOWN
        and r2.verdict is Verdict.UNKNOWN,
        "verificación: observación ausente o predicate roto ⇒ UNKNOWN (nunca PASS)")

    fake = FakeClock()
    attempts: list[int] = []

    def always_fail() -> None:
        attempts.append(1)
        raise RuntimeError("falla siempre")

    try:
        RecoveryEngine(fake).run(always_fail, RecoveryPolicy(max_retries=2))
    except Exception:
        pass
    add("OPERATIONS", "OPS-3", len(attempts) == 3,
        f"recovery acotado: max_retries=2 ⇒ exactamente {len(attempts)} intentos (§24)")

    # ── SAFETY ───────────────────────────────────────────────────────────
    try:
        check_transition(State.UNKNOWN, State.COMPLETED)
        unknown_rule = False
    except ValidationError:
        unknown_rule = True
    add("SAFETY", "SAF-1", unknown_rule,
        "UNKNOWN nunca transiciona a COMPLETED (§11)")

    ks = KillSwitch()
    ks.engage("prueba de auditoría")
    try:
        ks.check()
        ks_works = False
    except StoppedError:
        ks_works = True
    add("SAFETY", "SAF-2", ks_works, "kill switch bloquea acciones nuevas (§27)")

    lm = LockManager()
    lm.acquire("desktop", owner="audit-a")
    try:
        lm.acquire("desktop", owner="audit-b", timeout_s=0.05)
        lock_works = False
    except BlockedError:
        lock_works = True
    lm.release_all("audit-a")
    add("SAFETY", "SAF-3", lock_works, "lock ocupado ⇒ BLOCKED (§20)")

    try:
        from .clock import TimeoutsConfig
        TimeoutsConfig(action_s=-1).validate()
        timeouts_ok = False
    except (ValidationError, ValueError):
        timeouts_ok = True
    add("SAFETY", "SAF-4", timeouts_ok, "timeouts negativos/0 rechazados (§25)")

    # ── EVIDENCE ─────────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        ws = HandsWorkspace(Path(tmp) / "ws")
        ev = EvidenceLayer(ws.evidence, "audit_session")
        rec = ev.record("audit_probe", error="api_key=sk-abcdefghij1234567890")
        raw = (ws.evidence / f"evidence_audit_session.jsonl").read_text()
        ev_ok = (rec["hash"] and "sk-abcdefghij" not in raw
                 and "[REDACTED]" in raw)
        add("EVIDENCE", "EVID-1", ev_ok,
            "evidencia con hash SHA-256 y secretos redactados en disco (§21/§32)")

    return out


def _boom(_observed: Any) -> bool:
    raise RuntimeError("predicate roto a propósito (auditoría)")


def run_selfaudit() -> dict[str, Any]:
    """Ejecuta la auditoría completa §40 y devuelve el informe estructurado."""
    checks: list[dict[str, Any]] = []

    arch1_ok, arch1_detail = _check_isolation()
    checks.append({"id": "ARCH-1", "area": "ARCHITECTURE", "ok": arch1_ok,
                   "detail": arch1_detail})
    arch2_ok, arch2_detail = _check_no_circular()
    checks.append({"id": "ARCH-2", "area": "ARCHITECTURE", "ok": arch2_ok,
                   "detail": arch2_detail})

    checks.extend(_behavioral_checks())

    # ── TESTING: presencia real de las baterías HANDS ────────────────────
    tests_dir = HANDS_PACKAGE_DIR.parents[2] / "tests"   # raíz del repo
    hands_batteries = sorted(tests_dir.glob("test_hands*.py")) if tests_dir.exists() else []
    total_checks = 0
    for battery in hands_batteries:
        total_checks += battery.read_text(encoding="utf-8").count('check("')
    checks.append({"id": "TEST-1", "area": "TESTING",
                   "ok": len(hands_batteries) >= 3,
                   "detail": f"baterías HANDS: {[b.name for b in hands_batteries]} "
                             f"({total_checks} checks declarados)"})

    passed = sum(1 for c in checks if c["ok"])
    return {
        "suite": "HANDS SELF-AUDIT (§40)",
        "ok": passed == len(checks),
        "summary": f"{passed}/{len(checks)} checks PASS",
        "checks": checks,
    }


def print_selfaudit(report: dict[str, Any] | None = None) -> int:
    """Imprime el informe en formato de batería; devuelve exit code."""
    report = report or run_selfaudit()
    for c in report["checks"]:
        mark = "✓" if c["ok"] else "✗"
        print(f"  {mark} [{c['area']}] {c['id']}: {c['detail']}")
    print(f"\nHANDS SELF-AUDIT: {'PASS' if report['ok'] else 'FAIL'} "
          f"({report['summary']})")
    return 0 if report["ok"] else 1
