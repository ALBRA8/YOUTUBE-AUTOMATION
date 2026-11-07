# -*- coding: utf-8 -*-
"""PASO 0.2 · Registro de las baterías de minidramas en tests/run_all.py.

Reglas que este test blinda:
  1. test_minidrama_clip_validator.py y test_observador_piloto.py están
     en BATERIAS de tests/run_all.py y sus archivos existen.
  2. Cada una imprime, ejecutada como script standalone, el resumen
     "N OK · M fallos" que el runner parsea (sin él, run_all la contaría
     como "SIN RESUMEN (¿crash?)" aunque estuviera verde).
  3. Son herméticas: corren bajo la guardia de red (este mismo test pasa
     con ella activa).

Ejecutar: python3 -m pytest tests/test_registro_baterias.py -q
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

import run_all as runall  # noqa: E402  (BATERIAS es la lista canónica)

MINIDRAMAS = ("test_minidrama_clip_validator.py", "test_observador_piloto.py")
_RESUMEN = re.compile(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos")


def test_baterias_registradas_y_archivos_existentes():
    for nombre in MINIDRAMAS:
        assert nombre in runall.BATERIAS, f"{nombre} falta en BATERIAS"
        assert (REPO / "tests" / nombre).is_file(), f"no existe {nombre}"
    assert nombre not in runall.NON_HERMETIC_BATTERIES  # herméticas


def test_bateria_standalone_imprime_resumen_parseable():
    """Cada batería, ejecutada como script, termina 0 y emite el resumen
    que run_all sabe parsear (43 OK · 0 fallos / 12 OK · 0 fallos)."""
    for nombre in MINIDRAMAS:
        proc = subprocess.run(
            [sys.executable, str(REPO / "tests" / nombre)],
            cwd=str(REPO), capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, (nombre, proc.stdout[-400:])
        m = _RESUMEN.findall(proc.stdout)
        assert m, f"{nombre} sin resumen parseable"
        ok, fallos = (int(n) for n in m[-1])
        assert ok > 0 and fallos == 0, (nombre, ok, fallos)


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
