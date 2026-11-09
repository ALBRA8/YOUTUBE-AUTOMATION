# -*- coding: utf-8 -*-
"""PASO 1 · Tests de la sonda de capacidades MCP (nombres Flow/NotebookLM).

HERMÉTICOS y con DOBLES: la sonda real se conecta vía services.mcp_manager
en la máquina del dueño; aquí NUNCA se toca Flow ni NotebookLM reales ni
se arranca ningún subprocess de MCP. Los catálogos son fixtures falsos.

Ejecutar: python3 -m pytest tests/test_sonda_capacidades.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
BACKEND = REPO / "backend"
for p in (str(TOOLS), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sonda_capacidades_nombres import (  # noqa: E402
    NO_SOPORTADO,
    PEND,
    SOPORTADO,
    _catalogo_via_http,
    _leer_env_backend,
    analizar_tools,
    crear_pruebas,
    main,
    sondar_mcp,
)

FLOW_OK = [
    {"name": "flow_new_project", "description": "crea proyecto",
     "inputSchema": {"type": "object",
                     "properties": {"name": {"type": "string"}}}},
    {"name": "flow_new_character", "description": "crea personaje",
     "inputSchema": {"type": "object",
                     "properties": {"name": {"type": "string"},
                                    "reference": {"type": "string"}}}},
    {"name": "flow_generate_image", "description": "genera imagen",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"}}}},
]

FLOW_SIN_NOMBRE = [
    {"name": "flow_new_project", "inputSchema": {"type": "object",
                                                 "properties": {}}},
]

FLOW_RENOMBRAR = [
    {"name": "flow_new_project", "inputSchema": {"type": "object",
                                                 "properties": {}}},
    {"name": "flow_rename_project",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"},
                                    "name": {"type": "string"}}}},
]

NLM_OK = [
    {"name": "notebook_create", "description": "crea cuaderno",
     "inputSchema": {"type": "object",
                     "properties": {"notebook": {"type": "string"}}}},
    {"name": "source_add", "description": "añade fuente",
     "inputSchema": {"type": "object",
                     "properties": {"notebook": {"type": "string"},
                                    "source_type": {"type": "string"},
                                    "text": {"type": "string"},
                                    "title": {"type": "string"}}}},
    {"name": "notebook_list", "inputSchema": {"type": "object",
                                              "properties": {}}},
    {"name": "studio_generate", "inputSchema": {"type": "object",
                                                "properties": {}}},
]

NLM_RENOMBRAR = NLM_OK + [
    {"name": "notebook_rename",
     "inputSchema": {"type": "object",
                     "properties": {"notebook_id": {"type": "string"},
                                    "title": {"type": "string"}}}},
]


def _por_id(res):
    return {r["id"]: r for r in res}


# ── análisis puro: google-flow ────────────────────────────────────────

def test_flow_con_nombre_es_soportado():
    r = _por_id(analizar_tools("google-flow", FLOW_OK))
    assert r["q1_flow_proyecto_nombre"]["veredicto"] == SOPORTADO
    assert "flow_new_project" in r["q1_flow_proyecto_nombre"]["detalle"]
    assert r["q2_flow_personaje_nombre"]["veredicto"] == SOPORTADO


def test_flow_sin_nombre_es_no_soportado():
    r = _por_id(analizar_tools("google-flow", FLOW_SIN_NOMBRE))
    assert r["q1_flow_proyecto_nombre"]["veredicto"] == NO_SOPORTADO
    assert r["q2_flow_personaje_nombre"]["veredicto"] == NO_SOPORTADO


def test_flow_renombrar_cuenta_como_soportado():
    r = _por_id(analizar_tools("google-flow", FLOW_RENOMBRAR))
    assert r["q1_flow_proyecto_nombre"]["veredicto"] == SOPORTADO
    assert "flow_rename_project" in r["q1_flow_proyecto_nombre"]["detalle"]


# ── análisis puro: notebooklm ─────────────────────────────────────────

def test_notebooklm_titulos_soportados():
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q3_notebook_create_titulo"]["veredicto"] == SOPORTADO
    assert r["q5_source_add_titulo"]["veredicto"] == SOPORTADO


def test_notebooklm_sin_renombrar_es_no_soportado():
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q4_notebook_renombrar"]["veredicto"] == NO_SOPORTADO


def test_notebooklm_renombrar_soportado():
    r = _por_id(analizar_tools("notebooklm", NLM_RENOMBRAR))
    assert r["q4_notebook_renombrar"]["veredicto"] == SOPORTADO


def test_preguntas_cruzadas_quedan_not_demonstrated():
    """Las preguntas de Flow no se responden con el catálogo de NotebookLM."""
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q1_flow_proyecto_nombre"]["veredicto"] == PEND
    r2 = _por_id(analizar_tools("google-flow", FLOW_OK))
    assert r2["q3_notebook_create_titulo"]["veredicto"] == PEND


def test_catalogo_vacio_todo_not_demonstrated():
    for servicio in ("google-flow", "notebooklm"):
        r = _por_id(analizar_tools(servicio, []))
        assert all(x["veredicto"] == PEND for x in r.values()), servicio


# ── sondar_mcp con dobles (nunca MCP real) ────────────────────────────

def test_sondar_mcp_error_conexion_es_not_demonstrated():
    """Sin MCP real (sandbox/dueño apagado): el error se captura y el
    análisis cae en NOT_DEMONSTRATED — jamás un SOPORTADO inventado."""
    async def doble_que_falla(service):
        raise RuntimeError("no se pudo lanzar notebooklm-mcp")

    out = asyncio.run(sondar_mcp("notebooklm", catalogo_fn=doble_que_falla))
    assert out["error"] and out["tools"] == []
    r = _por_id(analizar_tools("notebooklm", out["tools"]))
    assert all(x["veredicto"] == PEND for x in r.values())


def test_sondar_mcp_con_doble_de_catalogo():
    async def doble(service):
        return {"server_info": {"name": "fake-nlm", "version": "0.8.5"},
                "tools": NLM_OK}
    out = asyncio.run(sondar_mcp("notebooklm", catalogo_fn=doble))
    assert out["server_info"]["version"] == "0.8.5"
    assert len(out["tools"]) == 4


def test_crear_pruebas_solo_con_doble():
    """La vía de creación llama al doble que le pasan (en producción,
    manager.execute tras flag+confirmación); los fallos se registran."""
    llamadas = []

    async def doble(service, tool, args):
        llamadas.append((service, tool, args))
        if tool == "flow_new_character":
            raise RuntimeError("TOOL_NOT_ALLOWED")
        return "ok"

    res = asyncio.run(crear_pruebas(doble))
    assert len(res) == 3 and len(llamadas) == 3
    assert res[0]["resultado"] == "EJECUTADA"
    assert res[1]["resultado"] == "FALLO"
    assert res[2]["resultado"] == "EJECUTADA"


# ── CLI: el flag de creación exige confirmación ───────────────────────

def test_crear_prueba_sin_confirmacion_refusa(monkeypatch, capsys):
    """--crear-prueba sin --confirmo 'SI CREAR' → refusa, exit 2, y ni
    siquiera se intenta crear (el doble no se llama)."""
    llamadas = []

    async def doble_crear(*a, **k):
        llamadas.append(a)
        return []

    async def doble_sondar(service, catalogo_fn=None, modo="http"):
        return {"service": service, "server_info": {}, "tools": [],
                "error": "sin MCP en pruebas"}

    monkeypatch.setattr("sonda_capacidades_nombres.sondar_mcp", doble_sondar)
    monkeypatch.setattr("sonda_capacidades_nombres.crear_pruebas", doble_crear)
    code = main(["--crear-prueba"])
    assert code == 2
    assert llamadas == []          # nada se creó
    assert "REFUSADO" in capsys.readouterr().err


def test_crear_prueba_con_confirmacion_llama_una_vez(monkeypatch):
    llamadas = []

    async def doble_crear(ejecutar_fn):
        llamadas.append(ejecutar_fn)
        return [{"prueba": "x", "resultado": "FALLO", "detalle": "sin MCP"}]

    async def doble_sondar(service, catalogo_fn=None, modo="http"):
        return {"service": service, "server_info": {}, "tools": [],
                "error": "sin MCP en pruebas"}

    monkeypatch.setattr("sonda_capacidades_nombres.sondar_mcp", doble_sondar)
    monkeypatch.setattr("sonda_capacidades_nombres.crear_pruebas", doble_crear)
    code = main(["--crear-prueba", "--confirmo", "SI CREAR"])
    assert code == 0
    assert len(llamadas) == 1      # la creación pasó por el doble


# ── tools_catalog de mcp_manager (catálogo de solo lectura) ──────────

def test_tools_catalog_con_conn_falsa(monkeypatch):
    """Con una conexión ya viva (falsa), tools_catalog devuelve el catálogo
    SIN lanzar subprocess (si no hay conn, conectaría — eso es del dueño)."""
    from services.mcp_manager import ST_CONNECTED, manager

    fake = SimpleNamespace(
        state=ST_CONNECTED,
        server_info={"name": "fake-flow", "version": "1.0"},
        tools=[{"name": "flow_new_project",
                "description": "x",
                "inputSchema": {"properties": {"name": {}}}}])
    monkeypatch.setitem(manager._conns, "google-flow", fake)
    cat = asyncio.run(manager.tools_catalog("google-flow"))
    assert cat["server_info"]["name"] == "fake-flow"
    assert cat["tools"][0]["name"] == "flow_new_project"
    assert "inputSchema" in cat["tools"][0]


def test_tools_catalog_servicio_desconocido():
    from services.mcp_manager import manager, MCPManagerError
    with pytest.raises(Exception):
        asyncio.run(manager.tools_catalog("desconocido"))


# ── Y2 · q5 corregida por capacidad y esquema; q8-q10 sobre Flow ──────

NLM_ADD_TEXT = [
    {"name": "notebook_add_text", "description": "añade nota de texto",
     "inputSchema": {"type": "object",
                     "properties": {"notebook_id": {"type": "string"},
                                    "text": {"type": "string"},
                                    "title": {"type": "string"}}}},
]   # 'title' NO está en required: OPCIONAL — y basta para SOPORTADO

NLM_ADD_TEXT_SIN_TITULO = [
    {"name": "notebook_add_text", "description": "añade nota de texto",
     "inputSchema": {"type": "object",
                     "properties": {"notebook_id": {"type": "string"},
                                    "text": {"type": "string"}}}},
]

FLOW_Q10_OK = [
    {"name": "flow_generate_image",
     "inputSchema": {"properties": {"prompt": {}, "project_id": {}}}},
    {"name": "flow_generate_video",
     "inputSchema": {"properties": {"prompt": {}, "project_id": {}}}},
    {"name": "flow_upload_file",
     "inputSchema": {"properties": {"file": {}, "project_id": {}}}},
]


def test_q5_notebook_add_text_con_titulo_opcional_es_soportado():
    """q5 corregida (Y2): capacidad «añadir texto» (notebook_add_text en el
    paquete real v0.1.15; source_add legacy) y basta 'title' en el esquema
    aunque sea OPCIONAL."""
    r = _por_id(analizar_tools("notebooklm", NLM_ADD_TEXT))
    q5 = r["q5_source_add_titulo"]
    assert q5["veredicto"] == SOPORTADO
    assert "notebook_add_text" in q5["detalle"] and "title" in q5["detalle"]


def test_q5_source_add_legacy_sigue_reconocido():
    """El nombre legacy de nlm_studio (source_add) sigue valiendo."""
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q5_source_add_titulo"]["veredicto"] == SOPORTADO


def test_q5_sin_title_es_no_soportado():
    r = _por_id(analizar_tools("notebooklm", NLM_ADD_TEXT_SIN_TITULO))
    assert r["q5_source_add_titulo"]["veredicto"] == NO_SOPORTADO


def test_q8_nombre_solo_por_esquema():
    """q8 (Y2): ¿flow_new_project acepta un nombre? — sin el rescate de q1
    vía renombrar: sin nombre en el esquema es NO_SOPORTADO aunque exista
    una tool de renombrar."""
    r = _por_id(analizar_tools("google-flow", FLOW_OK))
    assert r["q8_flow_new_project_nombre"]["veredicto"] == SOPORTADO
    r2 = _por_id(analizar_tools("google-flow", FLOW_SIN_NOMBRE))
    assert r2["q8_flow_new_project_nombre"]["veredicto"] == NO_SOPORTADO
    # cruces honestos: catálogo vacío o ajeno → NOT_DEMONSTRATED
    assert _por_id(analizar_tools("google-flow", []))[
        "q8_flow_new_project_nombre"]["veredicto"] == PEND
    assert _por_id(analizar_tools("notebooklm", NLM_OK))[
        "q8_flow_new_project_nombre"]["veredicto"] == PEND


def test_q9_retorno_por_outputschema():
    tools = [{"name": "flow_new_project", "description": "Crea un proyecto",
              "inputSchema": {"properties": {}},
              "outputSchema": {"type": "object",
                               "properties": {"project_id": {"type": "string"}}}}]
    r = _por_id(analizar_tools("google-flow", tools))
    q9 = r["q9_flow_new_project_devuelve"]
    assert q9["veredicto"] == SOPORTADO and "project_id" in q9["detalle"]


def test_q9_retorno_por_descripcion():
    tools = [{"name": "flow_new_project",
              "description": "Crea un proyecto. Devuelve el id del proyecto creado.",
              "inputSchema": {"properties": {}}}]
    r = _por_id(analizar_tools("google-flow", tools))
    assert r["q9_flow_new_project_devuelve"]["veredicto"] == SOPORTADO


def test_q9_descripcion_declara_que_no_devuelve():
    tools = [{"name": "flow_new_project",
              "description": "Crea un proyecto. No devuelve ningún valor.",
              "inputSchema": {"properties": {}}}]
    r = _por_id(analizar_tools("google-flow", tools))
    assert r["q9_flow_new_project_devuelve"]["veredicto"] == NO_SOPORTADO


def test_q9_sin_evidencia_es_not_demonstrated():
    """Sin outputSchema ni descripción que evidencie el retorno → honesto
    NOT_DEMONSTRATED (jamás se inventa qué devuelve)."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q7_MUDA))
    assert r["q9_flow_new_project_devuelve"]["veredicto"] == PEND


