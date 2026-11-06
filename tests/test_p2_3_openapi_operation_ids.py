# -*- coding: utf-8 -*-
"""P2-3 · Regresión: el esquema OpenAPI NO puede emitir warnings por
operation IDs duplicados (index__get, mcp_sin_barra_mcp_get, dashboard_index,
mcp_proxy_sin_barra...).

Lección de la primera versión de este test: buscaba la subcadena
"operation_id" (guion bajo) pero el warning real dice "Operation ID"
(espacio) → el test pasaba EN FALSO mientras la suite seguía mostrando 2
warnings. Ahora detecta por DOS vías independientes:
  1. Cuenta operationId repetidos en el ESQUEMA generado (no hay confianza
     en el texto del warning).
  2. Captura warnings cuyo mensaje case con /operation[ _-]?id/i.
Y fija el contrato P2-3: cada método de las rutas multi-método (/ y /mcp)
lleva su propio operation_id (un id compartido en un api_route
multi-método DUPLICA el id: FastAPI crea una operación por método).

Ejecutar: python3 -m pytest tests/test_p2_3_openapi_operation_ids.py -q
"""
import re
import sys
import warnings
from collections import Counter
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
        spec = get_openapi(title=main.app.title, version=main.app.version,
                           routes=main.app.routes)
    # Vía 1: el texto del warning (espacio O guion bajo, mayúsculas da igual)
    dups = [str(x.message) for x in w
            if re.search(r"operation[ _-]?id", str(x.message), re.IGNORECASE)]
    assert not dups, f"OpenAPI emite warnings de operation id duplicado: {dups}"
    # Vía 2: conteo REAL de ids en el esquema (vía 1 pudo no dispararse)
    ids = [op.get("operationId")
           for ops in spec["paths"].values()
           for op in ops.values()]
    repetidos = {k: v for k, v in Counter(ids).items() if v > 1}
    assert not repetidos, f"operationId repetidos en el esquema: {repetidos}"


def test_rutas_multi_metodo_con_id_por_metodo():
    """/ y /mcp: cada método su operación con id propio y distinto."""
    import main
    vistos: dict[str, set] = {}
    for route in main.app.routes:
        nombre = getattr(route, "name", "")
        if nombre in ("index", "mcp_sin_barra"):
            oid = getattr(route, "operation_id", None)
            assert oid, f"{nombre} sin operation_id explícito (P2-3)"
            vistos.setdefault(nombre, set()).add(oid)
    assert "dashboard_index" in vistos.get("index", set()), (
        "GET / debe conservar el id dashboard_index")
    assert vistos.get("mcp_sin_barra") == {
        "mcp_proxy_sin_barra_get", "mcp_proxy_sin_barra_post"}, (
        f"/mcp debe tener un id por método: {vistos.get('mcp_sin_barra')}")


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
