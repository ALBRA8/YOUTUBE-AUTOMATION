# -*- coding: utf-8 -*-
"""U1 · Agregador de estado SOLO LECTURA del «Ecosistema Google».

GET /api/mcp/resumen calcula, con lo que YA devuelven
/api/mcp/status (manager.status) y google_login_status, un semáforo
humano por pieza — chrome (CDP 9333), flow, notebooklm y cuaderno
seleccionado — más «listo_para_pipeline» y «siguiente_paso» en español
claro. «todo_conectado» SOLO es True si TODAS las piezas requeridas
están ok (adiós al badge que mentía con una sola pieza en verde).

Hermético: dobles para mcp_manager (nunca se conecta nada), sin red,
sin Chrome real, sin NotebookLM real. El servicio de conexión
(mcp_manager/GoogleFlowMCP) queda intacto: esto es solo lectura.

Ejecutar: python3 -m pytest tests/test_u1_mcp_resumen.py -q
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
from services.mcp_resumen import resumen_ecosistema  # noqa: E402

# ── dobles reutilizables (la forma EXACTA que sirven los endpoints) ──────

SVC_OK = {"state": "connected", "auth": "ok", "tools": [{"name": "t1"}],
          "server_info": {"name": "fake", "version": "1.0"}, "last_error": ""}
SVC_AUTH = {"state": "auth_required", "auth": "auth_required", "tools": [],
            "server_info": {}, "last_error": "sesión expirada"}


def _svcs(flow=SVC_OK, nblm=SVC_OK):
    """El CONTENIDO de la clave «services» de /api/mcp/status (lo que
    resumen_ecosistema espera como primer argumento)."""
    return {"google-flow": flow, "notebooklm": nblm}


def _status(flow=SVC_OK, nblm=SVC_OK):
    return {"services": _svcs(flow, nblm)}


def _gsess(chrome_up=True, port=9333):
    return {"cdp_port": port, "chrome_up": chrome_up, "profile_dir": "/p",
            "profile_exists": True, "flow_cdp_port": port,
            "shared_with_flow": True, "notebooklm_storage": {"exists": True}}


# ── 1 · función pura: los 4 escenarios del punto ─────────────────────────

def test_chrome_caido_todo_lo_demas_ok():
    """Chrome caído → pieza chrome en rojo, «todo conectado» False y el
    siguiente paso manda a abrir Chrome / Conectar todo (no miente)."""
    r = resumen_ecosistema(_svcs(), _gsess(chrome_up=False),
                           notebook_id="nb-1")
    assert r["piezas"]["chrome"]["ok"] is False
    assert "CDP 9333" in r["piezas"]["chrome"]["detalle"]
    assert r["piezas"]["flow"]["ok"] is True
    assert r["piezas"]["notebooklm"]["ok"] is True
    assert r["piezas"]["cuaderno"]["ok"] is True
    assert r["todo_conectado"] is False
    assert r["listo_para_pipeline"] is False
    assert "Conectar todo" in r["siguiente_paso"]
    assert "Chrome" in r["siguiente_paso"]


def test_flow_y_notebooklm_ok_sin_cuaderno():
    """NotebookLM conectado pero sin cuaderno elegido → la pieza cuaderno
    no miente («el desplegable aparece vacío») y pide listar/elegir."""
    r = resumen_ecosistema(_svcs(), _gsess(chrome_up=True),
                           notebook_id=None)
    assert r["piezas"]["chrome"]["ok"] is True
    assert r["piezas"]["flow"]["ok"] is True
    assert r["piezas"]["notebooklm"]["ok"] is True
    assert r["piezas"]["cuaderno"]["ok"] is False
    assert "vacío" in r["piezas"]["cuaderno"]["detalle"] or \
           "sin cuaderno" in r["piezas"]["cuaderno"]["detalle"]
    assert r["todo_conectado"] is False
    assert "cuaderno" in r["siguiente_paso"].lower()
    assert "Listar" in r["siguiente_paso"]       # acción concreta, no «conecta»


def test_todo_ok_es_el_unico_todo_conectado():
    """Las 4 piezas ok → listo_para_pipeline True y «Todo listo…»."""
    r = resumen_ecosistema(_svcs(), _gsess(chrome_up=True),
                           notebook_id="nb-abc-123")
    assert all(p["ok"] for p in r["piezas"].values())
    assert r["todo_conectado"] is True
    assert r["listo_para_pipeline"] is True
    assert r["siguiente_paso"].startswith("Todo listo")
    # toda pieza ok NO arrastra «accion_siguiente» (nada por hacer)
    assert all(p["accion_siguiente"] == "" for p in r["piezas"].values())


def test_notebooklm_auth_required_con_error():
    """auth_required con last_error → detalle humano que incluye el error
    y acción concreta (Conectar todo / Conectar)."""
    r = resumen_ecosistema(_svcs(nblm=SVC_AUTH), _gsess(),
                           notebook_id="nb-1")
    nb = r["piezas"]["notebooklm"]
    assert nb["ok"] is False
    assert "auth_required" in nb["detalle"]
    assert "sesión expirada" in nb["detalle"]
    assert "Conectar" in nb["accion_siguiente"]
    assert r["todo_conectado"] is False


def test_robustez_dicts_vacios_no_explota():
    """Sin datos (status/gsess vacíos) → sin excepción y honesto: nada ok."""
    r = resumen_ecosistema(_svcs(flow={"state": "disconnected"},
                                 nblm={"state": "disconnected"}),
                           {}, notebook_id=None)
    assert all(p["ok"] is False for p in r["piezas"].values())
    assert r["todo_conectado"] is False
    # el siguiente paso es el del PRIMER eslabón roto (Chrome, lo físico)
    assert "Chrome" in r["siguiente_paso"]


def test_cuaderno_sin_notebooklm_no_pide_listar():
    """Sin NotebookLM conectado, la acción del cuaderno NO puede ser
    «Listar» (aún no hay sesión): remite a conectar primero."""
    r = resumen_ecosistema(_svcs(nblm={"state": "disconnected",
                                       "tools": [], "last_error": ""}),
                           _gsess(), notebook_id=None)
    assert r["piezas"]["cuaderno"]["ok"] is False
    assert "Listar" not in r["siguiente_paso"]


# ── 2 · endpoint GET /api/mcp/resumen (solo lectura, con dobles) ─────────

async def _llama(ruta: str):
    import main as _main
    transport = httpx.ASGITransport(app=_main.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        return await c.get(ruta)


@pytest.fixture()
def dobles(monkeypatch):
    """Dobles de manager.status/google_login_status + guardia: si ALGUIEN
    intenta CONECTAR algo, el test falla (esto es SOLO lectura)."""
    import main as _main
    llamadas = {"connect": 0}

    async def status():
        return _status()

    async def gsess():
        return _gsess(chrome_up=True)

    async def connect_prohibido(*a, **k):
        llamadas["connect"] += 1
        raise AssertionError("resumen NO debe conectar nada (solo lectura)")

    monkeypatch.setattr(_main._mcpm.manager, "status", status)
    monkeypatch.setattr(_main._mcpm.manager, "google_login_status", gsess)
    monkeypatch.setattr(_main._mcpm.manager, "connect", connect_prohibido)
    monkeypatch.setattr(_main._mcpm.manager, "connect_all_google",
                        connect_prohibido)
    return llamadas


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return data


def test_endpoint_forma_completa(dobles):
    r = asyncio.run(_llama("/api/mcp/resumen"))
    assert r.status_code == 200, r.text
    js = r.json()
    assert set(js["piezas"]) == {"chrome", "flow", "notebooklm", "cuaderno"}
    for p in js["piezas"].values():
        assert set(p) == {"ok", "detalle", "accion_siguiente"}
        assert isinstance(p["ok"], bool)
        assert isinstance(p["detalle"], str) and p["detalle"]
    assert isinstance(js["listo_para_pipeline"], bool)
    assert isinstance(js["todo_conectado"], bool)
    assert isinstance(js["siguiente_paso"], str) and js["siguiente_paso"]
    assert dobles["connect"] == 0          # jamás conectó


def test_endpoint_sin_cuaderno_esta_honesto(dobles):
    """Con todo conectado pero sin cuaderno, listo_para_pipeline es False
    y el siguiente paso dice qué hacer (fin del estado mentiroso)."""
    r = asyncio.run(_llama("/api/mcp/resumen"))
    js = r.json()
    assert js["piezas"]["flow"]["ok"] is True
    assert js["piezas"]["notebooklm"]["ok"] is True
    assert js["piezas"]["cuaderno"]["ok"] is False
    assert js["todo_conectado"] is False
    assert js["listo_para_pipeline"] is False


def test_endpoint_memoria_del_nicho_y_precedencia(dobles, aislado):
    """El cuaderno recordado del nicho alimenta la pieza cuaderno; la
    query notebook_id (elección vigente de la UI) gana a la memoria."""
    rp.registrar_nicho("frutinovelas", "nb-del-nicho-1", "Cuaderno F")
    r = asyncio.run(_llama("/api/mcp/resumen?nicho_id=frutinovelas"))
    js = r.json()
    assert js["piezas"]["cuaderno"]["ok"] is True
    assert "nb-del-nicho-1" in js["piezas"]["cuaderno"]["detalle"]
    # query gana a memoria del nicho
    r2 = asyncio.run(_llama(
        "/api/mcp/resumen?nicho_id=frutinovelas&notebook_id=nb-ui-9"))
    assert "nb-ui-9" in r2.json()["piezas"]["cuaderno"]["detalle"]
    # nicho desconocido → se ignora sin error (honesto)
    r3 = asyncio.run(_llama("/api/mcp/resumen?nicho_id=no-existe"))
    assert r3.status_code == 200
    assert r3.json()["piezas"]["cuaderno"]["ok"] is False


def test_endpoint_fallback_config_notebook(dobles, aislado, monkeypatch):
    """Sin query ni memoria de nicho: usa NOTEBOOKLM_NOTEBOOK_ID de config."""
    monkeypatch.setattr(config, "NOTEBOOKLM_NOTEBOOK_ID", "nb-env-77")
    r = asyncio.run(_llama("/api/mcp/resumen"))
    assert "nb-env-77" in r.json()["piezas"]["cuaderno"]["detalle"]


def test_endpoint_chrome_caido_siguiente_paso_claro(dobles, monkeypatch):
    """Escenario EXACTO del bug: Flow en verde arriba mientras Chrome CDP
    está caído → el resumen NO dice «todo conectado» y manda a Chrome."""
    import main as _main

    async def gsess_caido():
        return _gsess(chrome_up=False)

    monkeypatch.setattr(_main._mcpm.manager, "google_login_status",
                        gsess_caido)
    js = asyncio.run(_llama("/api/mcp/resumen")).json()
    assert js["todo_conectado"] is False
    assert js["piezas"]["chrome"]["ok"] is False
    assert "Conectar todo" in js["siguiente_paso"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
