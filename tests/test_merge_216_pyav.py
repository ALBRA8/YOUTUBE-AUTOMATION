#!/usr/bin/env python3
"""Batería de integración del estado FUSIONADO 2.16.x + fix PyAV (v2.16.2).

Secciones:
  A · MCP 2.16.1 auditado por AST (20 tools, legacy intactas, dispatcher,
      handlers submit_production_json / lanzar_proyecto) — sin imports pesados.
  B · Adapter 2.16 real con módulo database fake (spec, preflight, extras).
  C · Fix PyAV verificado por strings de fuente (requirements, tts_step,
      doctor).
  D · Compatibilidad entre líneas (tts_skip Adapter↔tts_step, extras
      MCP↔Adapter, auto_start_override, coherencia de versiones).

Copia canónica (fuente de verdad) dentro del repo: el backend se resuelve
relativo al propio repositorio (tests/../backend). Única escritura real:
production.json del proyecto de prueba bajo data/output/ (se limpia al final).

Uso:  cd yt_automation_v2 && python3 tests/test_merge_216_pyav.py
      python3 -m pytest tests/ -q     (cada batería = 1 test pytest)
"""
import ast
import asyncio
import json
import re
import shutil
import sys
import types
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

    SRC_MCP = (BACKEND / "services/mcp_server.py").read_text(encoding="utf-8")
    SRC_PJ = (BACKEND / "services/production_json.py").read_text(encoding="utf-8")
    SRC_TTS = (BACKEND / "pipeline/tts_step.py").read_text(encoding="utf-8")
    SRC_DOC = (BACKEND / "services/doctor.py").read_text(encoding="utf-8")
    SRC_REQ = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    SRC_MAIN = (BACKEND / "main.py").read_text(encoding="utf-8")

    # ═══════════════════ A · MCP 2.16.1 por AST ═══════════════════
    print("── A. MCP 2.16.1 (AST, sin imports)")
    tree = ast.parse(SRC_MCP)
    check("mcp_server.py compila (AST válido)", True)
    tool_names = re.findall(r'"name":\s*"([a-z_]+)"', SRC_MCP)
    # deduplicar conservando orden (descripciones también citan nombres)
    vistos, tools_unicas = set(), []
    for n in tool_names:
        if n not in vistos:
            vistos.add(n)
            tools_unicas.append(n)
    tools_assign = next(
        (n.value for n in ast.walk(tree)
         if isinstance(n, ast.Assign)
         and any(getattr(t, "id", None) == "TOOLS" for t in n.targets)), None)
    n_tools = len(tools_assign.elts) if isinstance(tools_assign, ast.List) else -1
    check("20 tools declaradas (16 + 4 de operación Flow Bridge/QA v1)",
          n_tools == 20, f"={n_tools}")
    for legacy in ("ayuda", "crear_video", "crear_video_guion_json",
                   "estado_proyecto", "guion_de_proyecto", "listar_proyectos",
                   "listar_biblioteca", "listar_estilos", "listar_nichos",
                   "listar_avatares", "crear_avatar", "listar_recetas_camara",
                   "estado_sistema", "cancelar_trabajo"):
        check(f"legacy {legacy} intacta", f'{{"name": "{legacy}"' in SRC_MCP)
    check("tool submit_production_json declarada",
          '{"name": "submit_production_json"' in SRC_MCP)
    check("tool lanzar_proyecto declarada",
          '{"name": "lanzar_proyecto"' in SRC_MCP)
    check("SERVER_INFO 2.18.0", '"version": "2.18.0"' in SRC_MCP)
    check("dispatcher ruta submit_production_json",
          'if name == "submit_production_json":' in SRC_MCP
          and "return await _t_submit_production_json(**args)" in SRC_MCP)
    check("dispatcher ruta lanzar_proyecto",
          'if name == "lanzar_proyecto":' in SRC_MCP
          and "return await _t_lanzar_proyecto(**args)" in SRC_MCP)
    check("handler submit definido y async",
          "async def _t_submit_production_json(" in SRC_MCP)
    check("handler lanzar definido y async",
          "async def _t_lanzar_proyecto(" in SRC_MCP)
    check("submit llama production_svc.ingest",
          "await production_svc.ingest(" in SRC_MCP)
    check("lanzar NO re-ingiere (solo start_pipeline)",
          "await orchestrator.start_pipeline(project_id)" in SRC_MCP)
    check("lanzar protege job activo",
          "db.active_job_for_project(project_id)" in SRC_MCP)

    # ═══════════════════ B · Adapter 2.16 real (db fake) ═══════════════════
    print("── B. Adapter 2.16 (database fake, hermético)")

    class _FakeDB:
        def __init__(self):
            self.projects, self.scenes = {}, {}

        def replace_scenes(self, pid, escenas):
            self.scenes[pid] = escenas

        def update_project(self, pid, **kw):
            self.projects[pid].update(kw)

        def get_project(self, pid):
            return self.projects.get(pid)

    _FAKE = _FakeDB()
    sys.modules["database"] = types.SimpleNamespace(**{
        "replace_scenes": _FAKE.replace_scenes,
        "update_project": _FAKE.update_project,
        "get_project": _FAKE.get_project,
    })

    from services import production_json as pj  # noqa: E402
    from services.themes import STYLES  # noqa: E402

    ESTILOS = {s["id"] for s in STYLES}
    spec = pj.spec(sorted(ESTILOS))
    check("spec 2.18.0", spec["version"] == "2.18.0")
    check("spec declara image_prompt OPCIONAL EN INGESTA",
          "OPCIONAL EN INGESTA" in spec["campos_de_unidad"]
          ["image_prompt|visual_prompt|prompt_image"])

    payload = json.dumps({"project": {"title": "Fusión", "extra_flag": "keep"},
                          "sequence": [
                              {"narration": "a", "image_prompt": "img a",
                               "duration": 4},
                              {"narration": "b"}],
                          "auto_start": False}, ensure_ascii=False)
    g, av, norm = pj.validate(pj.parse_payload(payload), ESTILOS)
    check("validate: 2 escenas", len(g["escenas"]) == 2)
    check("validate: project_extra conservado",
          g["project_extra"] == {"extra_flag": "keep"})
    rep = pj.validate_execution(pj.parse_payload(payload))
    check("preflight: 1 bloqueada por image_prompt",
          rep["unidades_bloqueadas"] == 1)

    def _crear(gg):
        _FAKE.projects["test_pj_fusion"] = {"id": "test_pj_fusion",
                                            "title": gg.get("titulo"), "meta": {}}
        return dict(_FAKE.projects["test_pj_fusion"])

    res = asyncio.run(pj.ingest(payload, ESTILOS, _crear, auto_start_override=False))
    check("ingest draft ok (unidad incompleta conservada)", res["ok"] is True
          and res["job_id"] is None)
    meta_pj = _FAKE.projects["test_pj_fusion"]["meta"]["production_json"]
    check("ingest guarda validacion_ejecucion en meta",
          meta_pj["validacion_ejecucion"]["unidades_bloqueadas"] == 1)
    try:
        asyncio.run(pj.ingest(payload, ESTILOS, _crear, auto_start_override=True))
        check("preflight bloquea lanzamiento con faltantes", False)
    except ValueError as e:
        check("preflight bloquea lanzamiento con faltantes",
              "no se puede lanzar" in str(e))
    shutil.rmtree(Path(pj.OUTPUT_DIR) / "test_pj_fusion", ignore_errors=True)

    # ═══════════════════ C · Fix PyAV por strings de fuente ═══════════════════
    print("── C. Fix PyAV (fuente)")
    check("requirements: pin av>=11,<19", re.search(r"^av>=11,<19", SRC_REQ, re.M)
          is not None)
    check("requirements: faster-whisper presente", "faster-whisper" in SRC_REQ)
    check("tts_step: bypass tts_skip consume meta de escena",
          '(sc.get("meta") or {}).get("tts_skip")' in SRC_TTS)
    check("tts_step: fallback estimate_words si Whisper falla",
          "whisper_service.estimate_words(" in SRC_TTS)
    check("tts_step: CancelledError se re-lanza (no se traga)",
          re.search(r"except asyncio\.CancelledError:\s*\n\s*raise", SRC_TTS)
          is not None)
    check("tts_step: fallback captura Exception genérica",
          re.search(r"except Exception as e:.{0,200}?words = whisper_service\.estimate_words\(",
                    SRC_TTS, re.S) is not None)
    check("doctor: check pyav con cota <19",
          'add("pyav", av_ok and 0 < av_major < 19' in SRC_DOC)
    check("main.py: versión 2.18.0 (FastAPI)", 'version="2.18.0"' in SRC_MAIN)
    check("main.py: versión 2.18.0 (/estado)", '"version": "2.18.0"' in SRC_MAIN)

    # ═══════════════════ D · Compatibilidad entre líneas ═══════════════════
    print("── D. Compatibilidad Adapter ↔ pipeline ↔ MCP")
    check("Adapter emite tts_skip plano en meta de escena",
          re.search(r'meta_esc: dict = \{\s*\n\s*"production_unit": punit,\s*\n'
                    r'.*?"tts_skip": tts_skip,', SRC_PJ, re.S) is not None
          or '"tts_skip": tts_skip' in SRC_PJ)
    check("tts_step lee exactamente esa clave meta",
          '(sc.get("meta") or {}).get("tts_skip")' in SRC_TTS
          and '"tts_skip": tts_skip' in SRC_PJ)
    check("Adapter produce project_extra/root_extra",
          '"project_extra": project_extra' in SRC_PJ
          and '"root_extra": root_extra' in SRC_PJ)
    check("MCP persiste production_project_extra/root_extra",
          'pmeta["production_project_extra"]' in SRC_MCP
          and 'pmeta["production_root_extra"]' in SRC_MCP)
    check("MCP pasa auto_start_override=bool(lanzar)",
          "auto_start_override=bool(lanzar)" in SRC_MCP)
    check("Adapter ingest acepta auto_start_override",
          "async def ingest(payload, estilos_validos: set[str], crear_proyecto,\n"
          "                 auto_start_override=None)" in SRC_PJ)
    check("sin narración no se inventa voz (Adapter)",
          "tts_skip = not narr" in SRC_PJ)
    check("coherencia MCP/Adapter 2.18.0 y app 2.18.0",
          '"version": "2.18.0"' in SRC_MCP
          and '"version": "2.18.0"' in SRC_PJ
          and 'version="2.18.0"' in SRC_MAIN)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_bateria_merge_216_pyav():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