def test_q10_id_proyecto_uniforme_es_soportado():
    r = _por_id(analizar_tools("google-flow", FLOW_Q10_OK))
    assert r["q10_flow_generacion_identificador_proyecto"]["veredicto"] == SOPORTADO


def test_q10_destino_generico_no_cuenta_como_id_proyecto():
    """q10 es más estricta que q6: 'destino' genérico (upload_file en
    FLOW_Q6_OK) NO es un identificador de proyecto → NO_SOPORTADO."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q6_OK))
    q10 = r["q10_flow_generacion_identificador_proyecto"]
    assert q10["veredicto"] == NO_SOPORTADO
    assert "flow_upload_file" in q10["detalle"]


def test_q10_sin_generacion_es_not_demonstrated():
    r = _por_id(analizar_tools("google-flow", FLOW_Q7_MUDA))
    assert r["q10_flow_generacion_identificador_proyecto"]["veredicto"] == PEND


# ── Y2 · la sonda lee por HTTP del backend (default) ─────────────────

def test_sondar_mcp_http_es_el_default(monkeypatch):
    """Sin catalogo_fn, la sonda usa el endpoint HTTP del backend (Y1) y NO
    importa el gestor en su propio proceso (nada de procesos duplicados)."""
    llamadas = []

    def doble_http(service):
        llamadas.append(service)
        return {"server_info": {"name": "vía-http"},
                "tools": NLM_ADD_TEXT}

    monkeypatch.setattr("sonda_capacidades_nombres._catalogo_via_http", doble_http)
    out = asyncio.run(sondar_mcp("notebooklm"))
    assert out["error"] == "" and llamadas == ["notebooklm"]
    assert out["tools"][0]["name"] == "notebook_add_text"


def test_backend_no_responde_da_mensaje_claro(monkeypatch):
    """Si el backend no está en marcha, el error dice la URL y la acción
    siguiente (arrancar el panel o --modo-local), y el análisis cae
    NOT_DEMONSTRATED — jamás un SOPORTADO inventado."""
    import urllib.request as _ur

    def urlopen_roto(req, timeout):
        raise _ur.URLError("connection refused")

    monkeypatch.setattr(_ur, "urlopen", urlopen_roto)
    out = asyncio.run(sondar_mcp("google-flow"))   # default: modo http
    assert "no respondió" in out["error"] and "--modo-local" in out["error"]
    assert out["tools"] == []
    r = _por_id(analizar_tools("google-flow", out["tools"]))
    assert all(x["veredicto"] == PEND for x in r.values())


def test_leer_env_backend_puerto_y_apikey(tmp_path):
    """(PORT, MASTER_API_KEY) se leen de backend/.env sin levantar nada;
    comentarios y ausencias → defaults 8000 / \"\"."""
    env = tmp_path / ".env"
    env.write_text('PORT=8123\n'
                   '#MASTER_API_KEY=comentada-no-cuenta\n'
                   'MASTER_API_KEY="abc123"\n', encoding="utf-8")
    assert _leer_env_backend(env) == (8123, "abc123")
    assert _leer_env_backend(tmp_path / "noexiste.env") == (8000, "")


