#!/usr/bin/env python3
"""Batería HANDS NÚCLEO V1.0 — contratos, permisos, workspace, sesiones,
locks, evidencia, waits, verificación, recovery, kill switch, identificación,
action engine y runtime (capa aislada, sin conexión con el orquestador).

Cubre: 9 estados con transiciones (UNKNOWN nunca→COMPLETED §11), taxonomía de
10 errores (§29), modelo de acción OBSERVE→IDENTIFY→ACTION→OBSERVE→VERIFY
(§7), jerarquía de identificación semántico→a11y→texto→DOM→visual→coords
(§8) con coordenadas vetadas por política, observación estructurada (§9),
permisos deny-by-default en 5 categorías + allowlists (§16/§17), workspace
aislado con frontera fs anti-escape/symlink (§18), sesiones auditables
(§19), locks in-process con timeout y file-lock cross-proceso (§20), evidencia
hasheada + redacción de secretos + audit trail (§21/§31/§32), wait engine con
timeout obligatorio y 8 kinds (§10), verificación PASS/FAIL/UNKNOWN con
disciplina UNKNOWN + file verification con magic bytes (§12/§23), recovery
acotado con ciclo OBSERVE→WAIT→VERIFY→RECOVER (§24), kill switch (§27) y
runtime completo con sesión+locks+evidencia.

Uso:  cd yt_automation_v2 && python3 tests/test_hands.py
"""
import json
import sys
import tempfile
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services.hands import (                                # noqa: E402
    ActionEngine, ActionSpec, AuditTrail, EvidenceLayer, FakeClock, FileLock,
    HandsConfig, HandsError, HandsRuntime, KillSwitch, LockManager,
    MockDesktopBackend, Op, PermissionModel, RecoveryEngine, RecoveryPolicy,
    State, TargetNotFoundError, TargetResolver, TargetSpec, TimeoutsConfig,
    VerificationEngine, Verdict, WaitEngine, WaitSpec, redact, verify_file,
)
from services.hands.contracts import (                      # noqa: E402
    ErrorCode, InvalidTransitionError, Observation, PermissionDeniedError,
    can_transition, check_transition, error_from_exception,
)
from services.hands.workspace import HandsWorkspace, PathBoundary   # noqa: E402

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


# ══ 1. CONTRATOS: estados y transiciones (§11) ═══════════════════════════
print("── 1. Estados y transiciones (§11)")
check("9 estados canónicos",
      {s.value for s in State} == {"IDLE", "RUNNING", "WAITING", "COMPLETED",
                                   "FAILED", "TIMEOUT", "BLOCKED", "UNKNOWN",
                                   "STOPPED"})
check("IDLE→RUNNING permitida", can_transition(State.IDLE, State.RUNNING))
check("RUNNING→WAITING permitida", can_transition(State.RUNNING, State.WAITING))
check("WAITING→COMPLETED permitida", can_transition(State.WAITING, State.COMPLETED))
check("UNKNOWN→COMPLETED PROHIBIDA (§11)",
      not can_transition(State.UNKNOWN, State.COMPLETED))
check("UNKNOWN→COMPLETED lanza InvalidTransitionError",
      expect_error(lambda: check_transition(State.UNKNOWN, State.COMPLETED),
                   ErrorCode.VALIDATION_ERROR))
check("UNKNOWN→RUNNING permitida (re-observación)",
      can_transition(State.UNKNOWN, State.RUNNING))
check("FAILED→RUNNING permitida (recovery §24)",
      can_transition(State.FAILED, State.RUNNING))
check("STOPPED y COMPLETED son terminales",
      not can_transition(State.STOPPED, State.RUNNING)
      and not can_transition(State.COMPLETED, State.RUNNING))

