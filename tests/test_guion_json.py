#!/usr/bin/env python3
"""v2.10.2 · Suite de verificación del contrato guion_json (reconstruida).

Corre sin servidor (unidad) contra services/guion_json.py + orchestrator +
mcp_server: contratos, validaciones, alias, fences, sanitización, rama del
orquestador y dispatch MCP.

Copia canónica (fuente de verdad) dentro del repo: el backend se resuelve
relativo al propio repositorio. Esta batería usa la database REAL (SQLite de
desarrollo): crea proyectos de prueba y los borra al final de la corrida.

Uso:  cd yt_automation_v2 && python3 tests/test_guion_json.py
      python3 -m pytest tests/ -q     (cada batería = 1 test pytest)
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _reset_app_modules():
    """Purga de sys.modules los módulos de la app (y cualquier `database`
    fake dejado por otra batería en el mismo proceso, p.ej. bajo pytest),
    para que esta batería importe siempre estado fresco y coherente."""
    for name in [m for m in sys.modules
                 if m == "database"
                 or m.split(".")[0] in ("config", "security", "services",
                                        "pipeline")]:
        sys.modules.pop(name, None)


def main() -> int:
    global OK, FAIL
    OK, FAIL = 0, 0
    _reset_app_modules()

    from services import guion_json as guion_svc  # noqa: E402
    from services.themes import STYLES  # noqa: E402

    ESTILOS = {s["id"] for s in STYLES}
    EJEMPLO = guion_svc.spec([])["ejemplo"]

    print("── 1. spec del contrato")
    spec = guion_svc.spec([s["id"] for s in STYLES])
    check("version 2.11", spec["version"] == "2.11")
    check("campos clave", all(k in spec["campos"] for k in
                              ("titulo", "formato", "estilo", "escenas", "cta", "auto_start")))
    check("campo camara (recetas)", "camara" in spec["campos"])
    check("6 reglas", len(spec["reglas"]) == 6)
    check("ejemplo con 3 escenas", len(spec["ejemplo"]["escenas"]) == 3)

    print("── 2. parse_payload")
    check("dict pasa tal cual", guion_svc.parse_payload(EJEMPLO) is EJEMPLO)
    txt = json.dumps(EJEMPLO, ensure_ascii=False)
    check("str JSON", guion_svc.parse_payload(txt)["titulo"] == "El faro que gritaba")
    check("fences ```json", guion_svc.parse_payload(f"```json\n{txt}\n```")["titulo"]
          == "El faro que gritaba")
    try:
        guion_svc.parse_payload("esto no es json")
        check("JSON inválido rechazado", False)
    except ValueError:
        check("JSON inválido rechazado", True)

    print("── 3. validate")
    g, av = guion_svc.validate(guion_svc.parse_payload(txt), ESTILOS)
    check("3 escenas + CTA = 4", len(g["escenas"]) == 4)
    check("última escena es CTA", g["escenas"][-1]["title"] == "CTA")
    check("formato short", g["formato"] == "short")
    check("sin avisos en ejemplo limpio", not av, str(av))
    check("auto_start False", g["auto_start"] is False)

    # alias EN + fences + formato raro
    alien = {"title": "Prueba alias", "format": "9:16", "style": "no-existe",
             "platforms": ["youtube", "bebo"],
             "scenes": [{"narration": "uno", "image_prompt": "a cat, text"},
                        {"texto": "dos"}],
             "call_to_action": "comenta"}
    g2, av2 = guion_svc.validate(alien, ESTILOS)
    check("alias title→titulo", g2["titulo"] == "Prueba alias")
    check("9:16→short", g2["formato"] == "short")
    check("estilo inválido→auto + aviso", g2["estilo"] == "auto" and
          any("estilo" in a for a in av2))
    check("plataforma basura filtrada", g2["plataformas"] == ["youtube"] and
          any("bebo" in a for a in av2))
    check("image_prompt con texto→sanitizado", g2["escenas"][0]["image_prompt"]
         .endswith("no text"))
    check("alias texto→narracion", g2["escenas"][1]["narration"] == "dos")
    check("alias call_to_action→cta", g2["cta"] == "comenta")

    # límites duros
    for mal, esperado in [
        ({"escenas": []}, "escenas"),
        ({"escenas": [{"narracion": ""}]}, "narracion"),
        ({"escenas": [{"narracion": "x" * 2001}]}, "excede"),
        ({"escenas": [{"narracion": "a"}, {"narracion": "b"}][:1]}, "entre"),
    ]:
        try:
            guion_svc.validate(mal, ESTILOS)
            check(f"rechaza {esperado}", False, json.dumps(mal)[:60])
        except ValueError as e:
            check(f"rechaza {esperado}", esperado in str(e))

    print("── 4. ingest sin LLM (proyecto real + limpieza)")
    import database as db  # noqa: E402
    CREADOS: list[str] = []

    def fake_crear(g):
        p = db.create_project(title=(g.get("titulo") or "sin titulo"),
                              mode="guion_json", style=g.get("estilo") or "auto",
                              format=g.get("formato") or "short", meta={})
        CREADOS.append(p["id"])
        return dict(p)

    res = asyncio.run(guion_svc.ingest(EJEMPLO, ESTILOS, fake_crear))
    check("ok True", res["ok"] is True)
    check("4 escenas contadas", res["escenas"] == 4)
    check("modo guion_json", res["modo"] == "guion_json")
    meta = (db.get_project(CREADOS[-1]) or {}).get("meta") or {}
    check("meta.guion_json.fuente=chatgpt",
          meta.get("guion_json", {}).get("fuente") == "chatgpt")
    check("escenas persistidas", len(db.get_scenes(CREADOS[-1])) == 4)

    print("── 5. rama del orquestador (guion_json salta PASO 1)")
    import importlib  # noqa: E402
    orch = importlib.import_module("pipeline.orchestrator")
    src = Path(BACKEND / "pipeline/orchestrator.py").read_text()
    check("rama guion_json existe", 'project["mode"] == "guion_json"' in src)
    check("mención de contrato en emisión", "contrato guion_json" in src)
    check("escenas vacías → error claro", "guion_json sin escenas" in src)

    print("── 6. servidor MCP (JSON-RPC) · 2.16")
    from services import mcp_server  # noqa: E402
    check("16 tools (14 legacy + submit_production_json + lanzar_proyecto)",
          len(mcp_server.TOOLS) == 16, f"={len(mcp_server.TOOLS)}")
    check("tools 2.16 presentes",
          any(t["name"] == "submit_production_json" for t in mcp_server.TOOLS)
          and any(t["name"] == "lanzar_proyecto" for t in mcp_server.TOOLS))
    check("tool del contrato presente",
          any(t["name"] == "crear_video_guion_json" for t in mcp_server.TOOLS))
    check("tools avatar/camara presentes",
          any(t["name"] == "crear_avatar" for t in mcp_server.TOOLS)
          and any(t["name"] == "listar_recetas_camara" for t in mcp_server.TOOLS))
    r = asyncio.run(mcp_server._dispatch("listar_estilos", {}))
    check("dispatch listar_estilos", len(r) >= 25)
    r = asyncio.run(mcp_server._dispatch("estado_sistema", {}))
    check("dispatch estado_sistema", r["version"] == "2.11.0")
    r = asyncio.run(mcp_server._dispatch("listar_recetas_camara", {}))
    check("dispatch listar_recetas_camara", len(r) == 20)
    r = asyncio.run(mcp_server._dispatch(
        "crear_video_guion_json", {"guion": txt, "lanzar": False}))
    check("MCP crea proyecto desde contrato", r.get("ok") is True and r["escenas"] == 4)
    if r.get("project_id"):
        CREADOS.append(r["project_id"])  # el test también limpia lo creado vía MCP
    try:
        asyncio.run(mcp_server._dispatch("estado_proyecto", {"project_id": "xxx"}))
        check("proyecto inexistente → error", False)
    except ValueError:
        check("proyecto inexistente → error", True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    # limpieza de los proyectos de prueba
    for pid in CREADOS:
        db.delete_project(pid)
    return 1 if FAIL else 0


def test_bateria_guion_json():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
