# -*- coding: utf-8 -*-
"""P2-3 · Regresión: el esquema OpenAPI NO puede emitir warnings por
operation IDs duplicados (index__get, mcp_sin_barra_mcp_get...).

Ejecutar: python3 -m pytest tests/test_p2_3_openapi_operation_ids.py -q
"""
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_openapi_sin_operation_ids_duplicados():
    from fastapi.openapi.utils import get_openapi
    import main
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        get_openapi(title=main.app.title, version=main.app.version,
                    routes=main.app.routes)
    dups = [str(x.message) for x in w if "operation_id" in str(x.message).lower()]
    assert not dups, f"OpenAPI emite warnings de operation_id duplicado: {dups}"


def test_operation_ids_explicitos_en_rutas_multiples_metodos():
    """Las api_route con varios métodos llevan operation_id explícito."""
    import main
    for route in main.app.routes:
        methods = getattr(route, "methods", None) or set()
        if len(methods) > 1 and hasattr(route, "endpoint"):
            nombre = getattr(route, "name", "")
            if nombre in ("index", "mcp_sin_barra"):
                assert getattr(route, "operation_id", None), (
                    f"{nombre} sin operation_id explícito (P2-3)")


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