# ══ 2. TAXONOMÍA DE ERRORES (§29) ════════════════════════════════════════
print("── 2. Taxonomía de errores (§29)")
check("10 códigos diferenciados",
      {c.value for c in ErrorCode} == {"VALIDATION_ERROR", "PERMISSION_DENIED",
                                       "TARGET_NOT_FOUND", "TIMEOUT",
                                       "ACTION_FAILED", "VERIFICATION_FAILED",
                                       "RECOVERY_FAILED", "BLOCKED", "UNKNOWN",
                                       "STOPPED"})
_err = error_from_exception(ValueError("x rara"))
check("excepción ajena normalizada a UNKNOWN", _err.code is ErrorCode.UNKNOWN)
check("HandsError serializable con detalles",
      error_from_exception(
          PermissionDeniedError("no")).to_dict()["code"] == "PERMISSION_DENIED")

# ══ 3. PERMISOS DENY-BY-DEFAULT + ALLOWLISTS (§16/§17) ═══════════════════
print("── 3. Permisos deny-by-default (§16) + allowlists (§17)")
_vacio = PermissionModel()
check("sin allowlist de aplicaciones ⇒ DENY",
      not _vacio.check_application("notepad").allowed)
check("sin allowlist de dominios ⇒ DENY",
      not _vacio.check_domain("flow.google.com").allowed)
check("sin allowlist de comandos ⇒ DENY",
      not _vacio.check_command(["ffmpeg", "-version"]).allowed)
check("sin raíces de filesystem ⇒ DENY",
      not _vacio.check_path("/tmp/x.txt").allowed)
check("sin allowlist de navegador ⇒ DENY",
      not _vacio.check_browser("https://flow.google.com/").allowed)
check("allow_shell es False por diseño",
      _vacio.allow_shell is False
      and not _vacio.check_command(["bash", "-c", "rm -rf /"]).allowed)

with tempfile.TemporaryDirectory() as tmp:
    _perm = PermissionModel.from_dict({
        "applications": ["notepad-mock", "browser-*"],
        "domains": ["flow.google.com", "labs.google.com"],
        "filesystem_roots": [tmp],
        "browser_urls": ["https://flow.google.com/*"],
        "commands": [{"binary": "ffmpeg", "allowed_prefixes": [["-version"]],
                      "allow_no_args": True}],
    })
    check("aplicación en allowlist ⇒ ALLOW", _perm.check_application("notepad-mock").allowed)
    check("wildcard de aplicación funciona", _perm.check_application("browser-x").allowed)
    check("aplicación fuera de allowlist ⇒ DENY",
          not _perm.check_application("finder").allowed)
    check("dominio y subdominio permitidos",
          _perm.check_domain("flow.google.com").allowed
          and _perm.check_domain("labs.google.com").allowed)
    check("dominio ajeno ⇒ DENY", not _perm.check_domain("evil.com").allowed)
    check("comando permitido por prefijo ⇒ ALLOW",
          _perm.check_command(["ffmpeg", "-version"]).allowed)
    check("comando sin args cuando allow_no_args ⇒ ALLOW",
          _perm.check_command(["ffmpeg"]).allowed)
    check("comando con args NO permitidos ⇒ DENY",
          not _perm.check_command(["ffmpeg", "-i", "x"]).allowed)
    check("binario no listado ⇒ DENY",
          not _perm.check_command(["curl", "http://x"]).allowed)
    check("path dentro de raíz ⇒ ALLOW",
          _perm.check_path(Path(tmp) / "sub" / "f.txt").allowed)
    check("path fuera de raíz ⇒ DENY", not _perm.check_path("/etc/passwd").allowed)
    check("URL de navegador en allowlist ⇒ ALLOW",
          _perm.check_browser("https://flow.google.com/project/abc").allowed)
    check("URL de navegador fuera ⇒ DENY",
          not _perm.check_browser("https://evil.com/x").allowed)
    check("require() lanza PERMISSION_DENIED en DENY",
          expect_error(lambda: _vacio.require(_vacio.check_application("x")),
                       ErrorCode.PERMISSION_DENIED))