def test_main_default_usa_http_y_modo_local_avisa(monkeypatch, capsys):
    """main() sin flags sondea por HTTP (modo http); con --modo-local pasa
    modo local Y advierte del proceso duplicado en stderr."""
    vistos = []

    async def doble_sondar(service, catalogo_fn=None, modo="http"):
        vistos.append((service, modo))
        return {"service": service, "server_info": {}, "tools": [],
                "error": "sin backend en pruebas"}

    monkeypatch.setattr("sonda_capacidades_nombres.sondar_mcp", doble_sondar)
    assert main([]) == 0
    assert vistos == [("google-flow", "http"), ("notebooklm", "http")]
    vistos.clear()
    assert main(["--modo-local"]) == 0
    assert ("google-flow", "local") in vistos
    assert "DUPLICADOS" in capsys.readouterr().err.upper()


def test_informe_guarda_inputschema_completo():
    """Y2: el resumen del informe lleva la description COMPLETA y el
    inputSchema ÍNTEGRO de cada tool (antes: 140 chars y sin esquema)."""
    desc = ("Añade una nota de texto al cuaderno indicado. " * 6).strip()
    schema = {"type": "object",
              "properties": {"notebook_id": {}, "text": {}, "title": {}}}
    from sonda_capacidades_nombres import _resumen
    res = _resumen("notebooklm", {
        "server_info": {}, "error": "",
        "tools": [{"name": "notebook_add_text", "description": desc,
                   "inputSchema": schema}]})
    (tool,) = res["tools"]
    assert tool["description"] == desc and tool["inputSchema"] == schema


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── Q2 · q6/q7: generación con destino y proyecto activo ─────────────

