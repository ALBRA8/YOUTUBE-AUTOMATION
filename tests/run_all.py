#!/usr/bin/env python3
"""Runner de las baterías canónicas de tests (fuente de verdad).

Ejecuta las 4 baterías en orden, cada una en su PROPIO proceso python3
(aislamiento total de sys.modules), imprime un resumen por batería
(X OK · Y fallos) y un total. Exit code != 0 si alguna batería falla
o no puede ejecutarse.

Uso:  cd yt_automation_v2 && python3 tests/run_all.py
"""
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

BATERIAS = [
    "test_guion_json.py",        # contrato legacy guion_json + MCP (42 checks)
    "test_production_json.py",   # adapter Production JSON 2.16 (76 checks)
    "test_merge_216_pyav.py",    # merge/integración 2.16.x + fix PyAV (51 checks)
    "test_lanzar_preflight.py",  # preflight de lanzamiento vía MCP (29 checks)
    "test_flow_contract_p1.py",  # GOLDEN EXECUTION CONTRACT P1: video_prompt
                                 # del Creative Engine llega verbatim a Flow (44)
    "test_flow_bridge.py",       # FLOW BRIDGE v1: cola real claim/lease/
                                 # heartbeat/complete/fail + 6 endpoints (48)
    "test_golden_fixture.py",    # FIXTURE GOLDEN oficial: cadena completa con
                                 # DB (fixture → ingest → export → cola → QA)
    "test_qa_forensics.py",      # QA FORENSE de medios: pantalla negra/azul,
                                 # audio silencioso, propagación de warns (30)
    "test_production_doctor.py", # PRODUCTION DOCTOR V1.0: capas A-I, taxonomía,
                                 # reparaciones seguras, audit trail, SHA de lo
                                 # creativo invariante (54)
    "test_doctor_preflight.py",  # REAL FLOW PREFLIGHT: barrera antes de gastar
                                 # una prueba real con Google Flow; criterio
                                 # estricto video_prompt + STRUCTURAL ≠
                                 # RUNTIME NOT_DEMONSTRATED (38)
    "test_concurrencia.py",      # concurrencia: raza de claims, multi-proyecto,
                                 # token de una sola era, completes paralelos
    "test_chaos.py",             # chaos: reinicio REAL de proceso, rollback,
                                 # doble complete, asset corrupto, zombie
    "test_10_escenas.py",        # ESCALA: proyecto de 10 escenas (19 jobs),
                                 # P1 verbatim + prompt de ~11KB + QA a escala
    "test_bridge_e2e.py",        # E2E extensión: node --check + bridge.js real
                                 # contra backend mock (sandbox VM)
    "test_humos_infra.py",       # humos: lo declarado EXISTE en el repo (~50)
    "test_live_boot.py",         # BOOT VIVO: uvicorn real + ciclo completo del
                                 # Flow Bridge por HTTP (boot + cycle smoke)
]

_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")


def main() -> int:
    total_ok = 0
    total_fail = 0
    fallidas: list[str] = []

    for i, nombre in enumerate(BATERIAS, 1):
        print(f"\n──────── [{i}/{len(BATERIAS)}] {nombre} ────────")
        proc = subprocess.run(
            [sys.executable, str(TESTS_DIR / nombre)],
            cwd=str(TESTS_DIR.parent), capture_output=True, text=True,
        )
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)

        coincidencias = _RESUMEN.findall(proc.stdout)
        if coincidencias:
            ok, fail = (int(n) for n in coincidencias[-1])
            detalle = f"{ok} OK · {fail} fallos"
        else:
            ok, fail = 0, -1  # sin resumen → la batería no terminó (crash)
            detalle = "SIN RESUMEN (¿crash?)"
        verde = proc.returncode == 0 and fail == 0
        if fail < 0:
            fail = 0
        total_ok += ok
        total_fail += max(fail, 0)
        if not verde:
            fallidas.append(nombre)
        print(f"  → {nombre}: {detalle} · exit {proc.returncode}"
              + ("" if verde else "  ✗ FALLA"))

    print(f"\n═══ TOTAL: {total_ok} OK · {total_fail} fallos "
          f"en {len(BATERIAS)} baterías ═══")
    if fallidas:
        print("Baterías en rojo: " + ", ".join(fallidas))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