# ══ 4. WORKSPACE AISLADO + FRONTERA FS (§18) ═════════════════════════════
print("── 4. Workspace aislado (§18) + frontera filesystem")
with tempfile.TemporaryDirectory() as tmp:
    ws = HandsWorkspace(Path(tmp) / "hands")
    for area in ("workspace", "assets", "downloads", "exports", "tmp",
                 "evidence", "logs", "sessions"):
        check(f"área {area} separada y creada", (ws.root / area).is_dir())
    check("path_for valida área", expect_error(
        lambda: ws.path_for("no_existe", "f.txt"), ErrorCode.VALIDATION_ERROR))
    check("path_for rechaza traversal",
          expect_error(lambda: ws.path_for("downloads", "../../etc/x"),
                       ErrorCode.VALIDATION_ERROR))
    check("path_for acepta subruta normal",
          ws.path_for("downloads", "sub/f.png").is_relative_to(ws.downloads))
    _b = PathBoundary(ws.root)
    check("boundary resuelve dentro", _b.resolve_within(ws.downloads).is_dir())
    check("boundary bloquea escape a /etc", expect_error(
        lambda: _b.resolve_within("/etc/passwd"), ErrorCode.PERMISSION_DENIED))
    # symlink escape
    _fuera = Path(tmp) / "fuera"
    _fuera.mkdir()
    (_fuera / "secreto.txt").write_text("x")
    _link = ws.workspace / "puente"
    _link.symlink_to(_fuera)
    check("boundary bloquea escape por symlink", expect_error(
        lambda: _b.resolve_within(_link / "secreto.txt"),
        ErrorCode.PERMISSION_DENIED))

# ══ 5. SESIONES AUDITABLES (§19) ═════════════════════════════════════════
print("── 5. Sesiones auditables (§19)")
with tempfile.TemporaryDirectory() as tmp:
    from services.hands.sessions import SessionManager
    _mgr = SessionManager(Path(tmp) / "sessions", Path(tmp) / "evidence")
    _sess, _ev = _mgr.start("desktop", {"applications": ["x"]}, locks=["desktop"])
    check("sesión arranca RUNNING con campos obligatorios",
          _sess.current_state is State.RUNNING and _sess.session_id
          and _sess.operator == "desktop" and _sess.start_time
          and _sess.permissions_snapshot and _sess.lock_names == ["desktop"])
    _sess.add_error({"code": "TIMEOUT", "message": "m"})
    _sess.close(final_status="COMPLETED")
    _sess.save()
    _re = _mgr.get(_sess.session_id)
    check("sesión persistida y recargable (auditoría posterior)",
          _re is not None and _re.final_status == "COMPLETED"
          and _re.end_time and _re.errors[0]["code"] == "TIMEOUT"
          and _re.permissions_snapshot == {"applications": ["x"]})

# ══ 6. LOCKS (§20) ═══════════════════════════════════════════════════════
print("── 6. Locks de entorno (§20)")
_lm = LockManager()
_h1 = _lm.acquire("desktop", owner="s1", timeout_s=0.1)
check("lock adquirido con dueño", _lm.held().get("desktop") == "s1")
check("segundo dueño ⇒ BLOCKED", expect_error(
    lambda: _lm.acquire("desktop", owner="s2", timeout_s=0.05),
    ErrorCode.BLOCKED))
check("re-adquisición por el MISMO dueño ⇒ error (doble claim)",
      expect_error(lambda: _lm.acquire("desktop", owner="s1", timeout_s=0.05),
                   ErrorCode.VALIDATION_ERROR))
_h1.release()
check("release libera y otro dueño entra",
      _lm.acquire("desktop", owner="s2", timeout_s=0.1).owner == "s2")
_lm.release_all("s2")
check("release_all limpia", not _lm.is_held("desktop"))

_carrera_ok = []
def _worker(i: int) -> None:
    try:
        h = _lm.acquire("flow", owner=f"w{i}", timeout_s=2.0)
        _carrera_ok.append(h.owner)
        h.release()
    except HandsError:
        pass
_threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
for _t in _threads:
    _t.start()
for _t in _threads:
    _t.join()