FLOW_Q6_OK = [
    {"name": "flow_generate_image", "description": "genera imagen",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"},
                                    "project_id": {"type": "string"}}}},
    {"name": "flow_generate_video", "description": "genera video",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"},
                                    "project_id": {"type": "string"}}}},
    {"name": "flow_upload_file", "description": "sube archivo",
     "inputSchema": {"type": "object",
                     "properties": {"file": {"type": "string"},
                                    "destino": {"type": "string"}}}},
]

FLOW_Q6_MIXTO = [
    {"name": "flow_generate_image", "description": "genera imagen",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"},
                                    "project_id": {"type": "string"}}}},
    {"name": "flow_generate_video", "description": "genera video",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"}}}},
]

FLOW_Q7_SI = [
    {"name": "flow_new_project",
     "description": "Crea un proyecto y cambia el proyecto activo de la sesión",
     "inputSchema": {"type": "object", "properties": {}}},
]

FLOW_Q7_NO = [
    {"name": "flow_new_project",
     "description": "Crea un proyecto sin cambiar el proyecto activo actual",
     "inputSchema": {"type": "object", "properties": {}}},
]

FLOW_Q7_MUDA = [
    {"name": "flow_new_project", "description": "Crea un proyecto",
     "inputSchema": {"type": "object", "properties": {}}},
]


