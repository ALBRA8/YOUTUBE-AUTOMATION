#!/usr/bin/env python3
"""Batería HANDS CHAOS V1.0 — FAILURE + CHAOS de la capa aislada (§33).

Cubre: timeout de espera y de driver HTTP, target que desaparece y UI que
cambia a mitad de flujo (fallback de estrategia §8), permisos denegados por
categoría (aplicación/dominio/comando/filesystem), BLOCKED por lock ocupado,
backend detenido y bridge deshabilitado, recovery agotado (RECOVERY_FAILED,
nunca infinito), disciplina UNKNOWN (nunca se promueve a COMPLETED; la
sesión UNKNOWN cierra FAILED honesta §11), kill switch a mitad de sesión
(STOPPED + locks liberados + evidencia preservada), fichero que tarda con
reloj virtual, descarga fallida del driver, file lock con dueño muerto
(staleness) y evidencia consultable tras el caos.

Uso:  cd yt_automation_v2 && python3 tests/test_hands_chaos.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services.hands import (                                # noqa: E402
    ActionSpec, BlockedError, ErrorCode, EvidenceLayer, FakeClock, HandsError,
    HandsRuntime, KillSwitch, LockManager, MockDesktopBackend, MockEnvironment,
    Op, RecoveryEngine, RecoveryPolicy, State, StoppedError, TargetSpec,
    VerificationEngine, Verdict, WaitSpec, verify_file,
)
from services.hands.contracts import ElementRef             # noqa: E402
from services.hands.flow_operator import (ExtensionBridgeDriver,   # noqa: E402
                                          FlowJobSpec)
from services.hands.locks import FileLock                   # noqa: E402
from services.hands.recovery import RecoveryFailedError     # noqa: E402
from services.hands.sessions import SessionManager          # noqa: E402
from services.hands.waits import WaitEngine                 # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def expect_error(fn, code: ErrorCode) -> bool:
    try:
        fn()
        return False
    except HandsError as err:
        return err.code is code


class _TimeoutHttp:
    """Transporte HTTP que simula un timeout de red (caos §33)."""

    def request(self, method, url, *, headers, body, timeout_s):
        raise TimeoutError("conexión colgada (caos simulado)")


# ══ 1. TIMEOUTS (§10/§25/§33) ════════════════════════════════════════════
print("── 1. Timeouts: espera, driver HTTP y validación")
_fc = FakeClock()
_we = WaitEngine(_fc)
_out = _we.wait_until(lambda o: False, timeout_s=3.0, poll_interval_s=1.0)
check("wait vencido: ok=False + error TIMEOUT + polls contados",
      _out.ok is False and _out.error["code"] == "TIMEOUT"
      and _out.polls == 4 and _out.elapsed_s >= 3.0)

check("driver HTTP timeout ⇒ ACTION_FAILED (transporte inyectado)",
      expect_error(lambda: ExtensionBridgeDriver(
          base_url="http://127.0.0.1:1", enabled=True,
          http=_TimeoutHttp(), timeout_s=0.5).poll({"handle_id": "x"}),
          ErrorCode.ACTION_FAILED))

try:
    from services.hands.clock import TimeoutsConfig
    TimeoutsConfig(poll_interval_s=0).validate()
    check("config con poll=0 rechazada", False)
except HandsError:
    check("config con poll=0 rechazada", True)

# ══ 2. TARGET DESAPARECE + UI CAMBIA (§33) ═══════════════════════════════
print("── 2. Target desaparece / UI cambia a mitad de flujo")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos1")
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        h.desktop.open_app("notepad-mock")
        env.chaos_ui_change(lambda els: [setattr(el, "semantic", None)
                                         for el in els
                                         if el.semantic == "notepad-mock.prompt_input"])
        r1 = h.desktop.click(TargetSpec(semantic="notepad-mock.prompt_input",
                                        accessibility="role=textarea name=prompt"))
        check("UI cambia: semantic muere pero a11y responde (fallback §8)",
              r1.status is State.COMPLETED
              and r1.result.get("target_match", {}).get("strategy")
              == "accessibility")
        env.chaos_ui_change(lambda els: [setattr(el, "semantic", None)
                                         for el in els])
        r2 = h.desktop.click(TargetSpec(semantic="notepad-mock.send_button"))
        check("todas las estrategias muertas ⇒ FAILED TARGET_NOT_FOUND",
              r2.status is State.FAILED
              and r2.errors[0]["code"] == "TARGET_NOT_FOUND"
              and len(r2.errors[0]["details"].get("tried", [])) >= 1)
        _recs = h.evidence.query(result="FAILED")
        check("fallos quedan en evidencia consultable (§21)", len(_recs) >= 1)

# ══ 3. PERMISOS DENEGADOS POR CATEGORÍA (§16/§28) ════════════════════════
print("── 3. Permission denied en las 5 categorías")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos2",
                          allowlist={"applications": [], "domains": [],
                                     "commands": [], "filesystem_roots": [],
                                     "browser_urls": []})
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        check("aplicación no autorizada ⇒ BLOCKED",
              h.desktop.open_app("cualquiera").status is State.BLOCKED)
        check("dominio Flow no autorizado ⇒ flow BLOCKED",
              h.flow.open_flow().status is State.BLOCKED)
        check("comando sin allowlist ⇒ BLOCKED",
              h.desktop.execute_allowed(["ffmpeg", "-version"]).status
              is State.BLOCKED)
        r_fs = h.engine.execute(ActionSpec(
            name=Op.RENAME.value,
            params={"src": "/etc/hosts", "dst": "/tmp/hosts"}), h.desktop.backend)
        check("filesystem fuera de raíces ⇒ BLOCKED", r_fs.status is State.BLOCKED)
    _st = env.runtime.status()
    check("deny-by-default no deja locks huérfanos ni estados corruptos",
          _st["locks"] == {})

# ══ 4. BLOCKED: lock ocupado, backend parado, bridge apagado (§20/§27/§37) ═
print("── 4. Estados BLOCKED honestos")
_lm = LockManager()
_lm.acquire("browser", owner="otro", timeout_s=0.1)
check("lock browser ocupado ⇒ BLOCKED", expect_error(
    lambda: _lm.acquire("browser", owner="yo", timeout_s=0.05),
    ErrorCode.BLOCKED))
_lm.release_all("otro")

with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos3")
    env.desktop_mock.stop()
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        r = h.desktop.open_app("notepad-mock")
        check("backend detenido ⇒ acción BLOCKED",
              r.status is State.BLOCKED
              and r.errors[0]["code"] == "BLOCKED")
    check("bridge deshabilitado ⇒ TODO el flow BLOCKED (§37)",
          expect_error(lambda: ExtensionBridgeDriver(
              base_url="http://127.0.0.1:1").open_session(),
          ErrorCode.BLOCKED))

# ══ 5. RECOVERY AGOTADO (§24) ════════════════════════════════════════════
print("── 5. Recovery agotado: nunca infinito")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos4")
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        from services.hands.contracts import ActionFailedError
        _orig_perform = env.desktop_mock.perform

        def _always_fail(name, match, params):
            if name == Op.OPEN.value:
                raise ActionFailedError("siempre falla")
            return _orig_perform(name, match, params)

        env.desktop_mock.perform = _always_fail
        r = h.desktop.open_app("notepad-mock",
                               recovery={"max_retries": 3, "backoff_s": 0.1})
        check("agotados los reintentos ⇒ FAILED RECOVERY_FAILED",
              r.status is State.FAILED
              and r.errors[0]["code"] == "RECOVERY_FAILED"
              and len(r.errors[0]["details"].get("attempts", [])) == 4)
        check("recovery_failed con historial auditable de intentos",
              all("ok" in a for a in r.errors[0]["details"]["attempts"]))

_intentos = []
def _siempre_timeout():
    _intentos.append(1)
    from services.hands.contracts import HandsTimeoutError
    raise HandsTimeoutError("lento")
try:
    RecoveryEngine(FakeClock()).run(_siempre_timeout,
                                    RecoveryPolicy(max_retries=1))
except RecoveryFailedError as err:
    check("TIMEOUT reintentable se agota ⇒ RECOVERY_FAILED con 2 intentos",
          len(_intentos) == 2 and len(err.details["attempts"]) == 2)

# ══ 6. DISCIPLINA UNKNOWN (§11/§12) ══════════════════════════════════════
print("── 6. UNKNOWN nunca se promueve a COMPLETED")
_v = VerificationEngine()
_r = _v.verify(bool, None)     # callable + observación ausente
check("observación ausente ⇒ veredicto UNKNOWN",
      _r.verdict is Verdict.UNKNOWN)
from services.hands.contracts import (                       # noqa: E402
    check_transition, can_transition,
)
check("UNKNOWN→COMPLETED prohibida por máquina de estados",
      not can_transition(State.UNKNOWN, State.COMPLETED))

with tempfile.TemporaryDirectory() as tmp:
    _mgr = SessionManager(Path(tmp) / "s", Path(tmp) / "e")
    _sess, _ev = _mgr.start("desktop", {})
    _sess.set_state(State.UNKNOWN)           # RUNNING→UNKNOWN válido
    _sess.close(final_status="COMPLETED")
    check("sesión UNKNOWN cerrada como COMPLETED ⇒ FAILED honesta (§11)",
          _sess.final_status == "FAILED"
          and "close_state_conflict" in _sess.meta)

# ══ 7. KILL SWITCH A MITAD DE SESIÓN (§27) ═══════════════════════════════
print("── 7. Kill switch: STOPPED con evidencia preservada")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos5")
    _ks_gatillo = {"on": False}

    def _provider_con_killswitch():
        if _ks_gatillo["on"]:
            env.runtime.killswitch.engage("caos: parada a mitad de espera")
        return env.desktop_mock.observe()

    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        h.desktop.open_app("notepad-mock")
        _ev_antes = len(h.evidence.all_records())
        _ks_gatillo["on"] = True          # el provider activará el kill switch
        try:
            _we2 = WaitEngine(env.clock, killswitch=env.runtime.killswitch)
            _we2.wait_until(lambda o: False, timeout_s=60.0,
                            provider=_provider_con_killswitch)
            _stopeado = False
        except StoppedError:
            _stopeado = True
        check("kill switch a mitad de espera ⇒ StoppedError inmediato",
              _stopeado)
        r = h.desktop.open_app("files-mock")
        check("acción tras kill switch ⇒ STOPPED",
              r.status is State.STOPPED)
    _sid = h.session_id
    _recargada = env.runtime.sessions.get(_sid)
    check("sesión cerrada STOPPED con locks liberados (§27)",
          _recargada.final_status == "STOPPED"
          and not env.runtime.locks.is_held("desktop"))
    check("evidencia preservada tras kill (append-only)",
          len(env.runtime.sessions.get(_sid).actions) >= 2
          and len(EvidenceLayer(env.runtime.workspace.evidence, _sid)
                  .all_records()) >= _ev_antes)

# ══ 8. FICHERO QUE TARDA + DESCARGA FALLIDA (§33) ════════════════════════
print("── 8. Fichero lento (reloj virtual) y descarga fallida")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos6")
    _lento = Path(tmp) / "lento.png"
    env.chaos_delayed_file(_lento, delay_s=10.0, content=b"\x89PNG\r\n\x1a\nx")

    def _provider_materializa():
        env.desktop_mock.materialize_due_files()   # el entorno avanza con el reloj
        return env.desktop_mock.observe()

    _we3 = WaitEngine(env.clock, killswitch=env.runtime.killswitch)
    _out = _we3.wait_for_file(_lento, timeout_s=5.0)
    check("fichero tarda más que el timeout ⇒ TIMEOUT",
          _out.ok is False and _out.error["code"] == "TIMEOUT")
    _out2 = _we3.wait(
        WaitSpec("WAIT_FOR_FILE", 20.0, 1.0, {"path": str(_lento), "min_size": 2}),
        provider=_provider_materializa)
    check("con margen suficiente el fichero llega ⇒ ok (reloj virtual)",
          _out2.ok and _lento.is_file()
          and verify_file(_lento, media_kind="png").verdict is Verdict.PASS)

with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos7")
    with env.runtime.session(operator="flow", locks=("flow",)) as h:
        f = h.flow
        f.open_flow()
        job = FlowJobSpec(kind="video", project_id="p", scene_number=3,
                          prompt="PROMPT EXTERNO")
        f.set_prompt(job)
        r_start = f.start_generation()
        _handle = dict(r_start.result["handle"])
        _handle["_job"] = job.to_dict()
        f.wait_generation(_handle)
        f.driver.fetch = lambda handle: None      # CAOS: driver no entrega bytes
        r_dl = f.download_result(_handle, dest_name="novie.mp4")
        check("descarga sin bytes ⇒ FAILED honesto (no se inventa asset)",
              r_dl.status is State.FAILED
              and r_dl.errors[0]["code"] == "ACTION_FAILED")

# ══ 9. FILE LOCK CON DUEÑO MUERTO (§20) ══════════════════════════════════
print("── 9. File lock: caducidad de dueño muerto")
with tempfile.TemporaryDirectory() as tmp:
    _lock_path = Path(tmp) / "entorno.lock"
    _lock_path.write_text(json.dumps({"owner": "proceso-muerto"}))
    _viejo = time.time() - 3600
    os.utime(_lock_path, (_viejo, _viejo))
    _fl = FileLock(_lock_path, stale_s=60)
    _fh = _fl.acquire("nuevo-proceso", timeout_s=1.0)
    check("lock de dueño muerto se reclaima tras stale_s", _fl.is_locked())
    _fh.release()
    check("liberación limpia tras reclaim", not _fl.is_locked())

# ══ 10. AUDITABILIDAD TRAS EL CAOS (§19/§21/§31) ═════════════════════════
print("── 10. Todo el caos queda auditable")
with tempfile.TemporaryDirectory() as tmp:
    env = MockEnvironment(root=Path(tmp) / "chaos8")
    with env.runtime.session(operator="desktop", locks=("desktop",)) as h:
        h.desktop.open_app("no-permitida")            # BLOCKED
        h.desktop.open_app("notepad-mock")            # OK
        env.chaos_window_disappears("notepad-mock — Ventana principal")
        h.desktop.click(TargetSpec(semantic="notepad-mock.send_button"))  # FAILED
    _recs = h.evidence.all_records()
    _resultados = {r.get("result") for r in _recs}
    check("evidencia registra BLOCKED + COMPLETED + FAILED de la misma sesión",
          {"BLOCKED", "COMPLETED", "FAILED"} <= _resultados,
          str(_resultados))
    _man = h.evidence.manifest()
    check("manifiesto con sha256 del JSONL de evidencia",
          len(_man["sha256"]) == 64 and _man["records"] >= 3)
    _audit = env.runtime.audit.read_all()
    check("audit trail reconstruye qué ocurrió y cuándo (§31)",
          any(a["event"] == "action_start" for a in _audit)
          and any(a["event"] == "session_close" for a in _audit))
    _rec = env.runtime.sessions.get(h.session_id)
    check("sesión recargable con actions y errores completos",
          len(_rec.actions) >= 3 and _rec.permissions_snapshot)

# ══ RESUMEN ══════════════════════════════════════════════════════════════
print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