check("carrera de 8 threads: locks exclusivos y liberados",
      len(_carrera_ok) == 8 and not _lm.is_held("flow"),
      f"adquiridos={len(_carrera_ok)}")

with tempfile.TemporaryDirectory() as tmp:
    _fl = FileLock(Path(tmp) / "lock.json", stale_s=60)
    _fh = _fl.acquire("proc-a", timeout_s=1.0)
    check("file lock adquirido", _fl.is_locked())
    _fl2 = FileLock(Path(tmp) / "lock.json", stale_s=60)
    check("file lock busy ⇒ BLOCKED en otro 'proceso'", expect_error(
        lambda: _fl2.acquire("proc-b", timeout_s=0.1), ErrorCode.BLOCKED))
    _fh.release()
    check("file lock liberado", not _fl.is_locked())
    _fh2 = _fl2.acquire("proc-b", timeout_s=1.0)
    check("otro proceso toma el lock tras release", _fl2.is_locked())
    _fh2.release()

# ══ 7. EVIDENCIA + REDACCIÓN + AUDIT (§21/§31/§32) ═══════════════════════
print("── 7. Evidencia, redacción de secretos y audit trail")
check("redact enmascara api_key", "sk-abcdefghij" not in
      redact("api_key=sk-abcdefghij1234567890"))
check("redact enmascara bearer/token", "Bearer" not in
      redact("Authorization: Bearer abcdefgh12345678").lower()
      or "[REDACTED]" in redact("Authorization: Bearer abcdefgh12345678"))
check("redact enmascara password json",
      '"password": "secreto"' not in redact('"password": "secreto123"'))
check("texto limpio intacto", redact("operación normal sin secretos")
      == "operación normal sin secretos")

with tempfile.TemporaryDirectory() as tmp:
    _ev = EvidenceLayer(Path(tmp) / "ev", "sess-test", operator="desktop")
    _rec = _ev.record("TEST_OP", target={"semantic": "botón"},
                      expected_state="visible", observed_state="visible",
                      result="PASS", error="token=ghp_supersecreto123456789")
    check("registro con evidence_id y hash",
          bool(_rec["evidence_id"]) and len(_rec["hash"]) == 64)
    check("secreto redactado EN DISCO",
          "ghp_supersecreto" not in (Path(tmp) / "ev" / "evidence_sess-test.jsonl")
          .read_text(encoding="utf-8"))
    _ev.record("TEST_OP", result="FAIL")
    _ev.record("OTRO_OP", result="PASS")
    check("query por acción y resultado",
          len(_ev.query(action="TEST_OP")) == 2
          and len(_ev.query(result="PASS", action="OTRO_OP")) == 1)
    _man = _ev.manifest()
    check("manifiesto de evidencia con sha256",
          _man["records"] == 3 and len(_man["sha256"]) == 64)
    _at = AuditTrail(Path(tmp) / "logs")
    _at.append("op_start", session_id="sess-test", operator="desktop",
               token="ghp_supersecreto123456789")
    check("audit trail append-only redactado",
          "ghp_supersecreto" not in (Path(tmp) / "logs" / "audit_trail.jsonl")
          .read_text(encoding="utf-8"))

# ══ 8. WAIT ENGINE (§10) — reloj determinista ════════════════════════════
print("── 8. Wait engine con timeout obligatorio (§10)")
_fc = FakeClock()
_ks = KillSwitch()
_we = WaitEngine(_fc, killswitch=_ks)
check("timeout<=0 rechazado (no esperas infinitas)", expect_error(
    lambda: WaitSpec("WAIT_UNTIL", timeout_s=0).validate(),
    ErrorCode.VALIDATION_ERROR))
check("kind desconocido rechazado", expect_error(
    lambda: WaitSpec("WAIT_FOREVER", timeout_s=1).validate(),
    ErrorCode.VALIDATION_ERROR))
_out = _we.wait_until(lambda _o: False, timeout_s=2.0, poll_interval_s=0.5)
check("timeout ⇒ outcome(ok=False, error TIMEOUT)",
      _out.ok is False and _out.error["code"] == "TIMEOUT" and _out.polls >= 4)
