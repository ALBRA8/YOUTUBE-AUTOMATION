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
import os

# [D5] consola UTF-8 aunque el host use cp1252: baterías ejecutadas a mano
# SIN variables de entorno no deben morir por imprimir "──" u otros glifos.
import sys as _d5sys
for _d5s in (_d5sys.stdout, _d5sys.stderr):
    try:
        _d5s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import re
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")

if sys.platform == "win32" and not shutil.which("bash"):
    print("── live_boot_smoke.sh: omitido en Windows sin bash (entorno Linux/CI requerido)")
    print("\n0 OK · 0 fallos")
    sys.exit(0)

SCRIPTS = [
    ("live_boot_smoke.sh", "boot vivo (uvicorn + CORS + endpoints base)"),
    ("live_cycle_smoke.sh", "ciclo completo Flow Bridge por HTTP real"),
]

ok = 0
fail = 0
for script, desc in SCRIPTS:
    print(f"── {script}: {desc}")
    # [F7 · V13] Fin de línea IRRELEVANTE para la ejecución: bash no tolera
    # CRLF (`$'do\r'` → syntax error). El árbol de trabajo del dueño puede
    # tener los .sh materializados en CRLF (checkout histórico con
    # core.autocrlf=true previo a la higiene X3) sin que `git status` lo
    # muestre; la batería NO puede depender de CÓMO se hizo el checkout.
    # Solución: copia LF-normalizada HERMANA del original (mismo dirname).
    src = TESTS_DIR / script
    script_path, _tmp_copy = src, None
    try:
        if b"\r\n" in src.read_bytes():
            # hermana del original (mismo dirname): los scripts derivan el
            # repo desde `$(dirname "$0")/..` — un tmp global rompería las rutas
            _tmp_copy = TESTS_DIR / f".{script}.lf_norm.tmp"
            _tmp_copy.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
            _tmp_copy.chmod(0o755)
            script_path = _tmp_copy
        proc = subprocess.run(["bash", str(script_path)],
                              cwd=str(TESTS_DIR.parent),
                              capture_output=True, text=True, timeout=300)
    finally:
        if _tmp_copy is not None:
            _tmp_copy.unlink(missing_ok=True)
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
