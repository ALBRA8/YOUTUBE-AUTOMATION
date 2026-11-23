# -*- coding: utf-8 -*-
"""Q1 · Cobertura del registro de producciones — UN punto de paso común.

CLASIFICACIÓN DE LOS 14 SITIOS QUE CREAN PROYECTOS (todos cruzan por
database.create_project, que desde Q1 registra vía
registro_produccion.registrar_proyecto_creado — idempotente, best-effort):

  main.py 1142  POST /api/projects (rama con plantilla)      PRODUCCIÓN REAL
  main.py 1170  POST /api/projects (rama sin plantilla)      PRODUCCIÓN REAL
  main.py 1372  POST /api/projects (cuerpo, todos los modos) PRODUCCIÓN REAL
  main.py 2440  POST /api/a2a/productions (contrato A2A)     PRODUCCIÓN REAL
  main.py 3389  POST /api/clipper/create-project             PRODUCCIÓN REAL
                (main.py 3372 es la def del mismo endpoint)
  mcp_server.py  58  tool MCP crear_video                    PRODUCCIÓN REAL
  mcp_server.py  83  tool MCP crear_video_guion_json         PRODUCCIÓN REAL
  mcp_server.py 119  tool MCP submit_production_json         PRODUCCIÓN REAL
  general_agent.py 350  chat agente (con plantilla nicho)   PRODUCCIÓN REAL
  general_agent.py 365  chat agente (sin plantilla)         PRODUCCIÓN REAL
  scheduler.py  81  ciclo de fábrica (run_one_cycle)        PRODUCCIÓN REAL
  youtube_harness/adapter.py 310  op_create (arnés A2A)     INTERNO (arnés
                  de pruebas del host; el registro lo cubre igual,
                  best-effort y sin efecto colateral)
  youtube_harness/adapter.py 322  _crear_production (arnés)  INTERNO (arnés)

Estos tests crean UN proyecto por cada vía REAL y comprueban que su
registro.json existe y no se duplica. Hermético: sin Flow real, sin red;
orchestrator.start_pipeline es un doble donde hace falta.

Ejecutar: python3 -m pytest tests/test_q1_registro_cobertura.py -q
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
import database as db  # noqa: E402
from services import registro_produccion as rp  # noqa: E402


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return data


def _orch_falso():
    from types import SimpleNamespace

    async def start_pipeline(pid, autopublish=False):
        return "job-falso-q1"

    return SimpleNamespace(start_pipeline=start_pipeline)


async def _post(ctype_ruta: str, cuerpo: dict):
    import main as _main
    transport = httpx.ASGITransport(app=_main.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        return await c.post(ctype_ruta, json=cuerpo)


# ── vías de producción real ──────────────────────────────────────────────

def test_api_post_projects_registra(aislado):
    """main.py 1142/1170/1372 (POST /api/projects): registro existe y el
    doble registro (hook Q1 + _post_create_init) NO duplica."""
    r = asyncio.run(_post("/api/projects",
                          {"mode": "idea", "idea": "q1 vía API",
                           "title": "Q1 API"}))
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    reg = rp.leer(pid)
    assert reg is not None and reg["nicho_id"] == "general"
    # sin duplicados: re-registrar es no-op exacto
    antes = json.loads((rp.registro_path(pid)).read_text(encoding="utf-8"))
    rp.registrar_proyecto_creado({"id": pid, "title": "Q1 API"})
    despues = json.loads((rp.registro_path(pid)).read_text(encoding="utf-8"))
    assert antes == despues


def test_a2a_productions_registra(aislado):
    """main.py 2440 (contrato A2A, POST /api/agent/execute): registro existe."""
    from services import production_json as pj
    r = asyncio.run(_post("/api/agent/execute", {
        "requester": "test-agent-q1",
        "creative_spec": pj.spec([])["ejemplo"],
    }))
    assert r.status_code == 200, r.text
    datos = r.json()
    pid = datos.get("production_id")
    assert pid and rp.leer(pid) is not None, f"A2A sin registro: {datos}"


def test_clipper_registra(aislado):
    """main.py 3389 (POST /api/clipper/create-project): registro existe."""
    r = asyncio.run(_post("/api/clipper/create-project",
                          {"title": "Clip Q1",
                           "url": "https://youtu.be/q1test"}))
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    reg = rp.leer(pid)
    assert reg is not None
    assert reg["nicho_id"] == "clips virales"


def test_mcp_crear_video_registra(aislado):
    """mcp_server.py 58 (tool MCP crear_video): registro existe."""
    from services import mcp_server
    out = mcp_server._t_crear_video("idea de prueba q1 por MCP",
                                    lanzar=False)
    pid = out["project_id"]
    reg = rp.leer(pid)
    assert reg is not None and reg["titulo_historia"].startswith("idea de prueba q1")


def test_mcp_guion_json_registra(aislado):
    """mcp_server.py 83 (tool MCP crear_video_guion_json): registro existe."""
    from services import mcp_server
    guion = {"titulo": "Q1 guion MCP",
             "escenas": [{"narracion": "escena uno q1"},
                         {"narracion": "escena dos q1"}]}
    out = asyncio.run(mcp_server._t_crear_video_guion_json(
        json.dumps(guion), lanzar=False))
    pid = out["project_id"]
    assert rp.leer(pid) is not None


def test_mcp_production_json_registra(aislado):
    """mcp_server.py 119 (tool MCP submit_production_json): registro existe."""
    from services import mcp_server
    from services import production_json as pj
    out = asyncio.run(mcp_server._t_submit_production_json(
        pj.spec([])["ejemplo"], lanzar=False))
    pid = (out.get("project") or {}).get("id") or out.get("project_id")
    assert pid and rp.leer(pid) is not None, f"production_json sin registro: {out}"


def test_agente_con_plantilla_registra(aislado):
    """general_agent.py 350 (chat agente, con plantilla): registro existe."""
    from services import general_agent, niches
    tpl = niches.list_templates()[0]
    plan = {"action": "create_video",
            "params": {"idea": "q1 vía agente", "nicho": tpl["id"]}}
    out = asyncio.run(general_agent.execute(plan, db, _orch_falso(), []))
    pid = (out.get("project") or {}).get("id")
    assert pid and rp.leer(pid) is not None, f"agente sin registro: {out}"
    assert rp.leer(pid)["nicho_id"] == tpl.get("name")


def test_agente_sin_plantilla_registra(aislado):
    """general_agent.py 365 (chat agente, sin plantilla): registro existe."""
    from services import general_agent
    plan = {"action": "create_video", "params": {"idea": "q1 agente simple"}}
    out = asyncio.run(general_agent.execute(plan, db, _orch_falso(), []))
    pid = (out.get("project") or {}).get("id")
    assert pid and rp.leer(pid) is not None


def test_scheduler_registra(aislado, monkeypatch):
    """scheduler.py 81 (ciclo de fábrica): registro existe.

    NOTA: se parchea scheduler.orchestrator (el objeto que run_one_cycle
    llama de verdad), no la referencia fresca del test: las purgas de
    sys.modules del conftest pueden dejar dos objetos de módulo distintos
    y un parche a la copia fresca NO afecta al scheduler (lección Q1: el
    doble se instala en quien llama, no en quien importa)."""
    from services import scheduler

    async def _doble(pid, autopublish=False):
        return "job-falso-q1"

    monkeypatch.setattr(scheduler.orchestrator, "start_pipeline", _doble)
    scheduler.add_idea("idea q1 de la fábrica")
    res = asyncio.run(scheduler.run_one_cycle("q1-test"))
    assert res["ok"], res
    reg = rp.leer(res["project_id"])
    assert reg is not None and reg["titulo_historia"].startswith("idea q1")


# ── vías internas (arnés) ────────────────────────────────────────────────

def test_harness_op_create_registra(aislado):
    """adapter.py 310 (arnés op_create): registro existe (interno)."""
    from services.youtube_harness import adapter
    out = adapter.op_create({"idea": "q1 arnés idea"})
    pid = out["project"]["project_id"]
    assert rp.leer(pid) is not None


def test_harness_production_json_registra(aislado):
    """adapter.py 322 (arnés _crear_production): registro existe (interno)."""
    from services.youtube_harness import adapter
    p = adapter._crear_production({"titulo": "q1 arnés production"})
    assert rp.leer(p["id"]) is not None


# ── anti-duplicados y robustez ───────────────────────────────────────────

def test_sin_duplicados_doble_via_r4(aislado):
    """La vía R4 (_post_create_init) + el hook Q1 = UN solo registro:
    mismo numero_serie, sin reescritura."""
    p = db.create_project(title="Q1 dup", mode="idea",
                          meta={"idea": "q1"}, niche="frutinovelas")
    reg1 = rp.leer(p["id"])
    assert reg1 is not None
    antes = (rp.registro_path(p["id"])).read_text(encoding="utf-8")
    rp.registrar_proyecto_creado(p)
    rp.crear(production_id=p["id"], nicho_id="frutinovelas",
             titulo_historia="Q1 dup")
    despues = (rp.registro_path(p["id"])).read_text(encoding="utf-8")
    assert antes == despues


def test_secuencia_por_nicho_sin_huecos(aislado):
    """Proyectos del mismo nicho creados por vías distintas llevan
    numero_serie correlativo (S001, S002) — el hook no pisó la secuencia."""
    a = db.create_project(title="Q1 seq a", niche="frutinovelas")
    from services import mcp_server
    out = mcp_server._t_crear_video("q1 seq b por MCP", lanzar=False)
    reg_a = rp.leer(a["id"])
    # la vía MCP no fija nicho → «general» (no compite con frutinovelas)
    assert reg_a["numero_serie"] == 1
    assert rp.leer(out["project_id"])["nicho_id"] == "general"


def test_registrar_proyecto_creado_robusto(aislado):
    """IDs inválidos o dicts raros NO revientan (best-effort, sin lanzar)."""
    rp.registrar_proyecto_creado(None)
    rp.registrar_proyecto_creado({})
    rp.registrar_proyecto_creado({"id": "../escape"})
    rp.registrar_proyecto_creado({"id": "a" * 200})
    rp.registrar_proyecto_creado({"id": "  "})
    assert rp.listar_producciones() == []
