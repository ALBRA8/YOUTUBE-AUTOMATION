#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-5 · PROTOCOLO DE ACEPTACIÓN — Fase 3 (ROADMAP).

Meta: 10 videos seguidos en 2 nichos, SIN intervención manual, con
  · cero placeholders,
  · cero proyectos "ready" con fallos de QA (severidad error),
  · aceptación 8/10 o mejor, y una muestra revisada por el dueño.

ESTADO: PREPARADO, NO EJECUTADO (NOT_DEMONSTRATED) — requiere Flow real y
el servidor ALBRA levantado en la máquina del dueño. Este script NO genera
videos: observa, mide y redacta el reporte del protocolo.

USO (máquina del dueño):
  1. Arranca ALBRA (launchers/INICIAR-ALBRA.vbs) con Google Flow conectado.
  2. python tools/fase3_aceptacion.py --nichos "nichoA,nichoB" --objetivo 10
  3. Lanza los 10 proyectos (los que falten) y re-ejecuta el script; al
     alcanzar el objetivo escribe el reporte con veredicto.

Criterios codificados en evalua_protocolo(): un solo lugar de verdad.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ── Criterios de aceptación (única fuente) ──────────────────────────────────
CRITERIOS = {
    "min_videos": 10,           # 10 videos en el protocolo
    "nichos": 2,                # en 2 nichos distintos
    "max_placeholders": 0,      # cero placeholders en TODOS
    "max_qa_errors_ready": 0,   # ningún "ready" con fallos QA de severidad error
    "min_sin_intervencion": 8,  # meta 8/10 sin intervención manual
    "muestra_humana": 1,        # el dueño revisa al menos una muestra
}


def evalua_protocolo(registros: list[dict]) -> dict:
    """Puro y hermético: dado el registro de cada video, dicta el veredicto.
    Registro esperado: {proyecto, nicho, estado, placeholders:int,
    qa_errors:int, intervencion_manual:bool, revisada_por_dueno:bool}"""
    n = len(registros)
    nichos = {r.get("nicho") for r in registros if r.get("nicho")}
    ph = sum(int(r.get("placeholders", 0)) for r in registros)
    qa_bad = sum(1 for r in registros
                 if r.get("estado") == "ready" and int(r.get("qa_errors", 0)) > 0)
    sin_manual = sum(1 for r in registros if not r.get("intervencion_manual"))
    muestra = any(r.get("revisada_por_dueno") for r in registros)
    checks = {
        "videos_suficientes": n >= CRITERIOS["min_videos"],
        "nichos_suficientes": len(nichos) >= CRITERIOS["nichos"],
        "cero_placeholders": ph <= CRITERIOS["max_placeholders"],
        "cero_ready_con_qa_error": qa_bad <= CRITERIOS["max_qa_errors_ready"],
        "meta_sin_intervencion": sin_manual >= CRITERIOS["min_sin_intervencion"],
        "muestra_revisada": muestra,
    }
    return {
        "videos": n, "nichos": sorted(nichos), "placeholders_totales": ph,
        "ready_con_qa_error": qa_bad, "sin_intervencion": sin_manual,
        "checks": checks,
        "veredicto": "PASS" if all(checks.values()) else "FAIL",
    }


def _api(url: str, timeout: float = 10.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # localhost
        return json.loads(r.read().decode("utf-8"))


def recolecta(base_url: str, nichos: list[str]) -> list[dict]:
    """Observa los proyectos ya renderizados del protocolo (sin crear nada)."""
    out = []
    for p in _api(f"{base_url}/api/projects").get("projects", []):
        if nichos and str(p.get("nicho", "")) not in nichos:
            continue
        if str(p.get("status")) not in ("ready", "failed", "error"):
            continue
        pid = p.get("id")
        qa = {}
        try:
            qa = _api(f"{base_url}/api/projects/{pid}/qa")
        except Exception:  # noqa: BLE001 — QA ausente se reporta, no aborta
            qa = {"error": "sin QA"}
        n_ph = sum(1 for s in qa.get("scenes", [])
                   if (s.get("image") or {}).get("is_placeholder"))
        n_err = sum(1 for f in qa.get("flags", [])
                    if f.get("sev") == "error")
        out.append({
            "proyecto": pid,
            "nicho": p.get("nicho", "?"),
            "estado": p.get("status"),
            "placeholders": n_ph,
            "qa_errors": n_err,
            "intervencion_manual": bool(p.get("meta", {})
                                        .get("intervencion_manual", False)),
            "revisada_por_dueno": bool(p.get("meta", {})
                                       .get("revisada_por_dueno", False)),
        })
    return out


def redacta(res: dict) -> str:
    lineas = [
        "# Reporte Fase 3 · Aceptación (protocolo ROADMAP)", "",
        f"- Fecha: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        f"- Videos: {res['videos']} · Nichos: {', '.join(res['nichos']) or '—'}",
        f"- Placeholders totales: {res['placeholders_totales']} (máx {CRITERIOS['max_placeholders']})",
        f"- 'ready' con QA error: {res['ready_con_qa_error']} (máx {CRITERIOS['max_qa_errors_ready']})",
        f"- Sin intervención manual: {res['sin_intervencion']}/{CRITERIOS['min_sin_intervencion']} (meta 8/10)",
        f"- Muestra revisada por el dueño: {'sí' if res['checks']['muestra_revisada'] else 'NO'}",
        "", "| criterio | estado |", "|---|---|",
    ]
    lineas += [f"| {k} | {'✅' if v else '❌'} |" for k, v in res["checks"].items()]
    lineas += ["", f"## VEREDICTO: **{res['veredicto']}**", ""]
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Protocolo Fase 3 (observador)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--nichos", required=True, help="'nichoA,nichoB'")
    ap.add_argument("--objetivo", type=int, default=CRITERIOS["min_videos"])
    args = ap.parse_args()
    nichos = [n.strip() for n in args.nichos.split(",") if n.strip()]
    registros = recolecta(args.base_url, nichos)
    res = evalua_protocolo(registros)
    reporte = redacta(res)
    destino = REPO / "CONTEXTO YOUTUBE" / "08_SESSIONS" / "REPORTE_FASE3.md"
    destino.write_text(reporte, encoding="utf-8")
    print(reporte)
    print(f"[fase3] {len(registros)}/{args.objetivo} videos observados → "
          f"reporte: {destino}")
    return 0 if res["veredicto"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
