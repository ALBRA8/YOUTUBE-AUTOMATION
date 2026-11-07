# -*- coding: utf-8 -*-
"""Q3 · Disparador de la sincronización con Flow (fase Flow → registro).

El disparo vive en flow_jobs.enqueue_project (el punto donde EMPIEZA la
fase Flow de una producción — común al endpoint HTTP /api/extension/flow/
jobs/enqueue y a la tool MCP flow_encolar). Va fire-and-forget en hilo
(asyncio.to_thread desde loop; hilo daemon desde contexto síncrono) porque
el adaptador R5 usa asyncio.run y no puede correr dentro de un event loop.

Casos con dobles de MCP (NUNCA Flow real): flag apagado, id devuelto,
sin id, idempotencia. Además: q7 (sonda Q2) decide si se anota la
limitación de dirección de la generación.

Ejecutar: python3 -m pytest tests/test_q3_disparo_flow.py -q
"""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
from services import flow_jobs  # noqa: E402
from services import flow_mcp_client as fmc  # noqa: E402
from services import registro_produccion as rp  # noqa: E402


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return data


def _sonda(ruta, q1="NOT_DEMONSTRATED", d1="sin catálogo",
           q7="NOT_DEMONSTRATED", d7="descripción muda"):
    """Escribe un informe de sonda INT-093 con q1 y q7."""
    informe = {"servicios": {"google-flow": {"preguntas": [
        {"id": "q1_flow_proyecto_nombre", "veredicto": q1, "detalle": d1},
        {"id": "q7_flow_new_project_cambia_activo",
         "veredicto": q7, "detalle": d7},
    ]}}}
    ruta.write_text(json.dumps(informe), encoding="utf-8")
    return ruta


def _doble_new_project(llamadas, pid="flow-abc", fallo=None):
    async def doble(timeout=30.0, name=None, name_prop="name"):
        llamadas.append((name, name_prop))
        if fallo is not None:
            raise fallo
        return pid
    return doble


# ── casos exigidos (con dobles) ──────────────────────────────────────────

def test_flag_apagado_no_toca_nada(aislado, monkeypatch):
    """FLOW_REGISTRO_SYNC=0 (default): ni MCP ni registro — no cambia nada."""
    assert config.FLOW_REGISTRO_SYNC is False
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project", _doble_new_project(llamadas))
    antes = rp.leer("P1")
    res = rp.disparo_sync_flow("P1")
    assert res["estado"] == "APAGADO"
    assert llamadas == []
    assert rp.leer("P1") == antes          # registro intacto


def test_id_devuelto_registra_y_anota_limitacion_q7(aislado, tmp_path,
                                                    monkeypatch):
    """Flag activo + MCP entrega id → flow_project_id guardado; como q7 no
    está demostrado, la generación NO se redirige y queda la limitación."""
    sonda = _sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P1", "frutinovelas", "La prueba de Q3")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project", _doble_new_project(llamadas))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    assert res["estado"] == "VINCULADO"
    assert res["flow_project_id"] == "flow-abc"
    reg = rp.leer("P1")
    assert reg["flow_project_id"] == "flow-abc"
    assert rp.LIMITACION_Q7 in reg["limitaciones"]


def test_q7_soportado_no_anota_limitacion_de_direccion(aislado, tmp_path,
                                                       monkeypatch):
    """q7 SOPORTADO (evidencia de la sonda): id registrado SIN la limitación
    de dirección (la de nombre de q1 sí puede estar — veredictos separados)."""
    sonda = _sonda(tmp_path / "sonda_nombres.json", q7="SOPORTADO",
                   d7="declara que cambia el proyecto activo")
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project", _doble_new_project(llamadas))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    assert res["estado"] == "VINCULADO"
    assert rp.leer("P1")["flow_project_id"] == "flow-abc"
    assert rp.LIMITACION_Q7 not in rp.leer("P1")["limitaciones"]


def test_sin_id_deja_error_y_sin_direccion_falsa(aislado, tmp_path,
                                                 monkeypatch):
    """El MCP no entrega id → estado ERROR (R1), flow_project_id None y
    NINGUNA limitación de dirección (no hay proyecto que dirigir)."""
    sonda = _sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project", _doble_new_project(llamadas, pid="  "))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    assert res["estado"] == "ERROR"
    assert res["flow_project_id"] is None
    reg = rp.leer("P1")
    assert reg["flow_project_id"] is None
    assert rp.LIMITACION_Q7 not in reg["limitaciones"]


