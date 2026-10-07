"""
PRODUCTION DOCTOR V1.0 — API pública.

Modos (regla 4 del contrato):
  audit()   — diagnóstico completo SIN modificar nada.
  fix()     — diagnostica, aplica SOLO reparaciones seguras (lista blanca),
              re-verifica capas y re-ejecuta los tests afectados.
  verify()  — re-ejecuta checks de capas + baterías de tests de los
              componentes afectados y reporta exactamente qué cambió.
  report()  — último informe legible persistido (o uno fresco).
  preflight() — REAL FLOW PREFLIGHT (barrera antes de gastar una prueba real).

Cada modo persiste su informe en data/doctor/last_report.json y toda
reparación queda en data/doctor/audit_trail.jsonl (regla 10).
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import (AuditTrail, Crono, DoctorReport, Finding, TESTS_POR_COMPONENTE,
                   cargar_ultimo_reporte, doctor_dir, finding, resumen_de)
from .layers import auditar_capas
from .preflight import real_flow_preflight
from .repairs import SAFE_REPAIRS, aplicar_reparaciones

import json as _json  # persistencia del preflight (regla «cada modo persiste»)

_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")

__all__ = ["audit", "fix", "verify", "report", "preflight", "run_mode",
           "DoctorReport", "Finding", "SAFE_REPAIRS", "TESTS_POR_COMPONENTE",
           "cargar_ultimo_reporte", "resumen_de"]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── DOCTOR AUDIT ─────────────────────────────────────────────────────────────
def audit(*, deep: bool = False, in_process: bool = False,
          probe_http: bool = True, capas: list[str] | None = None) -> DoctorReport:
    """Diagnóstico de las 9 capas, SOLO LECTURA. `capas` limita el
    subconjunto (p. ej. ['A','D']) — por defecto todas."""
    with Crono() as cr:
        findings = auditar_capas(deep=deep, in_process=in_process,
                                 probe_http=probe_http, capas=capas)
    rep = DoctorReport(modo="audit", ts=_ts(), findings=findings,
                       resumen=resumen_de(findings), duracion_s=cr.s)
    rep.guardar()
    return rep


# ── tests afectados (regla 7: no hay segunda infraestructura de tests) ──────
def _correr_bateria(nombre: str, timeout: int = 420) -> dict:
    """Ejecuta UNA batería canónica (tests/<nombre>) en su propio proceso —
    exactamente como hace tests/run_all.py. NUNCA edita los tests."""
    ruta = _REPO_TESTS / nombre
    if not ruta.exists():
        return {"bateria": nombre, "ok": False, "error": "no existe",
                "detalle": "la batería mapeada no está en el repo"}
    try:
        proc = subprocess.run(
            [sys.executable, str(ruta)], cwd=str(_REPO_TESTS.parent),
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"bateria": nombre, "ok": False, "error": "timeout",
                "detalle": f">{timeout}s"}
    m = None
    for m in _RESUMEN.finditer(proc.stdout or ""):
        pass
    if proc.returncode == 0 and m:
        ok_n, fail_n = int(m.group(1)), int(m.group(2))
        return {"bateria": nombre, "ok": fail_n == 0 and proc.returncode == 0,
                "ok_count": ok_n, "fail_count": fail_n,
                "detalle": f"{ok_n} OK · {fail_n} fallos · exit "
                           f"{proc.returncode}"}
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    return {"bateria": nombre, "ok": False,
            "detalle": f"exit {proc.returncode} · {' | '.join(tail)[:220]}"}


_REPO_TESTS = Path(__file__).resolve().parents[3] / "tests"


def _tests_de_componentes(componentes: list[str]) -> list[str]:
    """Mapa componente → baterías (dedupe, orden estable)."""
    out: list[str] = []
    for c in componentes:
        for t in TESTS_POR_COMPONENTE.get(c, []):
            if t not in out:
                out.append(t)
    return out


def _ejecutar_tests(componentes: list[str]) -> list[dict]:
    baterias = _tests_de_componentes(componentes)
    return [_correr_bateria(b) for b in baterias]


# ── DOCTOR FIX ───────────────────────────────────────────────────────────────
def fix(*, deep: bool = False, in_process: bool = False,
        ejecutar_tests: bool = True) -> DoctorReport:
    """DIAGNOSTICAR → EXPLICAR → REPARAR (solo lista blanca) → VALIDAR.

    Ciclo completo de la regla 7: AUDIT → (reparaciones) → re-audit de capas
    afectadas → TESTS de los componentes afectados. Todo queda en el audit
    trail con antes/después."""
    with Crono() as cr:
        findings = auditar_capas(deep=deep, in_process=in_process)
        acciones, componentes = aplicar_reparaciones(findings)

        # audit trail (regla 10) — una entrada por acción aplicada
        trail = AuditTrail()
        componentes_trail = list(componentes)
        for a in acciones:
            rid = a.get("repair", "?")
            spec = SAFE_REPAIRS.get(rid, {})
            fids = a.get("finding_ids", [])
            diag = next((f.titulo for f in findings if f.id in fids),
                        rid)
            tests = _tests_de_componentes(
                [spec.get("componente", "doctor")])
            trail.append(
                finding_id=fids[0] if fids else rid,
                diagnostico=diag,
                archivo_afectado=a.get("archivo_afectado",
                                       spec.get("archivo", "?")),
                funcion_afectada=a.get("funcion_afectada",
                                       spec.get("funcion", "?")),
                cambio=a.get("cambio", ""),
                motivo=(next((f.causa_probable for f in findings
                              if f.id in fids), "")
                        or spec.get("descripcion", "")),
                test_ejecutado=", ".join(tests) or "(verificación de capas)",
                resultado_antes=a.get("antes", ""),
                resultado_despues=a.get("despues", ""))
            if spec.get("componente") and \
                    spec["componente"] not in componentes_trail:
                componentes_trail.append(spec["componente"])

        # VALIDAR: re-audit SOLO de las capas cuyos componentes se tocaron
        capas_re = _capas_de_componentes(componentes_trail)
        restantes = auditar_capas(capas=capas_re, deep=deep,
                                  in_process=in_process) if capas_re else []
        no_resueltos = [f for f in restantes
                        if f.reparacion_disponible and not f.reparado]

        tests_res = _ejecutar_tests(componentes_trail) \
            if (ejecutar_tests and componentes_trail) else []
        verify = {
            "capas_re_ejecutadas": capas_re,
            "findings_recurrentes": len(no_resueltos),
            "findings_recurrentes_detalle":
                [f.to_dict() for f in no_resueltos][:10],
            "tests": tests_res,
            "tests_ok": all(t.get("ok") for t in tests_res) if tests_res
            else None,
        }
    rep = DoctorReport(modo="fix", ts=_ts(), findings=findings,
                       acciones=acciones, verify=verify,
                       resumen=resumen_de(findings), duracion_s=cr.s)
    rep.guardar()
    return rep


def _capas_de_componentes(componentes: list[str]) -> list[str]:
    """Componente → capas del audit que lo vigilan."""
    mapa = {
        "flow_jobs": ["D", "G"], "production_json": ["A"],
        "adapter": ["B"], "flow_export": ["C"], "orchestrator": ["D"],
        "extension": ["E"], "manifest": ["E"], "bridge": ["E"],
        "google_flow": ["F"], "assets": ["G"], "video_qa": ["H"],
        "render": ["I"], "doctor": ["I"],
    }
    out: list[str] = []
    for c in componentes:
        for capa in mapa.get(c, []):
            if capa not in out:
                out.append(capa)
    return out


# ── DOCTOR VERIFY ────────────────────────────────────────────────────────────
def verify(*, deep: bool = False, in_process: bool = False,
           capas: list[str] | None = None,
           componentes: list[str] | None = None,
           ejecutar_tests: bool = True) -> DoctorReport:
    """Re-ejecuta los checks de las capas pedidas (o todas) + las baterías
    de los componentes pedidos (o los mapeados a lo que aparezca). Reporta
    exactamente qué cambió: findings por capa y resultado por batería."""
    with Crono() as cr:
        findings = auditar_capas(capas=capas, deep=deep,
                                 in_process=in_process)
        comps = componentes or sorted({
            f.componente for f in findings
            if f.componente in TESTS_POR_COMPONENTE})
        tests_res = _ejecutar_tests(comps) if (ejecutar_tests and comps) else []
        verify = {
            "capas_ejecutadas": capas or list("ABCDEFGHI"),
            "componentes_testados": comps,
            "tests": tests_res,
            "tests_ok": all(t.get("ok") for t in tests_res) if tests_res
            else None,
        }
    rep = DoctorReport(modo="verify", ts=_ts(), findings=findings,
                       verify=verify, resumen=resumen_de(findings),
                       duracion_s=cr.s)
    rep.guardar()
    return rep


# ── DOCTOR REPORT ────────────────────────────────────────────────────────────
def report(*, refrescar: bool = False) -> dict:
    """Informe legible del estado del sistema: el último persistido, o uno
    fresco (audit) si no existe o se pide refrescar."""
    if not refrescar:
        ultimo = cargar_ultimo_reporte()
        if ultimo:
            return ultimo
    return audit().to_dict()


# ── REAL FLOW PREFLIGHT ──────────────────────────────────────────────────────
def preflight(project_id: str | None = None,
              backend_url: str | None = None) -> dict:
    """Barrera REAL FLOW PREFLIGHT (regla 8). Nunca ejecuta Flow.
    v2.19 · persiste el resultado en data/doctor/last_report.json (mismo
    contrato que los demás modos — el docstring del paquete lo promete y
    antes solo audit/fix/verify lo cumplían)."""
    res = real_flow_preflight(project_id=project_id, backend_url=backend_url)
    try:
        d = doctor_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "last_report.json").write_text(_json.dumps(
            {"doctor": "PRODUCTION DOCTOR", "version": "1.0",
             "modo": "preflight", "ts": _ts(),
             "preflight": res, "verdict": res.get("verdict"),
             "ok": res.get("ok")},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:  # la barrera NUNCA depende del disco
        pass
    return res


# ── dispatcher único (CLI / MCP / API) ───────────────────────────────────────
def run_mode(modo: str, *, deep: bool = False, in_process: bool = False,
             ejecutar_tests: bool = True, project_id: str | None = None,
             backend_url: str | None = None,
             capas: list[str] | None = None) -> dict:
    if modo == "audit":
        return audit(deep=deep, in_process=in_process, capas=capas).to_dict()
    if modo == "fix":
        return fix(deep=deep, in_process=in_process,
                   ejecutar_tests=ejecutar_tests).to_dict()
    if modo == "verify":
        return verify(deep=deep, in_process=in_process, capas=capas,
                      ejecutar_tests=ejecutar_tests).to_dict()
    if modo == "report":
        return report()
    if modo == "preflight":
        return preflight(project_id=project_id, backend_url=backend_url)
    raise ValueError(f"modo desconocido: {modo} "
                     "(audit|fix|verify|report|preflight)")