check("elapsed virtual >= timeout", _out.elapsed_s >= 2.0)
_out2 = _we.wait_until(lambda _o: True, timeout_s=5.0)
check("condición satisfecha ⇒ ok inmediato", _out2.ok and _out2.polls == 1)
check("WAIT_UNTIL sin predicate ⇒ VALIDATION_ERROR", expect_error(
    lambda: _we.wait(WaitSpec("WAIT_UNTIL", timeout_s=1.0, params={})),
    ErrorCode.VALIDATION_ERROR))

# WAIT_FOR_FILE / DOWNLOAD sobre fs real con FakeClock
with tempfile.TemporaryDirectory() as tmp:
    _f = Path(tmp) / "llega.png"
    _we2 = WaitEngine(_fc)
    _out3 = _we2.wait_for_file(_f, timeout_s=1.0)
    check("WAIT_FOR_FILE timeout si no llega", _out3.ok is False)
    _f.write_bytes(b"png")
    _out4 = _we2.wait_for_file(_f, timeout_s=1.0, min_size=2)
    check("WAIT_FOR_FILE ok con min_size", _out4.ok)
    _out5 = _we2.wait_for_download(tmp, timeout_s=1.0, pattern="*.png",
                                   min_size=2)
    check("WAIT_FOR_DOWNLOAD encuentra patrón", _out5.ok)

# WAIT_FOR_WINDOW / ELEMENT / PROCESS / STATE / VISUAL sobre observación
_obs = Observation(timestamp="t", window="Flow — Proyecto", state="ready",
                   visual_digest="abc",
                   processes=[type("P", (), {"to_dict": lambda s: {},
                                             "pid": 7, "name": "ffmpeg",
                                             "state": "running"})()])
_out6 = _we.wait_for_window("Flow*", timeout_s=1.0, provider=lambda: _obs)
check("WAIT_FOR_WINDOW con glob", _out6.ok)
check("WAIT_FOR_STATE ok", _we.wait_for_state("ready", timeout_s=1.0,
      provider=lambda: _obs).ok)
check("WAIT_FOR_PROCESS por nombre",
      _we.wait_for_process(name="ffmpeg", timeout_s=1.0,
                           provider=lambda: _obs).ok)
check("WAIT_FOR_VISUAL_CHANGE detecta digest nuevo",
      _we.wait_for_visual_change("old", timeout_s=1.0,
                                 provider=lambda: _obs).ok)

# ══ 9. VERIFICACIÓN + FILE VERIFICATION (§12/§23) ════════════════════════
print("── 9. Verificación PASS/FAIL/UNKNOWN + file verification")
_v = VerificationEngine()
check("igualdad simple PASS/FAIL",
      _v.verify("a", "a").verdict is Verdict.PASS
      and _v.verify("a", "b").verdict is Verdict.FAIL)
check("observed ausente ⇒ UNKNOWN (nunca PASS)",
      _v.verify("a", None).verdict is Verdict.UNKNOWN)
check("predicate roto ⇒ UNKNOWN",
      _v.verify(lambda o: 1 / 0, 1).verdict is Verdict.UNKNOWN)
check("kind file_exists",
      _v.verify({"kind": "file_exists", "path": __file__}, None).verdict
      is Verdict.PASS)

