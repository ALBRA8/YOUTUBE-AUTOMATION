# -*- coding: utf-8 -*-
"""PASO 3 · Conexión con Flow APAGADA por defecto + GET /api/registro.
R5 · Adaptador real crear_proyecto (flow_mcp_client.new_project) con el
veredicto guardado de la sonda INT-093 (sonda_nombres.json).

Hermético: la creación de proyecto es SIEMPRE un doble (nunca Flow real);
el endpoint se ejerce con httpx.ASGITransport sobre la app real, con
OUTPUT_DIR/DATA_DIR aislados. Sin cambios visuales en el panel.

Ejecutar: python3 -m pytest tests/test_registro_conexion.py -q
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import flow_mcp_client as fmc  # noqa: E402
from services import registro_produccion as rp  # noqa: E402


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return data


def _doble_crear(llamadas, pid="flow-abc"):
    def doble(nombre_flow):
        llamadas.append(nombre_flow)
        return {"flow_project_id": pid, "nombre_observado": nombre_flow}
    return doble


# ── 3.1 · gate APAGADO por defecto ────────────────────────────────────

def test_gate_apagado_por_defecto_no_crea_nada(aislado):
    """config.FLOW_REGISTRO_SYNC=0 (default): ni una llamada al creador."""
    assert config.FLOW_REGISTRO_SYNC is False   # el default es APAGADO
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    res = rp.sincronizar_flow("P1", _doble_crear(llamadas))
    assert res["estado"] == "APAGADO"
    assert llamadas == []
    assert rp.leer("P1")["flow_project_id"] is None


def test_gate_activo_vincula_con_doble(aislado):
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    res = rp.sincronizar_flow("P1", _doble_crear(llamadas),
                              nombres_soportados="SOPORTADO",
                              sinc_activa=True)
    assert res["estado"] == "VINCULADO"
    assert llamadas == ["FRUTINOVELAS · S001 · a"]
    assert rp.leer("P1")["flow_project_id"] == "flow-abc"


def test_gate_lee_config(monkeypatch, aislado):
    """El gate lee config.FLOW_REGISTRO_SYNC (el dueño lo activa con env)."""
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    res = rp.sincronizar_flow("P1", _doble_crear(llamadas))
    assert res["estado"] == "VINCULADO" and len(llamadas) == 1


def test_gate_activo_sigue_siendo_idempotente(aislado):
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    rp.sincronizar_flow("P1", _doble_crear(llamadas), sinc_activa=True)
    res = rp.sincronizar_flow("P1", _doble_crear(llamadas), sinc_activa=True)
    assert res["estado"] == "YA_VINCULADO"
    assert len(llamadas) == 1   # jamás un segundo proyecto


def test_nombre_a_flow_solo_si_sonda_soporta(aislado):
    """Sin veredicto SOPORTADO de la sonda INT-093, el nombre NO se pasa a
    Flow (solo local) y la limitación queda anotada."""
    rp.crear("P1", "frutinovelas", "a")
    rp.sincronizar_flow("P1", _doble_crear([]), nombres_soportados=None,
                        sinc_activa=True)
    reg = rp.leer("P1")
    assert reg["flow_project_nombre_observado"] is None
    assert any("sin sonda" in x for x in reg["limitaciones"])


# ── 3.2 · GET /api/registro (solo lectura) ────────────────────────────

def test_endpoint_registro_lista_producciones(aislado):
    import main as _main
    rp.registrar_nicho("frutinovelas", "nb-1", "NICHO · Frutinovelas")
    rp.crear("P1", "frutinovelas", "La receta del caos")
    llamadas = []
    rp.sincronizar_flow("P1", _doble_crear(llamadas),
                        nombres_soportados="SOPORTADO", sinc_activa=True)

    async def consulta():
        transport = httpx.ASGITransport(app=_main.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            return await c.get("/api/registro")

    r = asyncio.run(consulta())
    assert r.status_code == 200
    datos = r.json()
    producciones = datos["producciones"]
    assert len(producciones) == 1
    p = producciones[0]
    for campo in ("production_id", "nicho_id", "nombre_flow",
                  "flow_project_id", "notebook_id_nicho", "estado"):
        assert campo in p, campo
    assert p["production_id"] == "P1"
    assert p["nicho_id"] == "frutinovelas"
    assert p["flow_project_id"] == "flow-abc"
    assert p["notebook_id_nicho"] == "nb-1"


def test_endpoint_es_solo_lectura(aislado):
    import main as _main
    rp.crear("P1", "frutinovelas", "a")
    antes = (rp.registro_path("P1")).read_text(encoding="utf-8")

    async def consulta():
        transport = httpx.ASGITransport(app=_main.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r1 = await c.get("/api/registro")
            r2 = await c.get("/api/registro")
            return r1.json(), r2.json()

    j1, j2 = asyncio.run(consulta())
    assert j1 == j2
    assert (rp.registro_path("P1")).read_text(encoding="utf-8") == antes


def test_creacion_proyecto_conecta_registro_local_sin_duplicar(aislado):
    """R4 · Al crear un proyecto en main.py se crea registro local. Si ya existe, no se recrea."""
    import main as _main

    async def crear_p():
        transport = httpx.ASGITransport(app=_main.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            return await c.post("/api/projects", json={
                "title": "Aventura Frutal",
                "mode": "idea",
                "nicho": "frutinovelas"
            })

    resp = asyncio.run(crear_p())
    assert resp.status_code == 200
    pdata = resp.json()
    pid = pdata["id"]

    reg = rp.leer(pid)
    assert reg is not None
    assert reg["production_id"] == pid
    assert reg["nicho_id"] == "frutinovelas"
    assert reg["titulo_historia"] == "Aventura Frutal"
    assert reg["numero_serie"] == 1
    assert reg["nombre_flow"] == "FRUTINOVELAS · S001 · Aventura Frutal"

    # Llamar _post_create_init de nuevo con el mismo proyecto no lo recrea
    _main._post_create_init(pdata, None)
    reg2 = rp.leer(pid)
    assert reg2["numero_serie"] == 1
    assert reg2["actualizado_en"] == reg["actualizado_en"]


def test_endpoint_vacio_sin_registros(aislado):
    import main as _main

    async def consulta():
        transport = httpx.ASGITransport(app=_main.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            return await c.get("/api/registro")

    r = asyncio.run(consulta())
    assert r.status_code == 200
    assert r.json() == {"producciones": []}


# ── R5 · adaptador real con el MCP (doble) + sonda INT-093 guardada ───

def _escribe_sonda(ruta: Path, veredicto: str = "SOPORTADO",
                   detalle: str = "flow_new_project acepta 'name' en su esquema") -> Path:
    informe = {"servicios": {"google-flow": {"preguntas": [
        {"id": "q1_flow_proyecto_nombre",
         "pregunta": "¿flow_new_project acepta nombre?",
         "veredicto": veredicto, "detalle": detalle}]}}}
    ruta.write_text(json.dumps(informe), encoding="utf-8")
    return ruta


def _doble_new_project(monkeypatch, llamadas, resultado="flow-777"):
    """Doble del cliente MCP: captura los kwargs y devuelve el resultado
    (o lanza, si `resultado` es una excepción). NUNCA Flow real."""
    async def doble(*args, **kwargs):
        llamadas.append(kwargs)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado
    monkeypatch.setattr(fmc, "new_project", doble)


def test_sonda_ausente_es_not_demonstrated(tmp_path):
    """Sin informe guardado → NOT_DEMONSTRATED (honesto, no se inventa)."""
    sonda = rp.leer_sonda(tmp_path / "no_existe.json")
    assert sonda == {"veredicto": "NOT_DEMONSTRATED", "prop": None}


def test_sonda_corrupta_es_not_demonstrated(tmp_path):
    ruta = tmp_path / "sonda_nombres.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    assert rp.leer_sonda(ruta)["veredicto"] == "NOT_DEMONSTRATED"


def test_sonda_soporata_extrae_la_propiedad_del_esquema(tmp_path):
    ruta = _escribe_sonda(tmp_path / "sonda_nombres.json")
    sonda = rp.leer_sonda(ruta)
    assert sonda == {"veredicto": "SOPORTADO", "prop": "name"}
    # NO_SOPORTADO: veredicto respetado tal cual, sin propiedad
    ruta2 = _escribe_sonda(tmp_path / "no.json", veredicto="NO_SOPORTADO",
                           detalle="no hay tool que encaje")
    sonda2 = rp.leer_sonda(ruta2)
    assert sonda2["veredicto"] == "NO_SOPORTADO" and sonda2["prop"] is None


def test_new_project_envia_el_nombre_solo_si_se_pasa(monkeypatch):
    """El cliente MCP añade el nombre a arguments SOLO cuando llega."""
    llamadas = []

    async def doble_call_tool(tool, arguments, timeout=None, cwd=None):
        llamadas.append((tool, dict(arguments)))
        return "flow-1"

    monkeypatch.setattr(fmc, "call_tool", doble_call_tool)
    assert asyncio.run(fmc.new_project(name="X", name_prop="name")) == "flow-1"
    assert llamadas[-1] == ("flow_new_project", {"name": "X"})
    asyncio.run(fmc.new_project())          # sin nombre → arguments vacío
    assert llamadas[-1] == ("flow_new_project", {})


def test_r5_con_id_y_sonda_soportado_pasa_nombre_y_guarda_id(
        aislado, tmp_path, monkeypatch):
    """R5 caso 'con id': sonda SOPORTADO → el nombre viaja al MCP (doble)
    y el flow_project_id queda guardado en el registro."""
    ruta_sonda = _escribe_sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P5", "frutinovelas", "a")
    llamadas = []
    _doble_new_project(monkeypatch, llamadas, resultado="flow-777")
    res = rp.sincronizar_flow_real("P5", ruta_sonda=ruta_sonda,
                                   sinc_activa=True)
    assert res["estado"] == "VINCULADO"
    reg = rp.leer("P5")
    assert reg["flow_project_id"] == "flow-777"
    assert reg["flow_project_nombre_observado"] == \
        "FRUTINOVELAS · S001 · a"
    assert len(llamadas) == 1
    assert llamadas[0]["name"] == "FRUTINOVELAS · S001 · a"
    assert llamadas[0]["name_prop"] == "name"


def test_r5_sonda_ausente_crea_sin_nombre_y_anota_limitacion(
        aislado, tmp_path, monkeypatch):
    """R5 sin informe de sonda → NOT_DEMONSTRATED: el proyecto se crea SIN
    nombre (el nombre vive solo en local) y la limitación queda anotada."""
    rp.crear("P5", "frutinovelas", "a")
    llamadas = []
    _doble_new_project(monkeypatch, llamadas, resultado="flow-888")
    res = rp.sincronizar_flow_real(
        "P5", ruta_sonda=tmp_path / "ausente.json", sinc_activa=True)
    assert res["estado"] == "VINCULADO"
    assert llamadas[0]["name"] is None        # el nombre NO viajó
    reg = rp.leer("P5")
    assert reg["flow_project_id"] == "flow-888"
    assert reg["flow_project_nombre_observado"] is None
    assert any("NOT_DEMONSTRATED" in x for x in reg["limitaciones"])


def test_r5_idempotente_no_crea_otro_proyecto(aislado, tmp_path,
                                              monkeypatch):
    """R5 caso 'idempotente': registro ya vinculado → NUNCA una segunda
    llamada al MCP (ni un segundo proyecto)."""
    ruta_sonda = _escribe_sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P5", "frutinovelas", "a")
    llamadas = []
    _doble_new_project(monkeypatch, llamadas, resultado="flow-1")
    assert rp.sincronizar_flow_real("P5", ruta_sonda=ruta_sonda,
                                    sinc_activa=True)["estado"] == "VINCULADO"
    res = rp.sincronizar_flow_real("P5", ruta_sonda=ruta_sonda,
                                   sinc_activa=True)
    assert res["estado"] == "YA_VINCULADO"
    assert len(llamadas) == 1
    assert rp.leer("P5")["flow_project_id"] == "flow-1"


def test_r5_mcp_sin_id_deja_error_y_limitacion(aislado, tmp_path,
                                               monkeypatch):
    """R5 caso 'sin id': el MCP (doble) no entrega id → ERROR honesto,
    flow_project_id sigue None y la limitación queda anotada (R1)."""
    rp.crear("P5", "frutinovelas", "a")
    _doble_new_project(monkeypatch, [], resultado="   ")
    res = rp.sincronizar_flow_real("P5",
                                   ruta_sonda=tmp_path / "s.json",
                                   sinc_activa=True)
    assert res["estado"] == "ERROR"
    reg = rp.leer("P5")
    assert reg["flow_project_id"] is None
    assert any("no entrego flow_project_id" in x
               for x in reg["limitaciones"])


def test_r5_mcp_excepcion_deja_error_y_limitacion(aislado, tmp_path,
                                                  monkeypatch):
    """El MCP (doble) lanza FlowMCPError → el adaptador no explota: ERROR
    en el registro + limitación anotada (R1: sin estado falso)."""
    rp.crear("P5", "frutinovelas", "a")
    _doble_new_project(monkeypatch, [],
                       resultado=fmc.FlowMCPError("no autenticado"))
    res = rp.sincronizar_flow_real("P5",
                                   ruta_sonda=tmp_path / "s.json",
                                   sinc_activa=True)
    assert res["estado"] == "ERROR"
    reg = rp.leer("P5")
    assert reg["flow_project_id"] is None
    assert any("no entrego flow_project_id" in x
               for x in reg["limitaciones"])


def test_r5_flag_apagado_no_llama_mcp(aislado, tmp_path, monkeypatch):
    """R5 caso 'flag apagado': FLOW_REGISTRO_SYNC=0 (default) → ni una
    llamada al MCP; el registro queda sin flow_project_id."""
    assert config.FLOW_REGISTRO_SYNC is False
    rp.crear("P5", "frutinovelas", "a")
    llamadas = []
    _doble_new_project(monkeypatch, llamadas, resultado="flow-no")
    res = rp.sincronizar_flow_real("P5", ruta_sonda=tmp_path / "s.json")
    assert res["estado"] == "APAGADO"
    assert llamadas == []
    assert rp.leer("P5")["flow_project_id"] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
