#!/usr/bin/env python3
"""Batería SKILLS + AUTONOMÍA — contrato Skill universal (§10) y niveles de
autonomía (§26), en HERMÉTICO (estado de skills en tmp; patrón run_all).

Ejercita:
  · REGISTRO: las 17 skills canónicas, identidad única, los 16 campos del
    contrato §10 presentes, kinds ∈ KINDS, versión/métricas honestas
    (confidence 0.8/0.5, success_rate 0.0 hasta primera medición real)
  · PUERTA DE VALIDACIÓN: validate_registry() resuelve CADA target con
    importlib (bindings reales del repo) y verifica que cada test de
    regresión listado existe en tests/ → ok=True, errores=[]
  · BINDINGS: qa_project, youtube_publish.upload, recover_expired y los
    callables REALES del doctor (preflight.real_flow_preflight — el nombre
    real del módulo preflight.py, no 'run_preflight' — y
    layers.auditar_capas — core.py NO define 'diagnose')
  · mark_validated: counters rolling en JSON de estado sandbox, copy con
    last_validated, success_rate derivado honesto, None en identidad
    desconocida
  · AUTONOMÍA §26: escalera L0..L5, current_level desde el env con clamping,
    check/require por acción, y la guarda INVIOABLE assert_no_bypass
    (self-improvement jamás autoriza publish/security)

Uso:  cd yt_automation_v2 && python3 tests/test_skills_autonomia.py
      python3 -m pytest tests/test_skills_autonomia.py -q
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
_TMP = Path(tempfile.mkdtemp(prefix="skills_test_"))
from services import skills, autonomy  # noqa: E402
skills.STATE_PATH = _TMP / "skills_state.json"   # hermético

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✓ {nombre}")
    else: FAIL += 1; print(f"  ✗ {nombre} {extra}")


_IDENTIDADES = {
    "CREATE_SCRIPT", "PREPARE_IMAGE_PROMPT", "GENERATE_IMAGE", "GENERATE_TTS",
    "GENERATE_VIDEO", "GENERATE_SUBTITLES", "ASSEMBLE_VIDEO", "ADD_MUSIC",
    "RENDER_VIDEO", "VALIDATE_ASSET", "RUN_VIDEO_QA", "RUN_FLOW_PREFLIGHT",
    "QUEUE_PRODUCTION", "RECOVER_PRODUCTION", "RETRY_FAILED_STEP",
    "PUBLISH_VIDEO", "ANALYZE_PRODUCTION_FAILURE",
}


def main() -> int:
    global OK, FAIL

    # ── 1 · Registro universal (§10) ─────────────────────────────────────────
    print("── 1. registro universal de skills (§10)")
    regs = skills.list()
    ids = {r.get("identity") for r in regs}
    check("17 identidades canónicas presentes", ids == _IDENTIDADES,
          f"→ faltan {sorted(_IDENTIDADES - ids)} sobran {sorted(ids - _IDENTIDADES)}")
    check("identidades únicas", len(regs) == len(ids))
    check("las 16 entradas traen TODOS los SKILL_FIELDS",
          all(all(c in r for c in skills.SKILL_FIELDS) for r in regs))
    check("kind declarado en KINDS en todas",
          all(r.get("kind") in skills.KINDS for r in regs))
    check("métricas honestas: confidence float y success_rate float en todas",
          all(isinstance(r["confidence"], float)
              and isinstance(r["success_rate"], float)
              and r["version"] == "1.0.0"
              and r["origin"] == "registrar_on_first_use" for r in regs))

    # ── 2 · Puerta de validación (resuelve CADA binding con importlib) ──────
    print("── 2. puerta de validación (bindings reales vía importlib)")
    val = skills.validate_registry()
    check("validate_registry()['ok'] es True", val.get("ok") is True,
          f"→ {val}")
    check("validate_registry()['errores'] vacía", val.get("errores") == [],
          f"→ {val.get('errores')}")

    # ── 3 · Bindings reales (nombres verificados contra el repo) ────────────
    print("── 3. bindings reales")
    check("RUN_VIDEO_QA → video_qa.qa_project",
          str(skills.get("RUN_VIDEO_QA")["target"]).endswith(
              "video_qa.qa_project"))
    check("PUBLISH_VIDEO → youtube_publish.upload",
          str(skills.get("PUBLISH_VIDEO")["target"]).endswith(
              "youtube_publish.upload"))
    check("RECOVER_PRODUCTION → flow_jobs.recover_expired",
          str(skills.get("RECOVER_PRODUCTION")["target"]).endswith(
              "flow_jobs.recover_expired"))
    check("doctor REALES: preflight.real_flow_preflight + "
          "layers.auditar_capas",
          str(skills.get("RUN_FLOW_PREFLIGHT")["target"]).endswith(
              "preflight.real_flow_preflight")
          and str(skills.get("ANALYZE_PRODUCTION_FAILURE")["target"]).
          endswith("layers.auditar_capas"))

    # ── 4 · Tests de regresión en disco ──────────────────────────────────────
    print("── 4. baterías de regresión en disco")
    _tests_dir = Path(__file__).resolve().parent
    check("3 baterías conocidas existen",
          all((_tests_dir / f).exists() for f in
              ("test_golden_fixture.py", "test_flow_bridge.py",
               "test_qa_forensics.py")))
    check("toda regression_tests listada existe en tests/",
          all((_tests_dir / t).exists() for r in regs
              for t in (r.get("regression_tests") or [])))

    # ── 5 · KINDS: diferenciación contractual ────────────────────────────────
    print("── 5. KINDS (7 naturalezas)")
    check("al menos una SKILL y una TOOL en el registro",
          any(r["kind"] == "SKILL" for r in regs)
          and any(r["kind"] == "TOOL" for r in regs))
    check("SELF-IMPROVEMENT declarado en KINDS (7 naturalezas)",
          "SELF-IMPROVEMENT" in skills.KINDS and len(skills.KINDS) == 7)

    # ── 6 · mark_validated (estado honesto en sandbox) ───────────────────────
    print("── 6. mark_validated (contadores en JSON de estado)")
    marcada = skills.mark_validated("RUN_VIDEO_QA", True)
    check("marca exitosa → copy con last_validated",
          marcada is not None and marcada["last_validated"] is not None)
    check("state file escrito bajo el sandbox",
          Path(skills.STATE_PATH).exists()
          and str(Path(skills.STATE_PATH)).startswith(str(_TMP)))
    check("identidad desconocida → None (nunca lanza)",
          skills.mark_validated("SKILL_QUE_NO_EXISTE", True) is None)
    skills.mark_validated("RUN_VIDEO_QA", True)          # 2º ok
    tras = skills.mark_validated("RUN_VIDEO_QA", False)  # 1er fail → 2/3
    import json as _json
    estado = _json.loads(Path(skills.STATE_PATH).read_text(encoding="utf-8"))
    reg = estado.get("RUN_VIDEO_QA", {})
    check("2 ok + 1 fail → success_rate ≈ 2/3 (3 llamadas registradas)",
          tras["success_rate"] == round(2 / 3, 4)
          and int(reg.get("ok", 0)) + int(reg.get("fail", 0)) >= 3,
          f"→ rate={tras['success_rate']} estado={reg}")
    check("state JSON persiste contadores ok=2 fail=1",
          reg.get("ok") == 2 and reg.get("fail") == 1, f"→ {reg}")
    check("registro vivo refleja last_validated tras marcar",
          skills.get("RUN_VIDEO_QA")["last_validated"] is not None)

    # ── 7 · Autonomía: escalera y current_level (env evaluado en llamada) ───
    print("── 7. niveles de autonomía (§26)")
    check("LEVELS: 6 niveles L0..L5 y DESCRIPTIONS los cubre",
          len(autonomy.LEVELS) == 6
          and autonomy.LEVELS[0] == "L0_OBSERVE"
          and autonomy.LEVELS[5] == "L5_SELF_IMPROVE"
          and all(l in autonomy.DESCRIPTIONS for l in autonomy.LEVELS))
    os.environ.pop("FACTORY_AUTONOMY_LEVEL", None)
    check("current_level() default 2 sin env", autonomy.current_level() == 2)
    try:
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "4"
        check("env FACTORY_AUTONOMY_LEVEL='4' → 4", autonomy.current_level() == 4)
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "9"
        check("clamping '9' → 5", autonomy.current_level() == 5)
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "x"
        check("basura 'x' → default 2", autonomy.current_level() == 2)
    finally:
        os.environ.pop("FACTORY_AUTONOMY_LEVEL", None)

    # ── 8 · check/require por acción ─────────────────────────────────────────
    print("── 8. check/require por acción")
    os.environ.pop("FACTORY_AUTONOMY_LEVEL", None)  # nivel 2 (default)
    v = autonomy.check("run_pipeline")
    check("run_pipeline permitida en L2 (required 2)",
          v["allowed"] is True and v["required"] == 2 and v["current"] == 2)
    v = autonomy.check("publish_video")
    check("publish_video BLOQUEADA en L2 (required 3)",
          v["allowed"] is False and v["required"] == 3 and v["current"] == 2)
    try:
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "3"
        v = autonomy.check("publish_video")
        check("publish_video permitida en L3", v["allowed"] is True)
        check("doctor_fix requiere 4 · self_improve requiere 5",
              autonomy.check("doctor_fix")["required"] == 4
              and autonomy.check("self_improve")["required"] == 5)
    finally:
        os.environ.pop("FACTORY_AUTONOMY_LEVEL", None)
    subio = no_subio = False
    try:
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "2"
        autonomy.require("publish_video")
    except PermissionError:
        subio = True
    try:
        os.environ["FACTORY_AUTONOMY_LEVEL"] = "3"
        autonomy.require("publish_video")
        no_subio = True
    finally:
        os.environ.pop("FACTORY_AUTONOMY_LEVEL", None)
    check("require: PermissionError en L2 y pasa en L3", subio and no_subio)

    # ── 9 · assert_no_bypass (guarda §26 inviolable) ─────────────────────────
    print("── 9. assert_no_bypass (self-improvement jamás salta security)")
    lanzo = False
    try:
        autonomy.assert_no_bypass("publish_video", granted_by="self_improve")
    except ValueError:
        lanzo = True
    check("self_improve intentando autorizar publish_video → ValueError",
          lanzo)
    lanzo = False
    try:
        autonomy.assert_no_bypass("upload_external",
                                  granted_by="self-improvement")
    except ValueError:
        lanzo = True
    check("variante 'self-improvement' + upload_external → ValueError",
          lanzo)
    check("origen legítimo (humano) o sin granted_by → sin ValueError",
          autonomy.assert_no_bypass("publish_video", granted_by="humano")
          is True and autonomy.assert_no_bypass("run_pipeline") is True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_bateria_skills_autonomia():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