def test_q6_generacion_con_destino_es_soportado():
    """q6: TODAS las herramientas de generación presentes aceptan destino."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q6_OK))
    q6 = r["q6_flow_generacion_destino"]
    assert q6["veredicto"] == SOPORTADO
    assert "project_id" in q6["detalle"] and "destino" in q6["detalle"]


def test_q6_destino_mixto_es_no_soportado():
    """q6: si UNA sola no acepta destino, la generación no es dirigible de
    forma uniforme → NO_SOPORTADO, y el detalle dice cuál falla."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q6_MIXTO))
    q6 = r["q6_flow_generacion_destino"]
    assert q6["veredicto"] == NO_SOPORTADO
    assert "flow_generate_video" in q6["detalle"]


def test_q6_sin_herramientas_de_generacion_es_not_demonstrated():
    """q6: catálogo sin herramientas de generación → NOT_DEMONSTRATED."""
    r = _por_id(analizar_tools("google-flow", FLOW_SIN_NOMBRE))
    assert r["q6_flow_generacion_destino"]["veredicto"] == PEND


def test_q6_catalogo_ajeno_queda_not_demonstrated():
    """q6 es de Flow: con catálogo de NotebookLM → NOT_DEMONSTRATED."""
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q6_flow_generacion_destino"]["veredicto"] == PEND


