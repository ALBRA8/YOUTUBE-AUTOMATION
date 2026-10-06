"""
PRODUCTION DOCTOR V1.0 — CLI.

Uso (desde backend/, igual que el resto de servicios):
    python3 -m services.production_doctor audit   [--deep] [--json]
    python3 -m services.production_doctor fix     [--deep] [--json] [--no-tests]
    python3 -m services.production_doctor verify  [--deep] [--json] [--capas A,C]
    python3 -m services.production_doctor report  [--json]
    python3 -m services.production_doctor preflight [--project-id PID] [--json]

Exit codes: 0 = limpio/PASS · 1 = findings o REAL FLOW BLOCKED · 2 = uso.
"""
from __future__ import annotations

import argparse
import json
import sys


def _imprimir_humano(rep: dict) -> None:
    print(f"═══ PRODUCTION DOCTOR V1.0 · modo {rep.get('modo', '?').upper()} "
          f"· {rep.get('ts', '')} ═══")
    if rep.get("modo") == "preflight" or "verdict" in rep:
        print(f"VEREDICTO: {rep.get('verdict')}")
        for c in rep.get("checks", []):
            marca = "✓" if c.get("ok") else "✗"
            print(f"  {marca} {c.get('id')}: {c.get('detalle')[:140]}")
        for r in rep.get("blocked_reasons", []):
            print(f"  ⛔ BLOQUEA: {r[:160]}")
        return
    res = rep.get("resumen", {})
    print(f"findings: {res.get('total', 0)} · reparables pendientes: "
          f"{res.get('reparables_pendientes', 0)} · requieren humano: "
          f"{res.get('requieren_humano', 0)}")
    for f in rep.get("findings", []):
        marca = {"critical": "⛔", "error": "✗", "warn": "⚠", "info": "·"}\
            .get(f.get("severidad"), "·")
        reparado = " [REPARADO]" if f.get("reparado") else ""
        print(f"  {marca} [{f.get('capa')}/{f.get('clasificacion')}] "
              f"{f.get('titulo')}{reparado}")
        if f.get("reparacion_disponible") and not f.get("reparado"):
            print(f"      ↳ auto-fix disponible: {f.get('reparacion_accion')}")
        if f.get("requiere_humano"):
            print("      ↳ HUMAN INVESTIGATION REQUIRED")
    for a in rep.get("acciones", []):
        print(f"  ♦ FIX {a.get('repair')}: {a.get('cambio')[:150]}")
    v = rep.get("verify") or {}
    if v.get("tests"):
        for t in v["tests"]:
            marca = "✓" if t.get("ok") else "✗"
            print(f"  {marca} TEST {t.get('bateria')}: {t.get('detalle', '')[:120]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="production_doctor",
                                 description="PRODUCTION DOCTOR V1.0")
    ap.add_argument("modo", choices=["audit", "fix", "verify", "report",
                                     "preflight"])
    ap.add_argument("--deep", action="store_true",
                    help="incluir QA forense pesado (ffprobe por asset)")
    ap.add_argument("--json", action="store_true", help="salida JSON completa")
    ap.add_argument("--no-tests", action="store_true",
                    help="no re-ejecutar baterías en fix/verify")
    ap.add_argument("--project-id", default=None,
                    help="preflight/audit de un proyecto concreto")
    ap.add_argument("--backend-url", default=None,
                    help="URL del backend para preflight (default 127.0.0.1:PORT)")
    args = ap.parse_args(argv)

    # sys.path: este módulo se ejecuta desde backend/ (python -m services.…)
    from services.production_doctor import run_mode
    try:
        rep = run_mode(
            args.modo, deep=args.deep,
            ejecutar_tests=not args.no_tests,
            project_id=args.project_id, backend_url=args.backend_url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        _imprimir_humano(rep)

    # exit code honesto: findings reales o bloqueo = 1
    if rep.get("modo") == "preflight" or "verdict" in rep:
        return 0 if rep.get("ok") else 1
    res = rep.get("resumen", {})
    graves = sum(v for k, v in (res.get("por_severidad") or {}).items()
                 if k in ("critical", "error"))
    return 1 if graves else 0


if __name__ == "__main__":
    sys.exit(main())
