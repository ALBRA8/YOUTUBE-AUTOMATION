#!/usr/bin/env python3
"""Chunk-runner: replica tests/run_all.py (1 proceso por batería) pero
ejecuta SOLO las baterías pasadas como argumentos, para poder repartir
la suite canónica en varias ventanas de ejecución.

Uso:  python3 tests/run_chunk.py battery1.py battery2.py ...
Salida: resumen por batería + total; exit 1 si alguna falla.
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent


def main() -> int:
    baterias = sys.argv[1:]
    total_ok = total_fail = 0
    fallidas = []
    for i, nombre in enumerate(baterias, 1):
        print(f"\n──────── [{i}/{len(baterias)}] {nombre} ────────", flush=True)
        proc = subprocess.run(
            [sys.executable, str(TESTS_DIR / nombre)],
            cwd=str(REPO), capture_output=True, text=True)
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        ok = fail = 0
        for line in proc.stdout.splitlines():
            line = line.replace("═", "").strip()
            if line.endswith("OK") and "·" in line and "fallos" in line:
                try:
                    parts = line.split("·")
                    ok = int(parts[0].split()[-1])
                    fail = int(parts[1].split()[0])
                except (ValueError, IndexError):
                    pass
        if proc.returncode != 0:
            print(f"  → {nombre}: EXIT {proc.returncode} (revisar arriba)")
            fail = fail or 1
        total_ok += ok
        total_fail += fail
        if fail:
            fallidas.append(nombre)
        print(f"  → {nombre}: {ok} OK · {fail} fallos", flush=True)
    print(f"\n{'═' * 60}")
    print(f"TOTAL LOTE: {total_ok} OK · {total_fail} fallos "
          f"en {len(baterias)} baterías")
    if fallidas:
        print("FALLIDAS:", ", ".join(fallidas))
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