def test_idempotente_segundo_disparo_no_recrea(aislado, tmp_path, monkeypatch):
    """Dos disparos → UNA sola llamada al MCP; el segundo es YA_VINCULADO y
    la limitación q7 no se duplica."""
    sonda = _sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project", _doble_new_project(llamadas))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    r1 = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    r2 = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    assert r1["estado"] == "VINCULADO"
    assert r2["estado"] == "YA_VINCULADO"
    assert len(llamadas) == 1
    assert rp.leer("P1")["limitaciones"].count(rp.LIMITACION_Q7) == 1


def test_excepcion_mcp_no_revienta_disparo(aislado, tmp_path, monkeypatch):
    """El MCP explota → el disparo NO propaga: estado ERROR (dato, R1)."""
    sonda = _sonda(tmp_path / "sonda_nombres.json")
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []
    monkeypatch.setattr(fmc, "new_project",
                        _doble_new_project(llamadas,
                                           fallo=fmc.FlowMCPError("boom")))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = rp.disparo_sync_flow("P1", ruta_sonda=sonda)
    assert res["estado"] == "ERROR"
    assert rp.leer("P1")["flow_project_id"] is None


def test_registro_inexistente_no_revienta(aislado, monkeypatch):
    """Sin registro de la producción → ERROR_DISPARO, sin lanzar."""
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = rp.disparo_sync_flow("NO-EXISTE-Q3", sinc_activa=True)
    assert res["estado"] == "ERROR_DISPARO"


# ── cableado en flow_jobs (fire-and-forget, sin bloquear) ────────────────

def test_programacion_contexto_sincrono_usa_hilo(aislado, monkeypatch):
    """Sin event loop → hilo daemon; el disparo programado llega a ejecutar."""
    llamado = threading.Event()
    recibidos = []

    def falso_disparo(pid):
        recibidos.append(pid)
        llamado.set()

    monkeypatch.setattr(flow_jobs, "_disparo_sync", falso_disparo)
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    flow_jobs._programar_disparo_sync("P1")
    assert llamado.wait(timeout=5)
    assert recibidos == ["P1"]


def test_programacion_contexto_async_usa_to_thread(aislado, monkeypatch):
    """Con event loop → create_task(asyncio.to_thread(...)); la tarea queda
    referenciada (anti-GC) y ejecuta sin bloquear al llamador."""
    llamado = threading.Event()

    def falso_disparo(pid):
        llamado.set()

    monkeypatch.setattr(flow_jobs, "_disparo_sync", falso_disparo)
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)

    async def escena():
        flow_jobs._programar_disparo_sync("P2")
        tareas = list(flow_jobs._TAREAS_DISPARO)
        assert tareas, "la tarea debía quedar programada"
        await asyncio.gather(*tareas)   # determinista: espera solo la nuestra

    asyncio.run(escena())
    assert llamado.wait(timeout=5)
    assert not flow_jobs._TAREAS_DISPARO   # el done_callback limpió


def test_programacion_flag_apagado_no_programa_nada(aislado, monkeypatch):
    """Flag apagado: ni hilo ni tarea (el gate vive también en el disparo)."""
    llamado = threading.Event()
    monkeypatch.setattr(flow_jobs, "_disparo_sync",
                        lambda pid: llamado.set())
    assert config.FLOW_REGISTRO_SYNC is False
    flow_jobs._programar_disparo_sync("P3")
    time.sleep(0.2)
    assert not llamado.is_set()


def test_enqueue_project_dispara_la_sincronizacion(aislado, monkeypatch):
    """E2E del punto exacto: enqueue (fase Flow) dispara el disparo del
    registro una vez la cola quedó generada."""
    p = db.create_project(title="Q3 e2e", mode="idea", meta={"idea": "q3"})
    db.replace_scenes(p["id"], [{"title": "S1", "narration": "una sola escena",
                                 "image_prompt": "a lone lighthouse"}])
    llamado = threading.Event()
    vistos = []
    monkeypatch.setattr(flow_jobs, "_disparo_sync",
                        lambda pid: (vistos.append(pid), llamado.set()))
    monkeypatch.setattr(config, "FLOW_REGISTRO_SYNC", True)
    res = flow_jobs.enqueue_project(p["id"])
    assert res["ok"] is True
    assert llamado.wait(timeout=5)
    assert vistos == [p["id"]]


def test_enqueue_project_flag_apagado_no_programa(aislado, monkeypatch):
    """Flag apagado (default): enqueue NO programa disparo — no cambia nada."""
    p = db.create_project(title="Q3 off", mode="idea", meta={"idea": "q3 off"})
    db.replace_scenes(p["id"], [{"title": "S1", "narration": "escena"}])
    llamado = threading.Event()
    monkeypatch.setattr(flow_jobs, "_disparo_sync",
                        lambda pid: llamado.set())
    assert config.FLOW_REGISTRO_SYNC is False
    res = flow_jobs.enqueue_project(p["id"])
    assert res["ok"] is True
    time.sleep(0.2)
    assert not llamado.is_set()
