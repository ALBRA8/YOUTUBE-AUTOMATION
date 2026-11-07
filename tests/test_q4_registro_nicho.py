# -*- coding: utf-8 -*-
"""Q4 · Cuaderno del nicho: endpoints protegidos/validados + propagación.

POST /api/registro/nicho {nicho_id, notebook_id, nombre_cuaderno} y
GET /api/registro/nicho/{nicho_id}. UN cuaderno por nicho, NUNCA por
historia. IDs validados con las MISMAS reglas que registro_path (R2).
propaga_notebook deja de callar: aviso en el log (no «except Exception:
pass»). Auth: heredada del middleware auth_guard de /api/* (se prueba con
MASTER_API_KEY activada). Hermético: sin red, sin NotebookLM real.

Ejecutar: python3 -m pytest tests/test_q4_registro_nicho.py -q
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
import database as db  # noqa: E402
from services import registro_produccion as rp  # noqa: E402


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return data


async def _llama(metodo: str, ruta: str, json_body: dict | None = None,
                 headers: dict | None = None):
    import main as _main
    transport = httpx.ASGITransport(app=_main.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        return await c.request(metodo, ruta, json=json_body, headers=headers)


# ── POST /api/registro/nicho ─────────────────────────────────────────────

def test_post_asigna_y_propaga(aislado):
    rp.crear("P1", "frutinovelas", "Historia uno")
    r = asyncio.run(_llama("POST", "/api/registro/nicho", {
        "nicho_id": "frutinovelas", "notebook_id": "nb-abc-123",
        "nombre_cuaderno": "FRUTINOVELAS · Cuaderno maestro"}))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["ok"] is True and datos["nicho_id"] == "frutinovelas"
    assert datos["nicho"]["notebook_id"] == "nb-abc-123"
    assert datos["propagacion"] == {"propagadas": 1, "omitidas": 0}
    # propagación: la producción del nicho lleva el cuaderno DEL NICHO
    assert rp.leer("P1")["notebook_id_nicho"] == "nb-abc-123"


def test_un_cuaderno_por_nicho_se_reemplaza(aislado):
    """Reasignar el cuaderno del nicho reemplaza (y re-propaga) — nunca un
    cuaderno por historia."""
    rp.crear("P1", "frutinovelas", "a")
    r1 = asyncio.run(_llama("POST", "/api/registro/nicho", {
        "nicho_id": "frutinovelas", "notebook_id": "nb-1",
        "nombre_cuaderno": "Cuaderno v1"}))
    r2 = asyncio.run(_llama("POST", "/api/registro/nicho", {
        "nicho_id": "frutinovelas", "notebook_id": "nb-2",
        "nombre_cuaderno": "Cuaderno v2"}))
    assert r1.status_code == r2.status_code == 200
    assert rp.registro_nicho("frutinovelas")["notebook_id"] == "nb-2"
    assert rp.leer("P1")["notebook_id_nicho"] == "nb-2"


def test_post_valida_ids_como_registro_path(aislado):
    """IDs con las mismas reglas de registro_path (R2): rechaza vacío,
    separadores, '..', absolutas, largos; exige nombre_cuaderno."""
    casos = [
        {"nicho_id": "", "notebook_id": "nb", "nombre_cuaderno": "n"},
        {"nicho_id": "../escape", "notebook_id": "nb", "nombre_cuaderno": "n"},
        {"nicho_id": "a/b", "notebook_id": "nb", "nombre_cuaderno": "n"},
        {"nicho_id": "C:\\win", "notebook_id": "nb", "nombre_cuaderno": "n"},
        {"nicho_id": "n" * 200, "notebook_id": "nb", "nombre_cuaderno": "n"},
        {"nicho_id": "frutinovelas", "notebook_id": "../nb",
         "nombre_cuaderno": "n"},
        {"nicho_id": "frutinovelas", "notebook_id": "x y z",
         "nombre_cuaderno": "n"},
        {"nicho_id": "frutinovelas", "notebook_id": "nb"},
    ]
    for cuerpo in casos:
        r = asyncio.run(_llama("POST", "/api/registro/nicho", cuerpo))
        assert r.status_code == 400, f"{cuerpo} → {r.status_code}"
    assert rp.registro_nicho("frutinovelas") is None


def test_post_nicho_valido_notebook_limpio_no_400(aislado):
    """Los caracteres permitidos ([A-Za-z0-9._-]) pasan la validación."""
    rp.crear("P1", "nicho.q4", "a")
    r = asyncio.run(_llama("POST", "/api/registro/nicho", {
        "nicho_id": "nicho.q4", "notebook_id": "NB_1234.ef",
        "nombre_cuaderno": "Q4 · Cuaderno"}))
    assert r.status_code == 200, r.text


# ── GET /api/registro/nicho/{nicho_id} ──────────────────────────────────

def test_get_nicho_existente_y_404(aislado):
    rp.registrar_nicho("frutinovelas", "nb-1", "Cuaderno")
    r = asyncio.run(_llama("GET", "/api/registro/nicho/frutinovelas"))
    assert r.status_code == 200
    assert r.json() == {"nicho_id": "frutinovelas", "notebook_id": "nb-1",
                        "nombre_cuaderno": "Cuaderno",
                        "actualizado_en": r.json()["actualizado_en"]}
    r404 = asyncio.run(_llama("GET", "/api/registro/nicho/otro-nicho"))
    assert r404.status_code == 404
    # «..» dentro del segmento → 400 por validación (un «..%2F» ni siquiera
    # llega: el enrutado lo rechaza antes con 404 — también rechazado).
    r400 = asyncio.run(_llama("GET", "/api/registro/nicho/esc..ape"))
    assert r400.status_code == 400


# ── auth: misma que el resto de /api (middleware) ────────────────────────

def test_auth_maestra_exige_clave(aislado, monkeypatch):
    """Con MASTER_API_KEY definida, POST/GET del nicho exigen X-API-Key
    (misma auth que el resto de /api: middleware auth_guard). security
    cachea la clave en import → hay que llamar reload() del MISMO objeto
    que la app referencia (main.security — lección Q1: parchea a quien
    llama; las purgas de sys.modules pueden duplicar el módulo)."""
    import main as _main
    sec = _main.security
    monkeypatch.setenv("MASTER_API_KEY", "clave-q4-test")
    sec.reload()
    try:
        r_sin = asyncio.run(_llama("POST", "/api/registro/nicho", {
            "nicho_id": "frutinovelas", "notebook_id": "nb-1",
            "nombre_cuaderno": "Cuaderno"}))
        assert r_sin.status_code == 401
        g_sin = asyncio.run(_llama("GET", "/api/registro/nicho/frutinovelas"))
        assert g_sin.status_code == 401
        r_con = asyncio.run(_llama("POST", "/api/registro/nicho", {
            "nicho_id": "frutinovelas", "notebook_id": "nb-1",
            "nombre_cuaderno": "Cuaderno"},
            headers={"X-API-Key": "clave-q4-test"}))
        assert r_con.status_code == 200
    finally:
        monkeypatch.undo()      # restaura el env ANTES del reload
        sec.reload()            # _key vuelve a vacío para los demás tests


# ── propagación resiliente + propaga_notebook deja de callar ─────────────

def test_propagar_nicho_continua_si_una_produccion_falla(aislado, monkeypatch):
    """Una producción que falla NO corta a las demás (aviso + omitidas)."""
    a = rp.crear("P1", "frutinovelas", "a")
    b = rp.crear("P2", "frutinovelas", "b")
    real = rp.propaga_notebook

    def quebradizo(pid):
        if pid == a["production_id"]:
            raise ValueError("sin registro (simulado)")
        return real(pid)

    monkeypatch.setattr(rp, "propaga_notebook", quebradizo)
    rp.registrar_nicho("frutinovelas", "nb-1", "Cuaderno")
    res = rp.propagar_nicho("frutinovelas")
    assert res == {"propagadas": 1, "omitidas": 1}
    assert rp.leer(b["production_id"])["notebook_id_nicho"] == "nb-1"
    assert rp.leer(a["production_id"])["notebook_id_nicho"] is None


def test_propaga_notebook_registra_el_aviso_en_el_log(aislado, caplog):
    """Q4 · _post_create_init deja de callar: el fallo de propaga_notebook
    queda en el LOG y el flujo sigue (no fatal). Se usa un proyecto SIN
    registro previo para que el bloque R4 de _post_create_init corra (con
    Q1, un proyecto de db.create_project ya nace registrado y ese bloque
    es no-op)."""
    import logging
    import main as _main
    real = rp.propaga_notebook

    def que_explota(pid):
        raise ValueError("sin registro para propagar (simulado)")

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(rp, "propaga_notebook", que_explota)
        with caplog.at_level(logging.WARNING, logger="main"):
            p = _main._post_create_init(
                {"id": "Q4SINREG", "title": "Q4 log",
                 "niche": "frutinovelas", "meta": {}}, None)
        assert p["id"] == "Q4SINREG"
        assert rp.leer("Q4SINREG") is not None   # el registro SÍ se creó
        assert any("propaga_notebook falló" in rec.message
                   for rec in caplog.records), caplog.text
    finally:
        mp.undo()