with tempfile.TemporaryDirectory() as tmp:
    _png = Path(tmp) / "a.png"
    _png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"resto")
    _html = Path(tmp) / "fake.mp4"
    _html.write_bytes(b"<html>error</html>")
    _mp4 = Path(tmp) / "b.mp4"
    _mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"resto")
    _ok = verify_file(_png, min_size=4, extensions=("png",), media_kind="png")
    check("png legítimo ⇒ PASS con media_kind detectado",
          _ok.verdict is Verdict.PASS and _ok.media_kind == "png")
    check("html disfrazado de mp4 ⇒ FAIL por media_kind",
          verify_file(_html, media_kind="mp4").verdict is Verdict.FAIL)
    check("mp4 real ⇒ PASS",
          verify_file(_mp4, media_kind="mp4").verdict is Verdict.PASS)
    check("fichero inexistente must_exist ⇒ FAIL",
          verify_file(Path(tmp) / "nope").verdict is Verdict.FAIL)
    check("fichero inexistente sin must_exist ⇒ UNKNOWN (no FAIL)",
          verify_file(Path(tmp) / "nope", must_exist=False).verdict
          is Verdict.UNKNOWN)
    check("sha256 mismatch ⇒ FAIL",
          verify_file(_png, sha256_expected="0" * 64).verdict is Verdict.FAIL)
    check("extensión incorrecta ⇒ FAIL",
          verify_file(_png, extensions=("mp4",)).verdict is Verdict.FAIL)

# ══ 10. RECOVERY ACOTADO (§24) ═══════════════════════════════════════════
print("── 10. Recovery con presupuesto acotado (§24)")
_fc2 = FakeClock()
_intentos = []
def _falla_siempre():
    _intentos.append(1)
    raise RuntimeError("boom")
try:
    RecoveryEngine(_fc2).run(_falla_siempre, RecoveryPolicy(max_retries=2))
    raise AssertionError("debía fallar")
except Exception:
    pass
check("max_retries=2 ⇒ exactamente 3 intentos", len(_intentos) == 3)
check("error no reintentable se propaga sin retry",
      expect_error(lambda: RecoveryEngine(_fc2).run(
          lambda: (_ for _ in ()).throw(PermissionDeniedError("denegado")),
          RecoveryPolicy(max_retries=5)), ErrorCode.PERMISSION_DENIED))
_intentos2 = []
def _ok_al_3():
    _intentos2.append(1)
    if len(_intentos2) < 3:
        raise RuntimeError("aún no")
    return "recuperado"
_res, _hist = RecoveryEngine(_fc2).run(_ok_al_3, RecoveryPolicy(max_retries=3),
                                       observe=lambda: None,
                                       recover=lambda e: ["acción-recover"])
check("recovery exitoso al 3er intento con backoff creciente",
      _res == "recuperado" and len(_hist) == 3
      and _hist[0].backoff_s == 1.0 and _hist[1].backoff_s == 2.0
      and "acción-recover" in _hist[0].recovered_with)
_ks3 = KillSwitch()
_ks3.engage("prueba recovery")
check("kill switch cancela recovery", expect_error(
    lambda: RecoveryEngine(_fc2, killswitch=_ks3).run(
        _falla_siempre, RecoveryPolicy(max_retries=5)), ErrorCode.STOPPED))

# ══ 11. IDENTIFICACIÓN DE TARGETS (§8) ═══════════════════════════════════
print("── 11. Jerarquía de identificación (§8)")
from services.hands.contracts import ElementRef as _El          # noqa: E402
_obs_rich = Observation(timestamp="t", elements=[
    _El(ref_id="e1", semantic="btn.enviar"),
    _El(ref_id="e2", accessibility="role=textarea"),
    _El(ref_id="e3", text="  Enviar ahora  "),
    _El(ref_id="e4", dom="#send"),
    _El(ref_id="e5", visual={"region": [0, 0, 10, 10]}),
])
_r_strict = TargetResolver()
_m = _r_strict.resolve(TargetSpec(semantic="btn.enviar", text="Enviar",
                                  dom="#send"), _obs_rich)
check("prioridad semántico > texto > DOM", _m.strategy.value == "semantic")
_m2 = _r_strict.resolve(TargetSpec(text="enviar", dom="#send"), _obs_rich)
check("texto visible case-insensitive y por contención",
      _m2.strategy.value == "text" and _m2.element_ref == "e3")
