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


# ══ U3 · bloque plegado «Avanzado» ════════════════════════════════════════

def _entre(s: str, a: str, b: str) -> str:
    """Contenido entre el ancla a y el ancla b (una ocurrencia cada uno)."""
    assert s.count(a) == 1 and s.count(b) == 1, f"anclas: {a!r} {b!r}"
    return s.split(a, 1)[1].split(b, 1)[0]


def test_u3_tarjetas_y_consola_viven_en_avanzado():
    """Las tarjetas por servicio, Test Pipeline, Refrescar, Reparar perfil,
    Abrir ventana y el #mcp-log quedan DENTRO del <details> «Avanzado»;
    la tarjeta del ecosistema y la del pipeline quedan FUERA (cuerpo)."""
    dentro = _entre(MCP_JS, '<details class="mcp-adv" id="mcp-advanced">',
                    '</details>\n  </div>`;'.replace("\n  ", "\n\n  "))
    fuera = MCP_JS.split('<details class="mcp-adv" id="mcp-advanced">', 1)[0]
    for contenido in ("mcpSvcHTML('google-flow'", "mcpSvcHTML('notebooklm'",
                      "mcpTest('')", 'id="mcp-log"', "gsessRepairProfile()",
                      "gsessOpenWindow()", "Avanzado"):
        assert contenido in dentro, f"debe vivir en Avanzado: {contenido!r}"
    for contenido in ("mcpGsessHTML()", 'id="pipe-card"'):
        assert contenido in fuera, f"debe seguir en el cuerpo: {contenido!r}"
    assert "<details" in STYLE.replace('details.mcp-adv', '<details') or \
        ".mcp-adv" in STYLE  # CSS del plegado


def test_u3_stderr_crudo_solo_en_avanzado():
    """El único sitio que RENDERIZA stderr_tail crudo es la zona de
    servicio (que vive dentro de Avanzado); avisoHumanoDe solo lo LEE
    (no lo pinta) y la tarjeta principal nunca muestra el volcado."""
    import re
    zona = MCP_JS.index("function mcpZoneHTML(")
    renders = [m.start() for m in re.finditer(r"st\.stderr_tail", MCP_JS)]
    assert renders, "el volcado crudo debe seguir existiendo en la zona"
    assert all(zona < p for p in renders), \
        "el volcado crudo solo puede pintarse dentro de mcpZoneHTML"
    # avisoHumanoDe LO LEE (v.stderr_tail) pero no lo renderiza
    aviso = MCP_JS.index("function avisoHumanoDe(")
    lecturas = [m.start() for m in re.finditer(r"v\.stderr_tail", MCP_JS)]
    assert lecturas and all(
        aviso < p < MCP_JS.index("function mcpZoneHTML(") for p in lecturas)
    assert "stderr_tail" not in MCP_JS.split("function mcpGsessHTML(")[1].split(
        "function ecoRowHTML(")[0]


def test_u3_aviso_conocido_humano():
    """fastmcp en la consola → línea humana «NO afecta» arriba y en la
    zona; sin fastmcp → sin aviso."""
    assert "function avisoHumanoDe(" in MCP_JS
    assert "/fastmcp/i" in MCP_JS and "NO afecta" in MCP_JS
    assert "id=\"eco-aviso\"" in MCP_JS
    # comportamiento verificado evaluando la función con node (sin DOM)
    import subprocess, json
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    fn = MCP_JS[MCP_JS.index("function avisoHumanoDe("):]
    fn = fn[:fn.index("}", fn.index("return ''")) + 1]
    script = fn + """
console.log(JSON.stringify([
  avisoHumanoDe({a: {stderr_tail: ['FastMCP 2.14.5 is outdated']}}),
  avisoHumanoDe({a: {stderr_tail: ['otro error cualquiera']}}),
  avisoHumanoDe({}),
]));"""
    r = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:200]
    con_aviso, sin_aviso, vacio = json.loads(r.stdout)
    assert "NO afecta" in con_aviso and "FastMCP" in con_aviso
    assert sin_aviso == "" and vacio == ""


def test_u3_sintaxis_js():
    _node_check()


# ══ U4 · selector de cuaderno auto-relleno + memoria por nicho ═══════════

def test_u4_selector_en_tarjeta_principal():
    """El selector nicho+cuaderno vive en la tarjeta principal (después de
    las filas del semáforo) y los IDs de contrato (#nblm-nid-sel,
    #nblm-nid, #nblm-list-btn) se conservan; la tarjeta de Avanzado ya no
    duplica el desplegable."""
    tarjeta = _entre(MCP_JS, "function mcpGsessHTML() {",
                     "async function gsessStart() {")
    for contenido in ("ecoNichoNidHTML()", 'id="nblm-nicho-sel"',
                      'id="nblm-nid-sel"', 'id="nblm-nid"', "nblm-list-btn"):
        assert contenido in tarjeta, f"falta en la tarjeta principal: {contenido!r}"
    svc = _entre(MCP_JS, "function mcpSvcHTML(",
                 "function renderMCP() {")
    assert "nblm-nid-sel" not in svc, "el desplegable no debe duplicarse en Avanzado"


def test_u4_memoria_por_nicho_en_registro_q4():
    """Al elegir cuaderno con nicho activo → POST /api/registro/nicho
    (UN cuaderno por nicho, Q4); sin nicho → avisa que no se recuerda."""
    pick = _entre(MCP_JS, "function mcpPickNotebook(", "function mcpZoneHTML(")
    assert "api('/registro/nicho', { method: 'POST', body: {" in pick
    assert "nicho_id: nicho, notebook_id: id" in pick
    assert "nombre_cuaderno:" in pick
    assert "elige un nicho arriba para que se recuerde" in pick
    assert "NICHOS_KEY" in MCP_JS and "yta-eco-nicho" in MCP_JS
    # cargar nichos: GET /api/niches/templates y restaurar cuaderno del nicho
    cargar = _entre(MCP_JS, "async function mcpNichosCargar(",
                    "function mcpZoneHTML(")
    assert "api('/niches/templates')" in cargar
    assert "api('/registro/nicho/' + encodeURIComponent(nicho))" in cargar


def test_u4_autorelleno_al_conectar_y_vacios_utiles():
    """Al conectar NotebookLM el desplegable se rellena solo (ya existía) y
    el texto del vacío reacciona al estado REAL: conectado → «pulsa
    Listar», no conectado → «conecta NotebookLM»."""
    assert "mcpListNotebooks({ silent: true })" in MCP_JS
    assert "NotebookLM conectado: pulsa «🔄 Listar / refrescar notebooks»" in MCP_JS
    assert "— conecta NotebookLM para listar los tuyos —" in MCP_JS
    # la actualización del vacío vive en mcpApplyStatus (reacciona al estado)
    apply = _entre(MCP_JS, "function mcpApplyStatus(", "async function mcpRefresh(")
    assert "op0.textContent" in apply
    assert "(S.mcp && (S.mcp.notebooklm || {}).state === 'connected')" in apply


def test_u4_endpoints_usados_existen():
    """Los endpoints que consume U4 están en la app real (misma auth)."""
    import asyncio
    import httpx
    import main as _main  # noqa: F401
    schema = _main.app.openapi()
    rutas = set(schema["paths"])
    assert "/api/registro/nicho" in rutas
    assert "/api/registro/nicho/{nicho_id}" in rutas
    assert "/api/niches/templates" in rutas


def test_u4_sintaxis_js():
    _node_check()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
