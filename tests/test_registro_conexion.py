# -*- coding: utf-8 -*-
"""PASO 3 · Conexión con Flow APAGADA por defecto + GET /api/registro.

Hermético: la creación de proyecto es SIEMPRE un doble (nunca Flow real);
el endpoint se ejerce con httpx.ASGITransport sobre la app real, con
OUTPUT_DIR/DATA_DIR aislados. Sin cambios visuales en el panel.

Ejecutar: python3 -m pytest tests/test_registro_conexion.py -q
"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