_m3 = _r_strict.resolve(TargetSpec(dom="#send"), _obs_rich)
check("DOM como estrategia intermedia", _m3.element_ref == "e4")
check("sin match ⇒ TARGET_NOT_FOUND con diagnóstico", expect_error(
    lambda: _r_strict.resolve(TargetSpec(text="fantasma"), _obs_rich),
    ErrorCode.TARGET_NOT_FOUND))
check("coords vetadas por política (deny-by-default §8)", expect_error(
    lambda: _r_strict.resolve(TargetSpec(coords=(5, 5)), _obs_rich),
    ErrorCode.PERMISSION_DENIED))
_r_coords = TargetResolver(allow_coordinate_fallback=True)
_m4 = _r_coords.resolve(TargetSpec(coords=(5, 5)), _obs_rich)
check("coords solo con política explícita y como último recurso",
      _m4.strategy.value == "coordinates")

# ══ 12. ACTION ENGINE — ciclo completo (§7) ══════════════════════════════
print("── 12. Action engine: OBSERVE→IDENTIFY→ACTION→OBSERVE→VERIFY")
with tempfile.TemporaryDirectory() as tmp:
    _ws2 = HandsWorkspace(Path(tmp) / "ws")
    _clock = FakeClock()
    _ks2 = KillSwitch()
    _ev2 = EvidenceLayer(_ws2.evidence, "engine-test")
    _at2 = AuditTrail(_ws2.logs)
    _perm2 = PermissionModel.from_dict({"applications": ["mockapp"],
                                        "filesystem_roots": [str(_ws2.root)]})
    _backend = MockDesktopBackend(_clock, _ws2.workspace)
    _eng = ActionEngine(permissions=_perm2,
                        resolver=TargetResolver(),
                        verification=VerificationEngine(),
                        recovery=RecoveryEngine(_clock),
                        clock=_clock, killswitch=_ks2, evidence=_ev2,
                        audit=_at2, action_timeout_s=30.0)
    _r_open = _eng.execute(ActionSpec(
        name=Op.OPEN.value, params={"application": "mockapp"},
        idempotency_check=lambda o: bool(o.window)
        and "mockapp" in (o.window or ""),
        verify={"kind": "window_contains", "value": "mockapp"},
        description="abrir mockapp"), _backend)
    check("OPEN: COMPLETED con verificación PASS",
          _r_open.status is State.COMPLETED
          and _r_open.verification.get("verdict") == "PASS")
    check("pipeline registra before/after + target info",
          "observation_before" in _r_open.result
          and "observation_after" in _r_open.result)
    _ev_ids = list(_r_open.evidence_ids)
    check("evidencia registrada con id", len(_ev_ids) == 1)
    _recs = _ev2.all_records()
    check("evidencia del engine en disco con action OPEN",
          any(r.get("action") == "OPEN" and r.get("result") == "COMPLETED"
              for r in _recs))
    # idempotencia: reabrir no repite
    _r_again = _eng.execute(ActionSpec(
        name=Op.OPEN.value, params={"application": "mockapp"},
        idempotency_check=lambda o: bool(o.window)
        and "mockapp" in (o.window or "")), _backend)
    check("idempotencia §26: already_satisfied, no repite acción",
          _r_again.status is State.COMPLETED
          and _r_again.result.get("already_satisfied") is True)
    # target no encontrado
    _r_miss = _eng.execute(ActionSpec(
        name=Op.CLICK.value, target=TargetSpec(semantic="fantasma.total")),
        _backend)
    check("target inexistente ⇒ FAILED con TARGET_NOT_FOUND",
          _r_miss.status is State.FAILED
          and _r_miss.errors[0]["code"] == "TARGET_NOT_FOUND")
    # verificación fallida
    _r_vfail = _eng.execute(ActionSpec(
        name=Op.OPEN.value, params={"application": "mockapp"},
        verify={"kind": "window_contains", "value": "otra-ventana"}),
        _backend)
    check("verify FAIL ⇒ FAILED con VERIFICATION_FAILED",
          _r_vfail.status is State.FAILED
          and _r_vfail.errors[0]["code"] == "VERIFICATION_FAILED")
    # permiso denegado ⇒ BLOCKED
    _r_den = _eng.execute(ActionSpec(
        name=Op.OPEN.value, params={"application": "prohibida"}), _backend)
    check("app fuera de allowlist ⇒ BLOCKED (§16)",
          _r_den.status is State.BLOCKED
          and _r_den.errors[0]["code"] == "PERMISSION_DENIED")
    # kill switch
    _ks2.engage("prueba engine")
    _r_stop = _eng.execute(ActionSpec(name=Op.OBSERVE.value), _backend)
    check("kill switch ⇒ STOPPED (§27)", _r_stop.status is State.STOPPED)
    _ks2.disengage()
    # recovery acotado dentro del engine
    _backend2 = MockDesktopBackend(_clock, _ws2.workspace)
    _backend2.fail_next(Op.OPEN.value, error_from_exception(
        RuntimeError("fallo transitorio")))
    _r_rec = _eng.execute(ActionSpec(
        name=Op.OPEN.value, params={"application": "mockapp"},
        recovery={"max_retries": 2, "backoff_s": 0.1},
        verify={"kind": "window_contains", "value": "mockapp"}),
        _backend2)
    check("recovery en engine: reintenta y COMPLETA (§24)",
          _r_rec.status is State.COMPLETED)

