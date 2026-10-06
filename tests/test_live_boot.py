#!/usr/bin/env python3
"""Batería de BOOT VIVO: la única que arranca uvicorn de verdad.

Los tests ASGI (httpx) prueban el contrato en memoria; esta batería cubre la
capa que solo existe con un servidor real levantado:

  1. live_boot_smoke.sh   → uvicorn arranca, CORS preflight de la extensión,
                            endpoints base, métricas, video QA, sin tracebacks.
  2. live_cycle_smoke.sh  → ciclo COMPLETO del Flow Bridge por HTTP real:
                            enqueue (build_script_json) → claim ordenado →
                            complete con PNG/MP4 reales (PIL/ffprobe) →
                            409 doble complete → 422 HTML → fail/retry →
                            guard de tipo → project_done → auto-render → QA.

Uso:  cd yt_automation_v2 && python3 tests/test_live_boot.py
"""
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")

SCRIPTS = [
    ("live_boot_smoke.sh", "boot vivo (uvicorn + CORS + endpoints base)"),
    ("live_cycle_smoke.sh", "ciclo completo Flow Bridge por HTTP real"),
]

ok = 0
fail = 0
for script, desc in SCRIPTS:
    print(f"── {script}: {desc}")
    proc = subprocess.run(["bash", str(TESTS_DIR / script)],
                          cwd=str(TESTS_DIR.parent),
                          capture_output=True, text=True, timeout=300)
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    m = _RESUMEN.findall(proc.stdout)
    if m:
        s_ok, s_fail = (int(n) for n in m[-1])
    else:
        s_ok, s_fail = 0, 1
        print("  ✗ sin resumen (¿crash del script?)")
    ok += s_ok
    fail += s_fail + (0 if proc.returncode == 0 else 1)
    if proc.returncode != 0 or s_fail:
        print(f"  ✗ {script} terminó mal (exit {proc.returncode})")

print(f"═══ {ok} OK · {fail} fallos ═══")
sys.exit(1 if fail else 0)
