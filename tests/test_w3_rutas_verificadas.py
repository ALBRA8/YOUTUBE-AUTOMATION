# -*- coding: utf-8 -*-
"""W3 · Guardia estática de rutas verificadas por el dueño en su PC.

Verifica que ni el backend (backend/main.py) ni el panel web
(backend/static/app-mcp.js) dejen de llamar o eliminen las rutas que el dueño
usó con éxito en su máquina:
  1. POST /api/mcp/google-sso/launch (con force_window: true)
  2. POST /api/mcp/launch-auth-browser
  3. POST /api/mcp/repair-profile
  4. POST /api/mcp/connect (con servicio google-flow)

Regla de oro 8 en LEEME_PRIMERO.md y catálogo en
CONTEXTO YOUTUBE/00_MASTER/RUTAS_VERIFICADAS_POR_EL_DUENO.md.
"""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
STATIC = BACKEND / "static"
CONTEXTO = REPO / "CONTEXTO YOUTUBE" / "00_MASTER"

RUTAS_CRITICAS = [
    "/mcp/google-sso/launch",
    "/mcp/launch-auth-browser",
    "/mcp/repair-profile",
    "/mcp/connect",
]


def test_w3_backend_endpoints_presentes():
    """backend/main.py debe registrar los 4 endpoints críticos verificados."""
    main_py = (BACKEND / "main.py").read_text(encoding="utf-8")
    for ruta in RUTAS_CRITICAS:
        api_ruta = f"/api{ruta}"
        assert f'"{api_ruta}"' in main_py or f"'{api_ruta}'" in main_py or ruta in main_py, (
            f"La ruta crítica {api_ruta} no está declarada en backend/main.py"
        )


def test_w3_panel_calls_presentes():
    """backend/static/app-mcp.js debe seguir invocando los 4 endpoints críticos."""
    app_mcp_js = (STATIC / "app-mcp.js").read_text(encoding="utf-8")
    for ruta in RUTAS_CRITICAS:
        assert ruta in app_mcp_js, (
            f"El panel backend/static/app-mcp.js dejó de llamar a {ruta}"
        )


def test_w3_panel_google_sso_launch_usa_force_window():
    """El panel debe llamar a /mcp/google-sso/launch con force_window: true."""
    app_mcp_js = (STATIC / "app-mcp.js").read_text(encoding="utf-8")
    idx = app_mcp_js.index("/mcp/google-sso/launch")
    contexto = app_mcp_js[idx:idx + 250]
    assert "force_window: true" in contexto, (
        "La llamada a /mcp/google-sso/launch debe incluir 'force_window: true'"
    )


def test_w3_documentacion_y_regla_leeme():
    """El catálogo RUTAS_VERIFICADAS_POR_EL_DUENO.md y la regla 8 de LEEME_PRIMERO.md deben existir."""
    doc_path = CONTEXTO / "RUTAS_VERIFICADAS_POR_EL_DUENO.md"
    assert doc_path.is_file(), f"No se encontró el documento {doc_path}"
    doc_text = doc_path.read_text(encoding="utf-8")
    for ruta in RUTAS_CRITICAS:
        assert ruta in doc_text, f"Falta {ruta} en RUTAS_VERIFICADAS_POR_EL_DUENO.md"

    leeme = (REPO / "LEEME_PRIMERO.md").read_text(encoding="utf-8")
    assert "Rutas verificadas por el dueño" in leeme, (
        "Falta la regla de rutas verificadas en LEEME_PRIMERO.md"
    )
    for ruta in RUTAS_CRITICAS:
        assert ruta in leeme, f"Falta mención a {ruta} en LEEME_PRIMERO.md"


if __name__ == "__main__":
    import pytest as _pytest

    class _Resumen:
        def __init__(self) -> None:
            self.ok = self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = _pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
