#!/usr/bin/env python3
"""Batería hermética del Adapter Production JSON 2.16 (reconstruida).

Corre SIN servidor y SIN DB real: se inyecta un módulo `database` fake en
sys.modules ANTES de importar services.production_json. Única escritura real:
production.json del proyecto de prueba bajo data/output/ (se limpia al final).

Copia canónica (fuente de verdad) dentro del repo: el backend se resuelve
relativo al propio repositorio (tests/../backend).

Uso:  cd yt_automation_v2 && python3 tests/test_production_json.py
      python3 -m pytest tests/ -q     (cada batería = 1 test pytest)
"""
import asyncio
import hashlib
import json
import shutil
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


# ── módulo database FAKE (hermético) ─────────────────────────────────────
class _FakeDB:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.scenes: dict[str, list] = {}

    def replace_scenes(self, pid, escenas):
        self.scenes[pid] = escenas

    def update_project(self, pid, **kw):
        self.projects[pid].update(kw)

    def get_project(self, pid):
        return self.projects.get(pid)


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

    _FAKE = _FakeDB()
    sys.modules["database"] = types.SimpleNamespace(**{
        "replace_scenes": _FAKE.replace_scenes,
        "update_project": _FAKE.update_project,
        "get_project": _FAKE.get_project,
    })

    from services import production_json as pj  # noqa: E402
    from services.themes import STYLES  # noqa: E402

    ESTILOS = {s["id"] for s in STYLES}

    def crear_proyecto(g):
        _FAKE.projects["test_pj_adapter"] = {"id": "test_pj_adapter",
                                             "title": g.get("titulo") or "sin titulo",
                                             "meta": {}}
        return dict(_FAKE.projects["test_pj_adapter"])

    EJEMPLO = pj.spec([])["ejemplo"]

    print("── 1. spec del contrato")
    spec = pj.spec(sorted(ESTILOS))
    check("version 2.19.0", spec["version"] == "2.19.0")
    check("campos clave", all(k in spec["campos"] for k in
                              ("project", "sequence", "title|name", "format",
                               "style", "voice", "avatar_id", "niche",
                               "platforms", "continuity", "auto_start")))
    check("campos_de_unidad presentes", all(k in spec["campos_de_unidad"] for k in
                                            ("id", "type", "title", "narration",
                                             "dialogue", "duration|duration_seconds")))
    check("image_prompt OPCIONAL EN INGESTA (spec)",
          "OPCIONAL EN INGESTA" in spec["campos_de_unidad"]["image_prompt|visual_prompt|prompt_image"])
    check("narration es lo único que llega a TTS (spec)",
          "lo ÚNICO que llega a TTS" in spec["campos_de_unidad"]["narration"])
    check("principio dos niveles de validación",
          any("dos niveles de validación" in p for p in spec["principios"]))
    check("principio no-invensión",
          any("jamás regenera ni inventa" in p for p in spec["principios"]))
    check("principio tts_skip silencio",
          any("silencio a duration_target" in p for p in spec["principios"]))
    check("validación nivel 2 documentada",
          any("nivel 2 EJECUCIÓN" in v for v in spec["validaciones"]))
    check("ejemplo con 1 unidad", len(spec["ejemplo"]["sequence"]) == 1)

    print("── 2. parse_payload")
    check("dict pasa tal cual", pj.parse_payload(EJEMPLO) is EJEMPLO)
    txt = json.dumps(EJEMPLO, ensure_ascii=False)
    check("str JSON", pj.parse_payload(txt)["project"]["title"] == "Mini demo")
    check("fences ```json", pj.parse_payload(f"```json\n{txt}\n```")["project"]["title"]
          == "Mini demo")
    try:
        pj.parse_payload("esto no es json")
        check("JSON inválido rechazado", False)
    except ValueError:
        check("JSON inválido rechazado", True)

    print("── 3. validate estructural")
    g, av, norm = pj.validate(pj.parse_payload(txt), ESTILOS)
    check("1 escena", len(g["escenas"]) == 1)
    check("titulo Mini demo", g["titulo"] == "Mini demo")
    check("formato short", g["formato"] == "short")
    check("adapter 2.19.0 en meta", g["production"]["adapter"] == "production_json/v2.19.0")
    check("sin avisos en ejemplo limpio", not av, str(av))
    check("unidad con visual_prompt → image_prompt",
          g["escenas"][0]["image_prompt"].startswith("macro miniature"))
    check("execution_requirements imagen True",
          g["escenas"][0]["meta"]["production_unit"]["execution_requirements"]
          == {"image_generation": True, "image_prompt_required_by_current_executor": True})
    check("unidad narración vacía → tts_skip True",
          g["escenas"][0]["meta"]["tts_skip"] is True)

    # aliases mecánicos
    alien = {"project": {"name": "Prueba alias", "format": {"aspect_ratio": "9:16"},
                         "style": "no-existe", "platforms": ["youtube", "bebo"]},
             "units": [{"narration": "uno", "visual_prompt": "a cat, no text",
                        "duration": 5},
                       {"dialogue": "hola"},
                       {"id": "b3", "type": "beat", "title": "Tres",
                        "image_prompt": "ok", "duration_seconds": 3}],
             "auto_start": False}
    g2, av2, norm2 = pj.validate(alien, ESTILOS)
    check("alias name→titulo", g2["titulo"] == "Prueba alias")
    check("format objeto aspect_ratio→short", g2["formato"] == "short")
    check("alias units→sequence registrada", any("units" in n for n in norm2))
    check("3 escenas", len(g2["escenas"]) == 3)
    check("estilo inválido→auto + aviso", g2["estilo"] == "auto" and
          any("estilo" in a for a in av2))
    check("plataforma basura filtrada", g2["plataformas"] == ["youtube"] and
          any("bebo" in a for a in av2))
    check("alias visual_prompt→image_prompt", g2["escenas"][0]["image_prompt"]
          == "a cat, no text")
    check("unidad 1 narración → tts_skip False",
          g2["escenas"][0]["meta"]["tts_skip"] is False)
    check("unidad 2 dialogue STRING → narration + tts_skip False",
          g2["escenas"][1]["meta"]["production_unit"]["narration"] == "hola"
          and g2["escenas"][1]["meta"]["tts_skip"] is False)
    check("unidad 3 sin texto → tts_skip True",
          g2["escenas"][2]["meta"]["tts_skip"] is True
          and g2["escenas"][2]["meta"]["production_unit"]["narration"] is None)
    check("dialogue conservado verbatim",
          g2["escenas"][1]["meta"]["production_unit"]["dialogue"] == "hola")
    check("duration_seconds→duration_target",
          g2["escenas"][2]["meta"]["duration_target"] == 3)
    check("id y tipo conservados",
          g2["escenas"][2]["meta"]["production_unit"]["id"] == "b3"
          and g2["escenas"][2]["meta"]["production_unit"]["type"] == "beat")

    # project_extra / root_extra verbatim
    extra = {"project": {"title": "Con extras", "pipeline_hint": "viral",
                         "creative_notes": {"tone": "epic"}},
             "sequence": [{"image_prompt": "x", "narration": "n"}],
             "workflow_id": "wf-42", "auto_start": False}
    g3, _, _ = pj.validate(extra, ESTILOS)
    check("project_extra verbatim", g3["project_extra"] ==
          {"pipeline_hint": "viral", "creative_notes": {"tone": "epic"}})
    check("root_extra verbatim", g3["root_extra"] == {"workflow_id": "wf-42"})

    # continuity verbatim
    cont = {"project": {"title": "Con continuity"},
            "sequence": [{"image_prompt": "x", "narration": "n",
                          "continuity": {"character": "Lía", "wardrobe": "red"}}],
            "continuity": {"world": "costa"}}
    g4, _, _ = pj.validate(cont, ESTILOS)
    check("continuity proyecto verbatim", g4["continuity"] == {"world": "costa"})
    check("continuity unidad verbatim",
          g4["escenas"][0]["meta"]["production_unit"]["continuity"]
          == {"character": "Lía", "wardrobe": "red"})

    # límites duros estructurales
    for mal, esperado in [
        ({"sequence": [{"image_prompt": "x"}]}, "identificable"),
        ({"project": {"title": "x"}}, "no encontrada"),
        ({"project": {"title": "x"}, "sequence": []}, "vacía"),
    ]:
        try:
            pj.validate(mal, ESTILOS)
            check(f"rechaza {esperado}", False, json.dumps(mal)[:50])
        except ValueError as e:
            check(f"rechaza {esperado}", esperado in str(e) and
                  str(e).startswith("Creative Production JSON validation error"))

    print("── 4. validate_execution (nivel 2)")
    rep = pj.validate_execution({"project": {"title": "x"}, "sequence": [
        {"image_prompt": "ok", "narration": "n", "duration": 4},
        {"narration": "sin imagen ni duration"},
        {"image_prompt": "ok", "duration": 2}]})
    check("nivel ejecucion", rep["nivel"] == "ejecucion")
    check("3 unidades auditadas", rep["unidades_auditadas"] == 3)
    check("2 ejecutables", rep["unidades_ejecutables"] == 2)
    check("1 bloqueada", rep["unidades_bloqueadas"] == 1)
    check("faltante image_prompt bloqueante",
          rep["unidades_con_faltantes"][0]["faltantes"][0]["campo"] == "image_prompt"
          and rep["unidades_con_faltantes"][0]["faltantes"][0]["bloqueante"] is True)
    check("fuente esperada apunta al CREATIVE ENGINE",
          "CREATIVE ENGINE" in rep["unidades_con_faltantes"][0]["faltantes"][0]["fuente_esperada"])
    check("unidad sin duration → faltante no bloqueante reportado",
          any(f["campo"] == "duration" and not f["bloqueante"]
              for f in rep["unidades_con_faltantes"][0]["faltantes"]))
    check("política no-invensión en reporte",
          "NO inventa" in rep["politica"])
    check("no lanza excepciones", True)

    print("── 5. validate_only (dry-run)")
    PID = "test_pj_adapter"
    dry = pj.validate_only(txt, ESTILOS)
    check("dry_run True", dry["dry_run"] is True)
    check("ok True", dry["ok"] is True)
    check("incluye validacion_ejecucion",
          dry["validacion_ejecucion"]["unidades_ejecutables"] == 1)
    check("vista_previa con unit id", dry["vista_previa"][0]["id"] == "beat_001")
    check("dry-run NO crea proyecto", _FAKE.get_project(PID) is None)

    print("── 6. ingest con DB fake")
    payload_str = json.dumps({"project": {"title": "Draft incompleto",
                                          "workflow": "abc"},
                              "sequence": [
        {"narration": "con imagen", "image_prompt": "a red pan, no text",
         "duration": 5},
        {"narration": "sin imagen"}], "auto_start": False}, ensure_ascii=False)

    res = asyncio.run(pj.ingest(payload_str, ESTILOS, crear_proyecto,
                                auto_start_override=False))
    check("ok True", res["ok"] is True)
    check("modo production_json", res["modo"] == "production_json")
    check("2 unidades", res["unidades"] == 2)
    check("job_id None en draft", res["job_id"] is None)
    check("escenas persistidas en db fake", len(_FAKE.scenes[PID]) == 2)
    meta_pj = _FAKE.projects[PID]["meta"]["production_json"]
    check("preflight guardado en meta",
          meta_pj["validacion_ejecucion"]["unidades_bloqueadas"] == 1)
    check("sha256 del original",
          meta_pj["sha256"] == hashlib.sha256(payload_str.strip().encode()).hexdigest())
    check("production.json en disco",
          (Path(pj.OUTPUT_DIR) / PID / "production.json").exists())
    check("unidad incompleta conservada (escena 2)",
          _FAKE.scenes[PID][1]["meta"]["production_unit"]["image_prompt"] is None
          and _FAKE.scenes[PID][1]["meta"]["production_unit"]
          ["execution_requirements"]["image_generation"] is False)
    check("image_prompt_required_by_current_executor",
          _FAKE.scenes[PID][1]["meta"]["production_unit"]
          ["execution_requirements"]["image_prompt_required_by_current_executor"] is True)
    check("tts_skips contados", res["tts_skips"] == 0)

    # lanzar=true con unidad bloqueada → error explícito, nada creado
    _antes = len(_FAKE.projects)
    bloq = json.dumps({"project": {"title": "No debe lanzarse"},
                       "sequence": [{"narration": "x"}], "auto_start": True})
    try:
        asyncio.run(pj.ingest(bloq, ESTILOS, crear_proyecto,
                              auto_start_override=True))
        check("lanzar con bloqueo → ValueError", False)
    except ValueError as e:
        check("lanzar con bloqueo → ValueError",
              "no se puede lanzar" in str(e) and "image_prompt" in str(e))
    check("nada creado por el intento bloqueado", len(_FAKE.projects) == _antes)

    # draft permitido vía validate-only aunque esté incompleto
    check("validate_only acepta incompleto (draft)",
          pj.validate_only(bloq, ESTILOS)["validacion_ejecucion"]["unidades_bloqueadas"] == 1)

    # ── v2.16.3 · dialogue-STRING = voz del dialecto Creative Engine ──────
    # Fix de regresión: v2.14 dejaba el dialogue string sin NINGÚN ejecutor
    # (videos mudos marcados ready). STRING → narration (TTS); LISTA de
    # lipsync se conserva verbatim y NUNCA se convierte en voz.
    dsp = json.dumps({
        "project": {"title": "Voz del dialecto"},
        "sequence": [
            {"id": "u1", "image_prompt": "p1", "duration": 4,
             "dialogue": "—¡No te vayas! —gritó el tomate."},
            {"id": "u2", "image_prompt": "p2", "duration": 4,
             "narration": "voz off clásica",
             "dialogue": [{"character": "tomate", "line": "—Hola"}]},
        ],
    })
    gd, avisos_d, _ = pj.validate(pj.parse_payload(dsp), ESTILOS)
    u1, u2 = gd["escenas"][0]["meta"]["production_unit"], \
        gd["escenas"][1]["meta"]["production_unit"]
    check("dialogue STRING → narration (voz del dialecto)",
          u1["narration"] == "—¡No te vayas! —gritó el tomate.")
    check("dialogue STRING conservado verbatim en la unidad",
          u1["dialogue"] == "—¡No te vayas! —gritó el tomate.")
    check("aviso del mapeo registrado",
          any("dialogue(string) → narration" in a for a in avisos_d))
    check("unit con dialogue STRING llega a TTS (no tts_skip)",
          gd["escenas"][0]["meta"]["tts_skip"] is False)
    check("dialogue LISTA (lipsync) NUNCA se convierte en voz",
          u2["narration"] == "voz off clásica"
          and isinstance(u2["dialogue"], list)
          and u2["dialogue"][0]["character"] == "tomate")
    check("unit con narration propia NO avisa mapeo",
          not any("dialogue(string) → narration" in a
                  for a in avisos_d if "sequence[1]" in a))

    # limpieza del proyecto de prueba en disco
    shutil.rmtree(Path(pj.OUTPUT_DIR) / PID, ignore_errors=True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_bateria_production_json():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
