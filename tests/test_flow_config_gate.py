#!/usr/bin/env python3
"""Batería EXECUTION CONTRACT V1.0 — lado EXTENSIÓN (flowConfigFn + gate).

Verifica, EN HERMÉTICO (sin Chrome, sin red, sin Flow real, sin coordenadas),
la capa mecánica del contrato añadida a background.js bajo las anclas
[execution-contract v1]:

  1. anclas + sintaxis: node --check de background.js/bridge.js/arnés,
     sección [execution-contract v1] config extraíble y balanceada.
  2. escenarios deterministas con el CÓDIGO REAL (arnés flow_config_mock.js,
     mini-DOM fake con log de clicks semántico):
     a) config_5s_a_8s_ok   UI 5s → click "8s" → re-lectura "8s" → VERIFIED
                            · gate ALLOW_GENERATE · sin error emitido.
     b) unsupported         sin control de duración → UNSUPPORTED ·
                            CONFIG_UNSUPPORTED (prefijo EXACTO).
     c) frozen_mismatch     click sin efecto → MISMATCH · CONFIG_MISMATCH.
     d) stale_unverifiable  re-lectura null → UNVERIFIABLE ·
                            CONFIG_UNVERIFIABLE.
     e) ya_configurado      UI ya en 8s → VERIFIED SIN click (heredado EN el
                            valor pedido, §6: lo prohibido es generar con un
                            valor DISTINTO, no con el pedido ya puesto).
     f) sin_spec            job sin execution_spec → NO corre config
                            (comportamiento actual exacto).
     g) aspect_requerido_ok/mismatch  aspect 9:16 requerido: presente y
                            correcto → ALLOW; 16:9 inchangable → MISMATCH.
  3. EXACTITUD del gate: la decisión JS (__flowGateDecision, espejo de
     execution_contract.config_gate) se compara contra el gate REAL del
     backend con los MISMOS capabilities/control_results de la extensión.
  4. clicks SEMÁNTICOS: el log del mini-DOM solo contiene elementos
     (tag/text/aria) — cero coordenadas ni llamadas posicionales.
  5. normalización "8s" ≡ 8 y " 9:16 " ≡ "9:16" con __flowNormVal REAL.

Uso:  cd yt_automation_v2 && python3 tests/test_flow_config_gate.py
      python3 -m pytest tests/test_flow_config_gate.py -q
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "flow_config_mock.js"

# ── hermeticidad ANTES de importar backend (patrón de la casa) ───────────────
_TMP = Path(tempfile.mkdtemp(prefix="flow_config_gate_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

from services import execution_contract as ec  # noqa: E402  (gate REAL backend)

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node),
          "instala Node.js para verificar la capa de configuración DOM")

    # ── 1. anclas + sintaxis ──────────────────────────────────────────────
    print("── 1. anclas [execution-contract v1] + sintaxis (extension)")
    bg = EXT / "background.js"
    br = EXT / "bridge.js"
    check("background.js existe", bg.exists())
    check("bridge.js existe", br.exists())
    src = bg.read_text(encoding="utf-8", errors="replace")
    check("ancla de sección config presente (inicio/fin)",
          "/* [execution-contract v1] config: inicio" in src
          and "/* [execution-contract v1] config: fin */" in src)
    check("ancla de sección progreso presente (inicio/fin)",
          "/* [execution-contract v1] progreso: inicio" in src
          and "/* [execution-contract v1] progreso: fin */" in src)
    check("flowConfigFn definida (inyectable, auto-contenida)",
          "function flowConfigFn(spec)" in src)
    check("gate __flowGateDecision definido (espejo de config_gate)",
          "function __flowGateDecision(spec, controlResults)" in src)
    check("helper de progreso __bridgeReportProgress definido",
          "function __bridgeReportProgress(jobId, token, state, detail, evidence)" in src)
    check("bridgeProgress definido en bridge.js (endpoint ADITIVO)",
          "async function bridgeProgress(jobId, token, state, detail, evidence)" in br.read_text(
              encoding="utf-8", errors="replace"))
    check("__bridgeHandleJob lee job.execution_spec",
          "__flowParseSpec(job && job.execution_spec)" in src)
    check("el gate NO corre para imágenes ni jobs sin spec (isVideo && execSpec)",
          "if (isVideo && execSpec) {" in src)
    check("sin coordenadas ni clicks posicionales en la nueva capa",
          "elementFromPoint" not in src.split("config: inicio")[-1].split("config: fin")[0]
          and "clientX" not in src.split("config: inicio")[-1].split("config: fin")[0])

    if node:
        for js in (bg, br, HARNESS):
            proc = subprocess.run([node, "--check", str(js)],
                                  capture_output=True, text=True, timeout=60)
            check(f"sintaxis OK: {js.name}", proc.returncode == 0,
                  proc.stderr.strip()[:150])
    if not node:
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1 if FAIL else 0

    # ── 2. arnés real (mini-DOM, vm, sin Flow) ────────────────────────────
    print("── 2. arnés determinista (código REAL de background.js en vm)")
    proc = subprocess.run([node, str(HARNESS)], capture_output=True,
                          text=True, timeout=120, cwd=str(REPO))
    salida = (proc.stdout or "") + (proc.stderr or "")
    check("arnés corre sin error (exit 0, sin error_de_harness)",
          proc.returncode == 0 and "error_de_harness" not in salida,
          salida[-250:])
    data = {}
    try:
        data = json.loads(proc.stdout or "{}")
        check("arnés produce JSON parseable", True)
    except ValueError as e:
        check("arnés produce JSON parseable", False, str(e)[:150])
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1
    esc = data.get("escenas", {})
    norm = data.get("normalizacion", {})
    esperadas = ["config_5s_a_8s_ok", "unsupported", "frozen_mismatch",
                 "stale_unverifiable", "ya_configurado", "sin_spec",
                 "aspect_requerido_ok", "aspect_requerido_mismatch"]
    check("los 8 escenarios corrieron",
          all(n in esc for n in esperadas),
          repr([n for n in esperadas if n not in esc]))

    def s(nombre):
        return esc.get(nombre, {})

    # ── 3. escenarios (veredictos + gate + prefijo EXACTO) ────────────────
    print("── 3. escenarios del Execution Contract (config 5s→8s, gate)")

    a = s("config_5s_a_8s_ok")
    check("a: corre con spec (ran)", a.get("ran") is True)
    check("a: duración 5s→click 8s→relectura 8s → VERIFIED",
          a.get("verdicts", {}).get("duration") == "VERIFIED",
          repr(a.get("verdicts")))
    check("a: observado before/after ('5s' → '8s')",
          a.get("observed", {}).get("duration", {}).get("before") == "5s"
          and a.get("observed", {}).get("duration", {}).get("after") == "8s",
          repr(a.get("observed")))
    check("a: click semántico del chip '8s' registrado",
          "8s" in a.get("clickChips", []), repr(a.get("clickChips")))
    check("a: gate ALLOW_GENERATE (no bloquea generación)",
          a.get("gateDecision") == "ALLOW_GENERATE", repr(a.get("gateDecision")))
    check("a: SIN error emitido (errorPrefix null)",
          a.get("errorPrefix") is None, repr(a.get("errorPrefix")))

    b = s("unsupported")
    check("b: control ausente → capability available:false (honesto)",
          (b.get("capDuration") or {}).get("available") is False,
          repr(b.get("capDuration")))
    check("b: veredicto UNSUPPORTED (control no encontrado)",
          b.get("verdicts", {}).get("duration") == "UNSUPPORTED",
          repr(b.get("verdicts")))
    check("b: gate CONFIG_UNSUPPORTED", b.get("gateDecision") == "CONFIG_UNSUPPORTED",
          repr(b.get("gateDecision")))
    check("b: prefijo EXACTO del error 'CONFIG_UNSUPPORTED: '",
          str(b.get("errorPrefix") or "").startswith("CONFIG_UNSUPPORTED: "),
          repr(b.get("errorPrefix")))

    c = s("frozen_mismatch")
    check("c: click en '8s' ocurrió (chip semántico)",
          "8s" in c.get("clickChips", []), repr(c.get("clickChips")))
    check("c: la UI no cambió → MISMATCH (observed_after 5s)",
          c.get("verdicts", {}).get("duration") == "MISMATCH"
          and c.get("observed", {}).get("duration", {}).get("after") == "5s",
          repr(c.get("observed")))
    check("c: gate CONFIG_MISMATCH", c.get("gateDecision") == "CONFIG_MISMATCH",
          repr(c.get("gateDecision")))
    check("c: prefijo EXACTO del error 'CONFIG_MISMATCH: '",
          str(c.get("errorPrefix") or "").startswith("CONFIG_MISMATCH: "),
          repr(c.get("errorPrefix")))

    d = s("stale_unverifiable")
    check("d: re-lectura null tras el click → UNVERIFIABLE",
          d.get("verdicts", {}).get("duration") == "UNVERIFIABLE"
          and d.get("observed", {}).get("duration", {}).get("after") is None,
          repr(d.get("observed")))
    check("d: gate CONFIG_UNVERIFIABLE", d.get("gateDecision") == "CONFIG_UNVERIFIABLE",
          repr(d.get("gateDecision")))
    check("d: prefijo EXACTO del error 'CONFIG_UNVERIFIABLE: '",
          str(d.get("errorPrefix") or "").startswith("CONFIG_UNVERIFIABLE: "),
          repr(d.get("errorPrefix")))

    e = s("ya_configurado")
    check("e: UI ya en 8s → VERIFIED (heredado EN el valor pedido, §6)",
          e.get("verdicts", {}).get("duration") == "VERIFIED"
          and e.get("observed", {}).get("duration", {}).get("before") == "8s",
          repr(e.get("observed")))
    check("e: SIN click (cero interacción innecesaria)", e.get("clickChips") == [],
          repr(e.get("clickChips")))
    check("e: gate ALLOW_GENERATE", e.get("gateDecision") == "ALLOW_GENERATE",
          repr(e.get("gateDecision")))

    f = s("sin_spec")
    check("f: job sin execution_spec → NO corre config (ran false)",
          f.get("ran") is False, repr(f.get("ran")))
    check("f: sin veredictos, sin gate, sin clicks (camino de siempre)",
          f.get("verdicts") == {} and f.get("gateDecision") is None
          and f.get("clicked") == [], repr(f))

    gok = s("aspect_requerido_ok")
    check("g-ok: duración VERIFIED + aspect 9:16 VERIFIED",
          gok.get("verdicts", {}).get("duration") == "VERIFIED"
          and gok.get("verdicts", {}).get("aspect_ratio") == "VERIFIED",
          repr(gok.get("verdicts")))
    check("g-ok: gate ALLOW_GENERATE", gok.get("gateDecision") == "ALLOW_GENERATE",
          repr(gok.get("gateDecision")))
    gmm = s("aspect_requerido_mismatch")
    check("g-mm: aspect 16:9 inchangable → MISMATCH (observed 16:9)",
          gmm.get("verdicts", {}).get("aspect_ratio") == "MISMATCH"
          and gmm.get("observed", {}).get("aspect_ratio", {}).get("after") == "16:9",
          repr(gmm.get("observed")))
    check("g-mm: gate CONFIG_MISMATCH (duración OK no lo salva)",
          gmm.get("gateDecision") == "CONFIG_MISMATCH", repr(gmm.get("gateDecision")))
    check("g-mm: prefijo EXACTO 'CONFIG_MISMATCH: '",
          str(gmm.get("errorPrefix") or "").startswith("CONFIG_MISMATCH: "),
          repr(gmm.get("errorPrefix")))

    # ── 4. clicks 100% semánticos (§16: cero coordenadas) ─────────────────
    print("── 4. semántica de los clicks (sin coordenadas, §16)")
    todos = []
    for nombre in esperadas:
        todos.extend(s(nombre).get("clicked", []) or [])
    check("hay clicks registrados en la batería (el flujo interactuó)",
          len(todos) >= 3, repr(len(todos)))
    check("CADA click es un registro {tag,text,aria} (elemento, no posición)",
          all(set(c.keys()) == {"tag", "text", "aria"} for c in todos),
          repr(todos[:2]))
    check("CADA click apunta a un botón/radio semántico (tag button)",
          all(c.get("tag") == "button" for c in todos),
          repr(sorted({c.get("tag") for c in todos})))
    check("CERO claves posicionales (x/y/clientX/clientY/coords) en los clicks",
          all(not ({"x", "y", "clientX", "clientY", "coords", "point"} & set(c.keys()))
              for c in todos))

    # ── 5. normalización '8s' ≡ 8 ─────────────────────────────────────────
    print("── 5. normalización del spec (8s ≡ 8, 9:16 ≡ ' 9:16 ')")
    check("'8s' ≡ 8 con __flowNormVal REAL", norm.get("ocho_s_eq_ocho") is True,
          repr(norm))
    check("'8s' normaliza a '8'", norm.get("ocho_s_eq_8_str") is True, repr(norm))
    check("' 9:16 ' ≡ '9:16' (espacios fuera)", norm.get("aspecto_espacios") is True,
          repr(norm))
    check("'5s' ≠ 8 (la comparación discrimina de verdad)",
          norm.get("cinco_s_neq_ocho") is True, repr(norm))

    # ── 6. EXACTITUD: gate JS ≡ config_gate del backend ───────────────────
    print("── 6. espejo EXACTO: gate JS vs execution_contract.config_gate")

    def _spec_backend(nombre):
        """Spec en forma build_execution_spec para alimentar el gate backend
        con EXACTAMENTE la misma entrada que la extensión."""
        duration = 8 if nombre != "sin_spec" else None
        return {
            "schema_version": "1.0",
            "duration": {"requested": duration, "required": duration is not None,
                         "tolerance_seconds": 0},
            "model": {"requested": None, "required": False},
            "aspect_ratio": {"requested": "9:16", "required": True},
            "outputs": {"requested": 1, "required": True},
            "audio": {"requested": None, "required": False},
            "resolution": {"requested": None, "required": False},
            "references": [],
            "start_frame": None,
            "end_frame": None,
            "compatibility_policy": {"allow_inherited_state": False,
                                     "generate_requires_verified": True,
                                     "retry_on_config_error": False},
            "verification": {
                "duration": {"method": "ffprobe", "tolerance_seconds": 0,
                             "transport_epsilon_s": 0.25},
                "aspect_ratio": {"method": "ffprobe", "relative_tolerance": 0.02},
                "audio": {"method": "ffprobe", "gate": "register_only"},
                "outputs": {"method": "transport"},
            },
        }

    def _resultados_extension(nombre):
        cr = s(nombre).get("verdicts", {}) or {}
        obs = s(nombre).get("observed", {}) or {}
        out = {}
        for control, verdict in cr.items():
            o = obs.get(control) or {}
            out[control] = {
                "verdict": verdict,
                "observed": o.get("after") if o.get("after") is not None else o.get("before"),
            }
        return out

    esperado_backend = {
        "config_5s_a_8s_ok": "ALLOW_GENERATE",
        "unsupported": "CONFIG_UNSUPPORTED",
        "frozen_mismatch": "CONFIG_MISMATCH",
        "stale_unverifiable": "CONFIG_UNVERIFIABLE",
        "ya_configurado": "ALLOW_GENERATE",
        "aspect_requerido_ok": "ALLOW_GENERATE",
        "aspect_requerido_mismatch": "CONFIG_MISMATCH",
    }
    for nombre, decision_esperada in esperado_backend.items():
        js_decision = s(nombre).get("gateDecision")
        check(f"{nombre}: decisión JS correcta ({decision_esperada})",
              js_decision == decision_esperada, repr(js_decision))
        g = ec.config_gate(_spec_backend(nombre),
                           s(nombre).get("capabilities") or {},
                           _resultados_extension(nombre))
        check(f"{nombre}: gate backend REAL coincide con el gate JS",
              g["decision"] == js_decision,
              f"backend={g['decision']} js={js_decision}")

    # ── 7. limpieza ────────────────────────────────────────────────────────
    print("── 7. limpieza")
    shutil.rmtree(_TMP, ignore_errors=True)
    check("tmp eliminado", not _TMP.exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_flow_config_gate():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
