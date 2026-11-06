# -*- coding: utf-8 -*-
"""P2-2 · TRINQUETE de `except Exception`: el número NO puede subir.

Línea base: 283 (auditoría P2-2, 2026-11-06; medido con rg sobre backend/**.py).
Regla: si añades un `except Exception` nuevo, este test FALLA y te obliga a
(1) justificarlo bajando otro de la misma zona (el trinquete no retrocede) o
(2) subir la constante BASELINE en este archivo EXPLICÁNDOLO en el commit.
Prioridad de reducción (P2-2): pipeline/, publicación y render — los que
tragan errores en silencio y entregan productos degradados.

Ejecutar: python3 -m pytest tests/test_p2_2_except_ratchet.py -q
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"

BASELINE = 283  # 2026-11-06 — NO subir sin justificación en el commit

_PATRON = re.compile(r"^\s*except\s+Exception\b")


def _cuenta() -> tuple[int, dict]:
    por_archivo: dict[str, int] = {}
    for path in sorted(BACKEND.rglob("*.py")):
        n = sum(1 for linea in path.read_text(encoding="utf-8").split("\n")
                if _PATRON.match(linea))
        if n:
            por_archivo[str(path.relative_to(REPO))] = n
    return sum(por_archivo.values()), por_archivo


def test_trinquete_except_exception_no_suben():
    total, por_archivo = _cuenta()
    assert total <= BASELINE, (
        f"`except Exception` subió: {total} > {BASELINE} (P2-2 trinquete). "
        "O reduce otros de la misma zona, o sube BASELINE en "
        "tests/test_p2_2_except_ratchet.py justificándolo en el commit. "
        f"Top: {sorted(por_archivo.items(), key=lambda kv: -kv[1])[:5]}"
    )


def test_zonas_criticas_por_debajo_de_su_linea():
    """Pipeline/video/orchestrator: los traga-errores peligrosos del render."""
    total, por_archivo = _cuenta()
    criticos = ["backend/pipeline/orchestrator.py", "backend/pipeline/video.py"]
    actual = sum(por_archivo.get(c, 0) for c in criticos)
    # línea base crítica al 2026-11-06: orchestrator 14 + video 11 = 25
    assert actual <= 25, (
        f"pipeline crítico subió a {actual} (> 25): justifica o reduce. "
        "Un except Exception en render = video degradado en silencio."
    )


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
