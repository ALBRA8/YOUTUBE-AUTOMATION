# -*- coding: utf-8 -*-
"""U2-U5 · Panel MCP rediseñado alrededor de la verdad de U1.

Este archivo crece por punto (un bloque por commit):
  U2 · Tarjeta única «Ecosistema Google» con 3 filas de semáforo REAL
       (fuente: GET /api/mcp/resumen), botón primario «Conectar todo»
       (POST /api/mcp/connect-all-google) y el badge «ECOSISTEMA
       CONECTADO» SOLO cuando U1 dice todo_conectado.
  U3 · Bloque plegado «Avanzado»: tarjetas por servicio, Reparar
       perfil, Probar, Test Pipeline y volcado de stderr viven AHÍ;
       los avisos conocidos (fastmcp) se traducen a una línea humana.
  U4 · Selector de cuaderno auto-relleno + memoria por nicho
       (registro de nichos Q4) con vacíos que dicen qué hacer.
  U5 · «Run Full Pipeline» deshabilitado con motivo exacto mientras
       U1 diga listo_para_pipeline=false.

Hermético: solo lectura de static/*.js/css y node --check (si hay
node). La verificación VISUAL en navegador real queda NOT_DEMONSTRATED
(sandbox sin Chrome de escritorio) — se lista en el cierre U7.

Ejecutar: python3 -m pytest tests/test_u_panel_ecosistema.py -q
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
STATIC = BACKEND / "static"
sys.path.insert(0, str(BACKEND))

MCP_JS = (STATIC / "app-mcp.js").read_text(encoding="utf-8")
CORE_JS = (STATIC / "app-core.js").read_text(encoding="utf-8")
STYLE = (STATIC / "style.css").read_text(encoding="utf-8")


def _node_check():
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    r = subprocess.run([node, "--check", str(STATIC / "app-mcp.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:300]


# ══ U2 · tarjeta única con semáforo real de U1 ═══════════════════════════

def test_u2_badge_mentiroso_eliminado():
    """La mentira original: `connected = flow||notebooklm||…` pintaba
    ECOSISTEMA CONECTADO con UNA pieza en verde. Ahora el badge sale del
    todo_conectado de U1 y en otro caso muestra el contador real."""
    assert "gsessSvcState(st.flow) || gsessSvcState(st.notebooklm)" not in MCP_JS
    assert MCP_JS.count("ECOSISTEMA CONECTADO") == 1, \
        "el texto verde debe existir UNA vez, dentro de la guarda de U1"
    # la única aparición está guardada por todo_conectado (U1)
    idx = MCP_JS.index("ECOSISTEMA CONECTADO")
    guarda = MCP_JS.rindex("todo_conectado", 0, idx)
    assert idx - guarda < 200, "«ECOSISTEMA CONECTADO» no está tras todo_conectado"
    # estado incompleto con contador real (nOk/4)
    assert "ECOSISTEMA INCOMPLETO" in MCP_JS and "${nOk}/4" in MCP_JS


def test_u2_tres_filas_con_semaforo_de_u1():
    """3 filas (Chrome, Flow, NotebookLM) pintadas con ecoRowHTML desde
    eco.piezas + línea de cuaderno, todas de /api/mcp/resumen."""
    for fila in ("ecoRowHTML('Chrome (CDP 9333)', piezas.chrome)",
                 "ecoRowHTML('Google Flow', piezas.flow)",
                 "ecoRowHTML('NotebookLM', piezas.notebooklm)"):
        assert fila in MCP_JS, f"falta la fila {fila!r}"
    assert "piezas.cuaderno" in MCP_JS and "eco-cuaderno" in MCP_JS
    assert "function ecoRowHTML(" in MCP_JS
    # la fila pinta detalle Y línea de acción de U1
    assert "accion_siguiente" in MCP_JS and "p.detalle" in MCP_JS
    # CSS de las filas presente
    for cls in (".eco-row", ".eco-accion", ".eco-row-head"):
        assert cls in STYLE


def test_u2_fuente_de_verdad_es_resumen():
    """gsessRefresh pide /mcp/resumen (U1) y guarda S.eco; el SSO solo
    aporta el perfil/fase. Sin llamadas con doble prefijo (regla INT-080)."""
    assert "api('/mcp/resumen')" in MCP_JS
    assert "S.eco = eco;" in MCP_JS
    assert "api('/api/" not in MCP_JS


def test_u2_boton_conectar_todo_con_login_claro():
    """Botón primario «Conectar todo» → POST /api/mcp/connect-all-google
    (endpoint que ya existía) y, si Chrome no está arriba (U1), dice al
    dueño que INICIE SESIÓN en la ventana que se abre."""
    assert "async function gsessConnectAll(" in MCP_JS
    assert "api('/mcp/connect-all-google'" in MCP_JS
    assert "onclick=\"gsessConnectAll()\"" in MCP_JS
    assert MCP_JS.count("INICIA SESIÓN") >= 2   # antes y tras el clic
    # el aviso depende del estado de Chrome según U1 (no de una adivinanza)
    assert "piezas.chrome.ok" in MCP_JS


def test_u2_contratos_vigentes_int025_int088():
    """Los nombres que fijan los tests INT-025/INT-088 siguen definidos
    (gsessApply/gsessRefresh/mcpGsessHTML/gsessStart/mcpPopulateNotebooks…)."""
    for sym in ("mcpGsessHTML", "gsessStart", "gsessOpenChrome", "gsessRefresh",
                "gsessApply", "mcpPopulateNotebooks", "gsess-card",
                "Ecosistema Google", "function renderMCP(",
                "async function mcpConnect(", "async function pipeRun("):
        assert sym in MCP_JS, f"contrato roto: {sym!r}"


def test_u2_sintaxis_js():
    _node_check()


def test_u2_n_funcs_real_actualizado():
    """El conteo estructural de INT-088 quedó 189 → 188 (U2): 3 pintadores
    HTML a mano fuera, ecoRowHTML + gsessConnectAll dentro. Este test
    fuerza que el número declarado coincida con el real del repo."""
    import re
    t88 = (BACKEND.parent / "tests" / "test_int088_app_modular_split.py").read_text(
        encoding="utf-8")
    m = re.search(r"N_FUNCS_REAL\s*=\s*(\d+)", t88)
    assert m, "no se halló N_FUNCS_REAL en test_int088"
    declarado = int(m.group(1))
    total = 0
    for mod in ("app-core.js", "app-projects.js", "app-mcp.js",
                "app-wizard.js", "app-player.js"):
        txt = (STATIC / mod).read_text(encoding="utf-8")
        total += len(re.findall(r"^(?:async )?function ([A-Za-z_$][\w$]*)",
                                txt, re.M))
    assert total == declarado, f"{total} funciones reales != {declarado} declaradas"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
