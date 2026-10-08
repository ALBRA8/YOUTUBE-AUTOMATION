"""
HANDS · Clean-Room Test (§42).

Demuestra que HANDS se inicializa y opera ÚNICAMENTE con:

  * código del repo (paquete hands, stdlib),
  * configuración declarada (HandsConfig + allowlists como datos),
  * mocks/fixtures (MockEnvironment — sin PC real, sin red, sin Flow real),
  * permisos declarados,
  * workspace aislado en un directorio temporal.

Sin hacks manuales ocultos: cada paso queda registrado como check con su
evidencia. El guion ejercita: arranque declarativo → sesión de escritorio
(abrir/enfocar/click semántico/teclear/verificar/copiar/capturar) → sonda de
bloqueo (app no autorizada ⇒ BLOCKED) → ciclo Flow completo con idempotencia
→ sonda de caos (espera con timeout) → kill switch (STOPPED + locks libres)
→ auditabilidad (evidencia hasheada + sesión persistida + audit trail) →
integración NOT CONNECTED.

Uso:  python3 -m services.hands cleanroom [--json]
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .contracts import BlockedError, ErrorCode, State, TargetSpec
from .future_integration import INTEGRATION_STATUS
from .mocks import MockEnvironment
from .runtime import HandsConfig, HandsRuntime


def run_cleanroom(*, verbose: bool = True) -> dict[str, Any]:
    """Ejecuta el guion clean-room completo y devuelve el informe."""
    checks: list[dict[str, Any]] = []

    def check(cid: str, ok: bool, detail: str = "") -> bool:
        checks.append({"id": cid, "ok": bool(ok), "detail": detail})
        if verbose:
            print(f"  {'✓' if ok else '✗'} {cid}{': ' + detail if detail else ''}")
        return bool(ok)

    with tempfile.TemporaryDirectory(prefix="hands_cleanroom_") as tmp:
        # ── 1. arranque 100% declarativo ─────────────────────────────────
        config = HandsConfig.from_dict({
            "workspace_root": str(Path(tmp) / "hands_ws"),
            "permissions": {
                "applications": ["notepad-mock", "files-mock"],
                "domains": ["flow.google.com", "labs.google.com"],
                "browser_urls": ["https://flow.google.com/*"],
                "commands": [],
                "filesystem_roots": [str(Path(tmp) / "hands_ws")],
            },
            "desktop_backend": "mock",
            "flow_driver": "mock",
            "timeouts": {"wait_s": 5.0, "action_s": 10.0},
        })
        runtime = HandsRuntime(config)
        boot_ok = (runtime.workspace.root.exists()
                   and runtime.status()["integration_status"] == "NOT CONNECTED")
        check("CR-01 arranque declarativo", boot_ok,
              f"workspace={runtime.workspace.root.name}")

        # ── 2. sesión de escritorio completa (§13) ───────────────────────
        with runtime.session(operator="desktop", locks=("desktop",)) as bundle:
            check("CR-02 sesión+lock", bundle.session.current_state.value == "RUNNING"
                  and runtime.locks.is_held("desktop"),
                  f"session={bundle.session_id}")

            r_open = bundle.desktop.open_app("notepad-mock")
            check("CR-03 OPEN app", r_open.status is State.COMPLETED,
                  f"window={r_open.result.get('observation_after', {}).get('window')}")

            obs = bundle.desktop.observe()
            target_prompt = TargetSpec(semantic="notepad-mock.prompt_input")
            r_click = bundle.desktop.click(target_prompt)
            check("CR-04 CLICK por target semántico (§8)",
                  r_click.status is State.COMPLETED
                  and r_click.result.get("target_match", {}).get("strategy") == "semantic")

            r_type = bundle.desktop.type_text(target_prompt, "hola desde HANDS")
            check("CR-05 TYPE + verify",
                  r_type.status is State.COMPLETED
                  and r_type.verification.get("verdict") in ("PASS", "NOT_SPECIFIED"))

            r_copy = bundle.desktop.copy_file(
                bundle.runtime.workspace.path_for("workspace", "origen.txt").name
                if False else str(_seed(bundle, "origen.txt")),
                str(bundle.runtime.workspace.path_for("workspace", "copia.txt")))
            check("CR-06 COPY dentro del workspace (§18)",
                  r_copy.status is State.COMPLETED)

            capture = bundle.desktop.capture_to_evidence(bundle.evidence)
            check("CR-07 CAPTURE a evidencia (§22)",
                  capture.get("screenshot") is not None
                  or capture.get("note") is not None,
                  "screenshot" if capture.get("screenshot") else "sin captura (honesto)")

            # ── sonda de bloqueo: app fuera de allowlist ⇒ BLOCKED (§16) ──
            r_denied = bundle.desktop.open_app("finder-prohibido")
            check("CR-08 deny-by-default ⇒ BLOCKED",
                  r_denied.status is State.BLOCKED
                  and r_denied.errors
                  and r_denied.errors[0]["code"] == ErrorCode.PERMISSION_DENIED.value)

            # ── sonda de caos: ventana fantasma ⇒ TIMEOUT, sesión sigue (§33) ─
            outcome = bundle.desktop.wait_for_window("fantasma-inexistente",
                                                     timeout_s=2.0)
            check("CR-09 wait con timeout (§10) — no infinito",
                  outcome.ok is False and outcome.error
                  and outcome.error["code"] == "TIMEOUT",
                  f"polls={outcome.polls}")

        # ── 3. ciclo Flow completo con mock driver (§14) ─────────────────
        with runtime.session(operator="flow", locks=("flow",)) as bundle:
            from .flow_operator import FlowJobSpec
            job = FlowJobSpec(kind="image", project_id="cr-project",
                              scene_number=1, part=1,
                              prompt="PROMPT EXTERNO DE PRUEBA (viene de la capa creativa)")
            steps = [
                bundle.flow.open_flow(),
                bundle.flow.open_project("cr-project"),
                bundle.flow.set_prompt(job),
                bundle.flow.set_configuration({"estilo": "mock"}),
                bundle.flow.start_generation(),
            ]
            names = [FlowOpName(i) for i in range(len(steps))]
            ok_chain = all(s.status is State.COMPLETED for s in steps)
            check("CR-10 OPEN_FLOW→…→START_GENERATION", ok_chain,
                  ",".join(f"{n}:{s.status.value}" for n, s in zip(names, steps)))

            r_wait = bundle.flow.wait_generation(steps[4].result["handle"])
            check("CR-11 WAIT_GENERATION", r_wait.status is State.COMPLETED)

            r_dl = bundle.flow.download_result(steps[4].result["handle"],
                                               dest_name="cr_result.png")
            check("CR-12 DOWNLOAD_RESULT + verificación de medios (§23)",
                  r_dl.status is State.COMPLETED
                  and r_dl.verification.get("verdict") == "PASS")

            r_dl2 = bundle.flow.download_result(steps[4].result["handle"],
                                                dest_name="cr_result.png")
            check("CR-13 idempotencia §26 (re-descarga evitada)",
                  r_dl2.status is State.COMPLETED
                  and bool(r_dl2.result.get("skipped")))

        # ── 4. kill switch (§27) ─────────────────────────────────────────
        runtime.stop("clean-room: prueba de parada segura", source="cleanroom")
        final_status = None
        with runtime.session(operator="desktop", locks=("desktop",)) as bundle:
            r_after = bundle.desktop.open_app("notepad-mock")
        final_status = bundle.session.final_status
        check("CR-14 kill switch ⇒ STOPPED",
              r_after.status is State.STOPPED and final_status == "STOPPED",
              f"final_status={final_status}")
        check("CR-15 locks liberados tras STOPPED",
              not runtime.locks.is_held("desktop"))

        # ── 5. auditabilidad (§19/§21/§31) ───────────────────────────────
        ev_files = list(runtime.workspace.evidence.glob("evidence_*.jsonl"))
        check("CR-16 evidencia persistida", len(ev_files) >= 2,
              f"{len(ev_files)} JSONL de evidencia")
        sessions = runtime.sessions.list_sessions()
        reloaded = runtime.sessions.get(sessions[0]) if sessions else None
        check("CR-17 sesión auditable posterior (§19)",
              reloaded is not None and reloaded.final_status is not None
              and reloaded.permissions_snapshot,
              f"{len(sessions)} sesiones")
        audit_entries = runtime.audit.read_all()
        check("CR-18 audit trail operacional (§31)", len(audit_entries) >= 8,
              f"{len(audit_entries)} entradas")

        # ── 6. integración NOT CONNECTED (§36/§37) ───────────────────────
        from .future_integration import NotConnectedAdapter
        try:
            NotConnectedAdapter().submit({"request_id": "x", "requested_by": "t",
                                          "operations": [], "created_at": "now"})
            not_connected = False
        except BlockedError as err:
            not_connected = err.details.get("integration_status") == "NOT CONNECTED"
        check("CR-19 YOUTUBE-AUTOMATION NOT CONNECTED", not_connected,
              INTEGRATION_STATUS)

    passed = sum(1 for c in checks if c["ok"])
    report = {
        "suite": "HANDS CLEAN-ROOM (§42)",
        "ok": passed == len(checks),
        "summary": f"{passed}/{len(checks)} checks PASS",
        "checks": checks,
    }
    if verbose:
        print(f"\nHANDS CLEAN-ROOM: {'PASS' if report['ok'] else 'FAIL'} "
              f"({report['summary']})")
    return report


def FlowOpName(index: int) -> str:
    return ["OPEN_FLOW", "OPEN_PROJECT", "SET_PROMPT", "SET_CONFIGURATION",
            "START_GENERATION"][index]


def _seed(bundle, name: str) -> str:
    path = bundle.runtime.workspace.path_for("workspace", name)
    if not path.exists():
        path.write_text("contenido semilla clean-room")
    return str(path)