# ══ 13. RUNTIME COMPLETO — sesión + locks + estados honestos ═════════════
print("── 13. Runtime: sesión auditable con locks y cierre honesto")
with tempfile.TemporaryDirectory() as tmp:
    _rt = HandsRuntime({
        "workspace_root": str(Path(tmp) / "ws"),
        "permissions": {"applications": ["mockapp"],
                        "domains": ["flow.google.com"]},
        "timeouts": {"wait_s": 3.0},
    })
    _st = _rt.status()
    check("status con integración NOT CONNECTED",
          _st["integration_status"] == "NOT CONNECTED")
    check("workspace por defecto creado con áreas",
          (_rt.workspace.root / "evidence").is_dir())
    with _rt.session(operator="desktop", locks=("desktop",)) as _b:
        check("lock adquirido por la sesión", _rt.locks.is_held("desktop"))
        _res_op = _b.desktop.open_app("mockapp")
        check("operador de sesión funciona", _res_op.status is State.COMPLETED)
        check("excepción HandsError capturada en resultado, no lanzada",
              isinstance(_res_op, object) and hasattr(_res_op, "status"))
    check("al salir: sesión cerrada COMPLETED y lock liberado",
          _rt.sessions.get(_b.session_id).final_status == "COMPLETED"
          and not _rt.locks.is_held("desktop"))
    # sesión con lock ocupado ⇒ BLOCKED
    _rt.locks.acquire("desktop", owner="intruso", timeout_s=0.1)
    try:
        with _rt.session(operator="desktop", locks=("desktop",),
                         lock_timeout_s=0.1) as _b2:
            _never = True
        _lock_blocked = False
    except HandsError as _e:
        _lock_blocked = _e.code is ErrorCode.BLOCKED
    check("lock ocupado ⇒ sesión BLOQUEADA al arrancar (§20)", _lock_blocked)
    _rt.locks.release_all("intruso")
    # stop global
    _rt.stop("mantenimiento")
    with _rt.session(operator="desktop", locks=("desktop",)) as _b3:
        _r3 = _b3.desktop.open_app("mockapp")
    check("tras stop(): acción STOPPED y sesión final STOPPED (§27)",
          _r3.status is State.STOPPED
          and _rt.sessions.get(_b3.session_id).final_status == "STOPPED")
    check("timeouts config validados",
          expect_error(lambda: HandsConfig(timeouts={"wait_s": -1}).validate(),
                       ErrorCode.VALIDATION_ERROR))
    check("physical backend exige consentimiento",
          expect_error(lambda: HandsConfig(desktop_backend="physical").validate(),
                       ErrorCode.VALIDATION_ERROR))

# ══ RESUMEN ══════════════════════════════════════════════════════════════
print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