def test_q7_cambia_activo_con_evidencia_en_descripcion():
    """q7: SOPORTADO solo con evidencia explícita en la descripción."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q7_SI))
    assert r["q7_flow_new_project_cambia_activo"]["veredicto"] == SOPORTADO
    assert "proyecto activo" in r["q7_flow_new_project_cambia_activo"]["detalle"]


def test_q7_declara_que_no_cambia_es_no_soportado():
    r = _por_id(analizar_tools("google-flow", FLOW_Q7_NO))
    assert r["q7_flow_new_project_cambia_activo"]["veredicto"] == NO_SOPORTADO


def test_q7_descripcion_muda_es_not_demonstrated():
    """q7 es CONDUCTA, no esquema: descripción sin evidencia → honesto
    NOT_DEMONSTRATED (jamás se inventa el comportamiento)."""
    r = _por_id(analizar_tools("google-flow", FLOW_Q7_MUDA))
    assert r["q7_flow_new_project_cambia_activo"]["veredicto"] == PEND


def test_q6_q7_catalogo_vacio_y_cruzadas():
    """Invariantes conservados: catálogo vacío → PEND; catálogo de
    NotebookLM no responde preguntas de Flow (q6/q7 incluidas)."""
    for servicio in ("google-flow", "notebooklm"):
        r = _por_id(analizar_tools(servicio, []))
        assert r["q6_flow_generacion_destino"]["veredicto"] == PEND
        assert r["q7_flow_new_project_cambia_activo"]["veredicto"] == PEND
    r = _por_id(analizar_tools("notebooklm", NLM_OK))
    assert r["q6_flow_generacion_destino"]["veredicto"] == PEND
    assert r["q7_flow_new_project_cambia_activo"]["veredicto"] == PEND


def test_informe_guardado_incluye_q6_y_q7(tmp_path):
    """El informe de la sonda (--salida → sonda_nombres.json) lleva las 7
    preguntas: leer_sonda (q1) y el disparo de Q3 (q7) pueden leerlas."""
    import json

    informe = {"servicios": {"google-flow": {"preguntas": analizar_tools(
        "google-flow", FLOW_Q7_SI + FLOW_Q6_OK)}}}
    ruta = tmp_path / "sonda_nombres.json"
    ruta.write_text(json.dumps(informe, ensure_ascii=False), encoding="utf-8")
    ids = {p["id"] for p in informe["servicios"]["google-flow"]["preguntas"]}
    assert {"q1_flow_proyecto_nombre", "q6_flow_generacion_destino",
            "q7_flow_new_project_cambia_activo"} <= ids
