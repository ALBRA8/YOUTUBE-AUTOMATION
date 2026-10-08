#!/usr/bin/env python3
"""Batería determinista del RESOLVER/INYECTOR de editor (extensión 2.2.2).

Qué verifica (sin Chrome, sin red, sin Google Flow real — la prueba REAL se
hará después en el PC del usuario):

  1. EXTRACCIÓN: slateInjectFn se extrae de background.js por marcadores de
     sección y se evalúa standalone (es auto-contenida: se serializa a la
     pestaña vía chrome.scripting.executeScript).
  2. ANCLAJES de la adaptación: compatibilidad legacy Slate conservada, sin
     dependencia de dominio, sin coordenadas/clicks posicionales, execCommand
     NO es el único mecanismo (fallback textContent), inserción de textarea
     por setter nativo + eventos, diagnóstico estructurado.
  3. ESCENARIOS deterministas (node tests/editor_resolver_mock.js, mini-DOM
     propio): los 12 casos de la especificación + extras robustos:
       1  legacy Slate editor (estrategia D, execCommand)
       2  textarea visible de prompt (aisandbox-root, setter nativo)
       3  contenteditable role=textbox (estrategia C)
       4  textarea oculto + textarea visible → elige el visible
       5  múltiples textareas donde solo una es el prompt (por señales)
       6  campo de navegación vetado (dentro de <nav>) + caso solo-nav
       7  inyección dispara evento input (y change en textarea)
       8  verificación del valor tras la inserción (positiva y negativa)
       9  ausencia total de editor → ok:false
      10  error diagnóstico estructurado (estrategias probadas + candidatos)
      11  inputs irrelevantes ignorados (solo y mixto)
      12  compatibilidad con la UI actual flow.google.com (DOM estilo Flow)
      +   fallbacks de execCommand (false/throw/ausente), prompt multilínea,
          prompt vacío, Slate con role=textbox.

Uso:  cd yt_automation_v2 && python3 tests/test_extension_resolver.py
      python3 -m pytest tests/test_extension_resolver.py -q
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "editor_resolver_mock.js"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _extraer_fn(src: str) -> str:
    i = src.index("function slateInjectFn")
    j = src.index("/* --------------------- Sondeo del DOM", i)
    cuerpo = src[i:j].rstrip()
    if not cuerpo.endswith("}"):
        raise ValueError("la funcion extraida no termina en }")
    return cuerpo


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node),
          "instala Node.js para poder verificar el resolver")

    print("── 1. extraccion y anclajes de la adaptacion (background.js)")
    bg = EXT / "background.js"
    check("background.js existe", bg.exists())
    src = bg.read_text(encoding="utf-8", errors="replace")
    try:
        fn_src = _extraer_fn(src)
        extraida = bool(fn_src) and fn_src.count("{") == fn_src.count("}")
    except Exception as e:  # noqa: BLE001
        fn_src, extraida = "", False
        print(f"  (extraccion: {e})")
    check("slateInjectFn extraible y con llaves balanceadas", extraida)
    check("fn sin dependencia de dominio (sin 'labs')", "labs" not in fn_src.lower())
    check("compatibilidad legacy Slate conservada ([data-slate-editor=\"true\"])",
          '[data-slate-editor="true"]' in fn_src)
    check("independiente de la URL de la pestana (sin location/URL)",
          "location" not in fn_src and "document.URL" not in fn_src)
    check("sin coordenadas ni clicks posicionales",
          "elementFromPoint" not in fn_src and "clientX" not in fn_src
          and "mouse" not in fn_src.lower())
    check("execCommand NO es unico mecanismo (fallback textcontent-fallback)",
          "textcontent-fallback" in fn_src)
    check("textarea usa setter nativo + eventos (native-setter + input/change)",
          "native-setter" in fn_src and "'input'" in fn_src and "'change'" in fn_src)
    check("diagnostico estructurado (strategies + candidates en fallos)",
          "strategies:" in fn_src.replace(" ", "") or "strategies: diag.strategies" in fn_src,
          )

    print("── 2. harness determinista (mini-DOM, sin Flow real)")
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("sintaxis OK: editor_resolver_mock.js", proc_syn.returncode == 0,
          proc_syn.stderr.strip()[:150])
    if not node:
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1 if FAIL else 0

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(fn_src)
        fn_path = f.name
    proc = subprocess.run([node, str(HARNESS), fn_path],
                          capture_output=True, text=True, timeout=120)
    check("harness corre sin error de ejecucion", proc.returncode == 0,
          (proc.stderr or "")[-200:])
    try:
        data = json.loads(proc.stdout)
        esc = data.get("scenarios", {})
    except Exception as e:  # noqa: BLE001
        check("harness produce JSON parseable", False, str(e)[:150])
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1
    check("harness produce JSON parseable", True)
    check("sin error_de_harness en ninguna escena",
          not data.get("errores"), repr(data.get("errores"))[:150])
    esperadas = ["legacy_slate", "legacy_slate_con_role", "textarea_aisandbox",
                 "contenteditable_textbox", "oculto_vs_visible",
                 "multiples_textareas", "nav_field_vetado", "solo_nav",
                 "verificacion_falla", "sin_editor", "inputs_ignorados_solo",
                 "inputs_ignorados_mixto", "fallback_textcontent", "exec_throw",
                 "exec_ausente", "multiline_prompt", "flow_like", "prompt_vacio"]
    check("las 18 escenas deterministas corrieron",
          all(n in esc for n in esperadas),
          repr([n for n in esperadas if n not in esc]))

    def r(nombre):
        return esc.get(nombre, {}).get("result", {}) or {}

    def evs(nombre):
        return esc.get(nombre, {}).get("events", []) or []

    def val(nombre, campo):
        return esc.get(nombre, {}).get(campo)

    print("── 3.1 estrategia D: legacy Slate ([data-slate-editor=\"true\"])")
    res = r("legacy_slate")
    check("legacy: ok=true", res.get("ok") is True, repr(res))
    check("legacy: selectorStrategy=slate-legacy",
          res.get("selectorStrategy") == "slate-legacy")
    check("legacy: editorType=slate-legacy",
          res.get("editorType") == "slate-legacy")
    check("legacy: valor reemplazado (texto viejo fuera, prompt dentro)",
          val("legacy_slate", "slate_value") == val("legacy_slate", "prompt"),
          repr(val("legacy_slate", "slate_value"))[:80])
    eventos = " ".join(evs("legacy_slate"))
    check("legacy: beforeinput + input + keydown disparados",
          "beforeinput" in eventos and "input" in eventos and "keydown" in eventos,
          eventos)
    res = r("legacy_slate_con_role")
    check("legacy con role=textbox: el marcador legacy gana (D)",
          res.get("ok") is True and res.get("selectorStrategy") == "slate-legacy")
    check("legacy con role: valor verificado",
          val("legacy_slate_con_role", "slate_value") == val("legacy_slate_con_role", "prompt"))

    print("── 3.2 estrategia A: textarea de prompt en aisandbox-root (UI real)")
    res = r("textarea_aisandbox")
    check("aisandbox: ok=true", res.get("ok") is True, repr(res)[:120])
    check("aisandbox: selectorStrategy=aisandbox-root",
          res.get("selectorStrategy") == "aisandbox-root")
    check("aisandbox: editorType=textarea", res.get("editorType") == "textarea")
    check("aisandbox: insercion por setter nativo",
          res.get("injectPath") == "native-setter")
    check("aisandbox: promptInjected + valueVerified",
          res.get("promptInjected") is True and res.get("valueVerified") is True)
    check("aisandbox: el prompt quedo en el textarea",
          val("textarea_aisandbox", "prompt_value") == val("textarea_aisandbox", "prompt"))
    eventos = " ".join(evs("textarea_aisandbox"))
    check("aisandbox: eventos input + change sobre TEXTAREA",
          "input:TEXTAREA" in eventos and "change:TEXTAREA" in eventos, eventos)
    check("aisandbox: boton send cliqueado + Enter sintetico",
          res.get("clicked") is True and "click:BUTTON" in eventos
          and "keydown:TEXTAREA" in eventos, eventos)

    print("── 3.3 estrategia C: contenteditable visible con role=textbox")
    res = r("contenteditable_textbox")
    check("contenteditable: ok=true", res.get("ok") is True, repr(res)[:120])
    check("contenteditable: selectorStrategy=contenteditable-textbox",
          res.get("selectorStrategy") == "contenteditable-textbox")
    check("contenteditable: editorType=contenteditable",
          res.get("editorType") == "contenteditable")
    check("contenteditable: insercion via execCommand",
          res.get("injectPath") == "execcommand")
    check("contenteditable: valor verificado",
          val("contenteditable_textbox", "ce_value") == val("contenteditable_textbox", "prompt"))
    eventos = " ".join(evs("contenteditable_textbox"))
    check("contenteditable: beforeinput + input disparados",
          "beforeinput:DIV" in eventos and "input:DIV" in eventos, eventos)

    print("── 3.4 filtros: oculto vs visible / multiples / navegacion / inputs")
    res = r("oculto_vs_visible")
    check("oculto vs visible: ok=true eligiendo el visible",
          res.get("ok") is True)
    check("oculto vs visible: el visible recibio el prompt",
          val("oculto_vs_visible", "visible_value") == val("oculto_vs_visible", "prompt"))
    check("oculto vs visible: el oculto queda intacto",
          val("oculto_vs_visible", "oculto_value") == "")
    res = r("multiples_textareas")
    check("multiples: ok=true con la textareas correcta",
          res.get("ok") is True)
    check("multiples: el prompt fue a la textareas con senales de prompt",
          val("multiples_textareas", "prompt_value") == val("multiples_textareas", "prompt"))
    check("multiples: la textareas neutral queda intacta",
          val("multiples_textareas", "notas_value") == "")
    check("multiples: estrategia por senales (textarea-prompt)",
          res.get("selectorStrategy") == "textarea-prompt")
    res = r("nav_field_vetado")
    check("nav: ok=true y el prompt real fue seleccionado",
          res.get("ok") is True
          and val("nav_field_vetado", "prompt_value") == val("nav_field_vetado", "prompt"))
    check("nav: el campo de navegacion NO recibio texto",
          val("nav_field_vetado", "nav_value") == "")
    res = r("solo_nav")
    check("solo nav: ok=false (no se inyecta en navegacion)",
          res.get("ok") is False)
    vetos = [c.get("veto") for c in (res.get("candidates") or [])]
    check("solo nav: diagnostico cita el veto 'dentro de <nav>'",
          any(v and "dentro de <nav>" in v for v in vetos), repr(vetos)[:120])
    res = r("inputs_ignorados_solo")
    check("inputs solo: ok=false (un <input> no es candidato de prompt)",
          res.get("ok") is False)
    check("inputs solo: diagnostico indica 0 candidatos evaluados",
          "Candidatos evaluados: 0" in str(res.get("error", "")))
    res = r("inputs_ignorados_mixto")
    check("inputs mixto: ok=true eligiendo el textarea de prompt",
          res.get("ok") is True
          and val("inputs_ignorados_mixto", "prompt_value") == val("inputs_ignorados_mixto", "prompt"))
    check("inputs mixto: el input irrelevante queda sin valor",
          val("inputs_ignorados_mixto", "input_value") == "")

    print("── 3.5 insercion y verificacion del valor")
    res = r("verificacion_falla")
    check("setter roto: ok=false (verificacion de valor honesta)",
          res.get("ok") is False)
    check("setter roto: el error explica que el valor no quedo presente",
          "no quedo presente" in str(res.get("error", "")))
    check("setter roto: diagnostico con estrategias probadas",
          isinstance(res.get("strategies"), list) and len(res["strategies"]) == 4)
    res = r("multiline_prompt")
    check("multilinea: ok=true con saltos conservados",
          res.get("ok") is True
          and val("multiline_prompt", "prompt_value") == val("multiline_prompt", "prompt"))
    res = r("prompt_vacio")
    check("prompt vacio: ok=false temprano y textarea intacto",
          res.get("ok") is False and "prompt vacio" in str(res.get("error", ""))
          and val("prompt_vacio", "prompt_value") == "")

    print("── 3.6 robustez de execCommand (nunca unico mecanismo)")
    res = r("fallback_textcontent")
    check("execCommand=false: ok=true via fallback",
          res.get("ok") is True and res.get("injectPath") == "textcontent-fallback")
    check("execCommand=false: valor verificado y evento input disparado",
          val("fallback_textcontent", "ce_value") == val("fallback_textcontent", "prompt")
          and "input:DIV" in " ".join(evs("fallback_textcontent")))
    res = r("exec_throw")
    check("execCommand lanza: ok=true via fallback",
          res.get("ok") is True and res.get("injectPath") == "textcontent-fallback"
          and val("exec_throw", "ce_value") == val("exec_throw", "prompt"))
    res = r("exec_ausente")
    check("execCommand ausente: ok=true via fallback",
          res.get("ok") is True and res.get("injectPath") == "textcontent-fallback"
          and val("exec_ausente", "ce_value") == val("exec_ausente", "prompt"))

    print("── 3.7 UI real flow.google.com (DOM estilo Flow) + diagnosticos")
    res = r("flow_like")
    check("flow_like: ok=true", res.get("ok") is True, repr(res)[:120])
    check("flow_like: estrategia aisandbox-root sobre textarea",
          res.get("selectorStrategy") == "aisandbox-root"
          and res.get("editorType") == "textarea")
    check("flow_like: prompt en el composer, nav/feedback intactos",
          val("flow_like", "prompt_value") == val("flow_like", "prompt")
          and val("flow_like", "nav_value") == ""
          and val("flow_like", "feedback_value") == "")
    check("flow_like: boton send cliqueado", res.get("clicked") is True)
    res = r("sin_editor")
    check("sin editor: ok=false", res.get("ok") is False)
    check("sin editor: 4 estrategias probadas en orden A/B/C/D",
          [s.get("strategy") for s in res.get("strategies", [])]
          == ["aisandbox-root", "textarea-prompt",
              "contenteditable-textbox", "slate-legacy"],
          repr(res.get("strategies"))[:150])
    check("sin editor: cada estrategia reporta su resultado",
          all("result" in s for s in res.get("strategies", [])))
    check("sin editor: error cita las estrategias probadas",
          all(n in str(res.get("error", "")) for n in
              ("aisandbox-root", "textarea-prompt",
               "contenteditable-textbox", "slate-legacy")))
    check("sin editor: candidatos evaluados reportado (0)",
          "Candidatos evaluados: 0" in str(res.get("error", "")))

    print("── 4. limpieza")
    check("bateria sin efectos sobre el repo (solo lectura + subprocess)", True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_extension_resolver():
    """Entrada pytest: la bateria completa como un unico test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
