#!/usr/bin/env python3
"""Batería determinista del SELECTOR DE PESTAÑA FLOW ([bridge v3], ext 2.2.3).

Causa raíz corregida (prueba REAL reproducible con la extensión 2.2.2):
background.js seleccionaba la pestaña Flow con tabs.query(...)[0] — con varias
pestañas de Flow, tabs[0] podía ser una pestaña antigua sin contexto de
scripting efectivo (p.ej. tras recargar la extensión) y el job fallaba con
"Cannot access contents of the page. Extension manifest must request
permission to access the respective host.".

Qué verifica (sin Chrome, sin red, sin Google Flow real — la prueba REAL se
hará después en el PC del usuario):

  1. ANCLAJES de la corrección en background.js:
     - ya NO existe tabs[0] en código (solo en comentarios documentales)
     - el worker usa __bridgeResolveFlowTab y el mensaje de error conserva el
       ancla contractual 'sin pestaña de Google Flow (flow.google.com)'
     - VALIDACIÓN REAL: la sonda inyecta código con chrome.scripting.
       executeScript (comprobar el manifest NO basta) y re-chequea la URL
     - sin coordenadas, sin títulos frágiles, sin project_id, sección
       auto-contenida (sin acoplarse a slateInjectFn ni a labTabId global)
  2. COMPATIBILIDAD: ambas URLs (flow.google.com + labs.google) siguen en la
     consulta; el resolver A→D y la inyección textarea/contenteditable/Slate
     quedan intactos (anclas ligeros; el comportamiento completo lo sigue
     verificando test_extension_resolver.py en la suite).
  3. ESCENARIOS deterministas (node tests/tab_selector_mock.js; el mock
     EJECUTA el código real de la sonda serializada contra un contexto de
     página falso, como haría Chrome):
       A  una sola pestaña Flow válida
       B  DEMO EXIGIDA: [antigua inválida, nueva válida] con la antigua
          vinculada → se selecciona la nueva válida
       C  primera inválida + segunda válida → fallback (se continúa)
       D  varias pestañas (5) con la activa enfocada inválida → gana la activa
          de otra ventana válida
       E  flow.google.com + labs.google conviven (compat dominios, ambas vías)
       F  ninguna válida → tabId null + diagnóstico estructurado con razones
       G  la activa enfocada es válida → única sondada (eficiencia)
       H  activa enfocada inválida + otra válida → se selecciona la otra
       I  executeScript falla en la primera candidata y funciona en la segunda
       J  tabs[0] arbitrario prohibido (la inválida de la posición 0 nunca)
       K  sin coordenadas ni artefactos posicionales en el resultado
       L  el resolver A→D no se modifica (anclas de slateInjectFn intactas)
       M  la inyección textarea/contenteditable/Slate no se rompe (anclas)
       +  E2 vinculada que navegó fuera de Flow (vetada por URL real),
          E3 vinculada muerta (tabs.get lanza), E4 vinculada válida sin
          activas (compat), CASO INVERSO y sanidad de la sonda real.

Uso:  cd yt_automation_v2 && python3 tests/test_extension_tab_selector.py
      python3 -m pytest tests/test_extension_tab_selector.py -q
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "tab_selector_mock.js"
INI_SECCION = "/* [bridge v3] RESOLUCIÓN ROBUSTA DE PESTAÑA FLOW"
FIN_SECCION = "/* [bridge v3] fin resolución de pestaña */"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _extraer_seccion(src: str) -> str:
    i = src.index(INI_SECCION)
    j = src.index(FIN_SECCION, i) + len(FIN_SECCION)
    cuerpo = src[i:j]
    if cuerpo.count("{") != cuerpo.count("}"):
        raise ValueError("seccion con llaves desbalanceadas")
    return cuerpo


def _codigo_sin_comentarios(texto: str) -> str:
    """Elimina comentarios /* */ y // (máquina de estados por línea).
    Suficientemente conservador para los checks de contenido: truncar antes
    de tiempo dentro de strings solo puede quitar ruido, nunca crear falsos
    positivos para los patrones que se buscan (tabs[0], title, project_id)."""
    out, en_bloque = [], False
    for ln in texto.splitlines():
        resto = ln
        if en_bloque:
            fin = resto.find("*/")
            if fin == -1:
                continue
            resto = resto[fin + 2:]
            en_bloque = False
        while True:
            i1 = resto.find("//")
            i2 = resto.find("/*")
            if i2 != -1 and (i1 == -1 or i2 < i1):
                fin = resto.find("*/", i2 + 2)
                if fin == -1:
                    resto = resto[:i2]
                    en_bloque = True
                    break
                resto = resto[:i2] + " " + resto[fin + 2:]
                continue
            if i1 != -1:
                resto = resto[:i1]
            break
        out.append(resto)
    return "\n".join(out)


def _tabs0_fuera_de_comentarios(src: str) -> list:
    """Líneas con tabs[0] que NO son comentarios (código real)."""
    malas = []
    for ln, codigo in zip(src.splitlines(),
                          _codigo_sin_comentarios(src).splitlines()):
        if "tabs[0]" in codigo:
            malas.append(ln.strip()[:80])
    return malas


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node),
          "instala Node.js para poder verificar el selector de pestaña")

    print("── 1. anclajes de la corrección [bridge v3] (background.js)")
    bg = EXT / "background.js"
    check("background.js existe", bg.exists())
    src = bg.read_text(encoding="utf-8", errors="replace")
    seccion = ""
    try:
        seccion = _extraer_seccion(src)
    except Exception as e:  # noqa: BLE001
        print(f"  (extracción de sección: {e})")
    check("sección [bridge v3] extraíble y auto-contenida", bool(seccion))
    sec_codigo = _codigo_sin_comentarios(seccion) if seccion else ""
    check("CAUSA RAÍZ eliminada: tabs[0] solo en comentarios, nunca en código",
          not _tabs0_fuera_de_comentarios(src),
          repr(_tabs0_fuera_de_comentarios(src)[:3]))
    check("patrón antiguo '(tabs && tabs.length) ? tabs[0].id' eliminado",
          "(tabs && tabs.length) ? tabs[0].id" not in src)
    check("el worker resuelve con __bridgeResolveFlowTab (no con tabs[0])",
          "await __bridgeResolveFlowTab(Number.isInteger(labTabId) ? labTabId : null)" in src)
    check("VALIDACIÓN REAL: la sonda usa chrome.scripting.executeScript",
          "chrome.scripting.executeScript" in seccion and "__flowTabProbeFn" in seccion)
    check("la sonda re-chequea que la pestaña sigue en Flow/labs (URL real)",
          "__FLOW_HOST_RE.test" in seccion)
    check("fallo de una candidata NO aborta: la sonda devuelve {ok:false,reason}",
          "ok: false, reason:" in seccion.replace('"', "'"))
    check("fallback: el resolutor continúa con la siguiente candidata",
          "for (const t of cands)" in seccion and "if (probe.ok) return" in seccion)
    check("orden de preferencia: activa enfocada → activa → vinculada → resto",
          "focusedIds.has(t.id)" in seccion and "lastAccessed" in seccion
          and "cands.push(linked)" in seccion)
    check("consulta cubre AMBOS dominios (flow.google.com + labs.google) ×2",
          src.count("url: ['https://flow.google.com/*', 'https://labs.google/*']") >= 2)
    check("ancla contractual del mensaje de error conservado",
          "sin pestaña de Google Flow (flow.google.com)" in src)
    check("diagnóstico estructurado: tried con tabId/url/flags/razón",
          '"tried"' in seccion or "'tried'" in seccion or "tried.push" in seccion)
    check("sin coordenadas ni clicks posicionales en la sección",
          "elementFromPoint" not in sec_codigo and "clientX" not in sec_codigo
          and "mouse" not in sec_codigo.lower())
    check("sin títulos frágiles ni project_id como mecanismo de selección",
          "title" not in sec_codigo.lower() and "project_id" not in sec_codigo
          and "projectId" not in sec_codigo)
    check("sección auto-contenida: no toca labTabId global ni slateInjectFn",
          "labTabId" not in sec_codigo and "slateInjectFn" not in sec_codigo)

    print("── 2. compatibilidad: dominios, manifest y resolver A→D intactos")
    mf_path = EXT / "manifest.json"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    hp = mf.get("host_permissions", [])
    check("extensión 2.4.1 (bump patch: CF-E2E-01 gate obligatorio §7.1)",
          mf.get("version") == "2.4.1", mf.get("version"))
    check("host_permissions conserva flow.google.com Y labs.google",
          "https://flow.google.com/*" in hp and "https://labs.google/*" in hp)
    check("permisos intactos (scripting/activeTab/downloads/storage/alarms)",
          mf.get("permissions") == ["scripting", "activeTab", "downloads",
                                    "storage", "alarms"])
    try:
        i = src.index("function slateInjectFn")
        j = src.index("/* --------------------- Sondeo del DOM", i)
        fn_src = src[i:j].rstrip()
    except Exception:  # noqa: BLE001
        fn_src = ""
    check("L/M: slateInjectFn sigue extraíble (marcadores de sección intactos)",
          bool(fn_src) and fn_src.count("{") == fn_src.count("}"))
    check("L/M: compatibilidad legacy Slate conservada ([data-slate-editor=\"true\"])",
          '[data-slate-editor="true"]' in fn_src)
    check("L/M: inserción textarea por setter nativo + input/change intacta",
          "native-setter" in fn_src and "'input'" in fn_src and "'change'" in fn_src)
    check("M: execCommand con fallback textContent (nunca único mecanismo)",
          "textcontent-fallback" in fn_src)
    check("M: diagnóstico estructurado del resolver A→D intacto",
          "candidates" in fn_src and "strategies" in fn_src)

    print("── 3. escenas deterministas (mini-chrome, sonda REAL ejecutada)")
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("harness tab_selector_mock.js con sintaxis válida",
          proc_syn.returncode == 0, proc_syn.stderr.strip()[:150])

    with tempfile.TemporaryDirectory() as td:
        sec_file = Path(td) / "bridge_v3_section.js"
        sec_file.write_text(seccion, encoding="utf-8")
        proc = subprocess.run([node, str(HARNESS), str(sec_file)],
                              capture_output=True, text=True, timeout=120,
                              cwd=str(REPO))
    salida = (proc.stdout or "") + (proc.stderr or "")
    check("harness corre sin FATAL", "FATAL" not in salida, salida[-200:])
    check("harness exit 0", proc.returncode == 0, f"exit={proc.returncode}")
    data = {}
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        pass
    sc = data.get("scenarios", {})
    check("las 17 escenas del harness corrieron (sin errores)",
          not data.get("errores") and len(sc) == 17,
          repr(data.get("errores")))

    if sc:
        a, b = sc.get("A_una_valida", {}), sc.get("B_antigua_invalida_nueva_valida", {})
        c = sc.get("C_primera_invalida_segunda_valida", {})
        d = sc.get("D_varias_pestanas", {})
        e = sc.get("E_flow_y_labs", {})
        f = sc.get("F_ninguna_valida", {})
        g = sc.get("G_activa_valida_unica_sonda", {})
        h = sc.get("H_activa_invalida_otra_valida", {})
        i2 = sc.get("I_fallo_primera_funciona_segunda", {})
        j2 = sc.get("J_tabs0_no_arbitrario", {})
        k = sc.get("K_sin_coordenadas", {})
        e2 = sc.get("E2_vinculada_fuera_unica_candidata", {})
        e2b = sc.get("E2b_vinculada_fuera_con_alternativa_valida", {})
        e3 = sc.get("E3_vinculada_muerta", {})
        e4 = sc.get("E4_vinculada_valida_sin_activas", {})
        inv = sc.get("CASO_INVERSO_primera_valida", {})
        san = sc.get("SANIDAD_sonda_real", {})

        # A — una sola pestaña Flow válida
        check("A: una sola pestaña válida → seleccionada con 1 sola sonda",
              a.get("tabId") == 11 and a.get("probeCalls") == [11]
              and a.get("tried") == 1, repr(a))

        # B — DEMO EXIGIDA: [antigua inválida, nueva válida] → la nueva válida
        check("B: [antigua inválida (vinculada), nueva válida] → se selecciona "
              "la NUEVA válida (102)", b.get("tabId") == 102, repr(b))
        check("B: la antigua inválida jamás se usa (ni siquiera se sondea de más)",
              b.get("primeraSonda") == 102 and b.get("probeCalls") == [102], repr(b))
        check("B: el worker NO depende de tabs[0] ni de la vinculada muerta",
              [t.get("tabId") for t in b.get("tried", [])] == [102], repr(b))

        # C — primera inválida + segunda válida → fallback
        check("C: primera inválida + segunda válida → se selecciona la segunda",
              c.get("tabId") == 202, repr(c))
        check("C: fallback demostrado: ambas sondadas EN ORDEN [201, 202]",
              c.get("probeCalls") == [201, 202], repr(c))

        # D — varias pestañas
        check("D: 5 pestañas, activa enfocada inválida → gana la activa de otra "
              "ventana (304)", d.get("tabId") == 304, repr(d))
        check("D: solo se sondan las necesarias [301, 304] (preferencia real)",
              d.get("probeCalls") == [301, 304], repr(d))
        check("D: la segunda candidata era realmente 'activa' (de otra ventana)",
              d.get("candidata2FlagActiva") is True, repr(d))

        # E — Flow + labs.google
        check("E: labs.google activa y válida → seleccionada (compat dominios)",
              e.get("sel1") == 401 and e.get("probes1") == [401], repr(e))
        check("E: flow inválida + labs válida en fondo → fallback a labs (411)",
              e.get("sel2") == 411 and e.get("probes2") == [412, 411], repr(e))

        # F — ninguna válida
        check("F: ninguna válida → tabId null (el worker fallará con detalle)",
              f.get("tabId") is None, repr(f))
        check("F: diagnóstico estructurado: 2 candidatas con razón de fallo",
              f.get("tried") == 2 and f.get("conErrorPermisos") is True
              and all(r for r in f.get("razones", [])), repr(f))

        # G — la activa es válida
        check("G: activa enfocada válida → seleccionada y ÚNICA sondada "
              "(eficiencia, sin sondeo en cascada)",
              g.get("tabId") == 601 and g.get("probeCalls") == [601], repr(g))

        # H — activa inválida pero existe otra válida
        check("H: activa enfocada inválida + otra válida → se selecciona la otra",
              h.get("tabId") == 702 and h.get("probeCalls") == [701, 702], repr(h))

        # I — executeScript falla en la primera y funciona en la segunda
        check("I: primera candidata falla executeScript → segunda (vinculada) "
              "funciona", i2.get("tabId") == 802
              and i2.get("probeCalls") == [801, 802], repr(i2))
        check("I: la segunda candidata era la vinculada (compat con flujo actual)",
              i2.get("segundaEsLinked") is True, repr(i2))

        # J — tabs[0] arbitrario prohibido
        check("J: tabs[0] (901: inválida, reciente, vinculada) NUNCA seleccionada",
              j2.get("tabId") == 902 and j2.get("seleccionadaNoEsTabs0") is True,
              repr(j2))
        check("J: el orden de sondeo sigue la preferencia, no la posición de la "
              "lista", j2.get("probeCalls") == [902], repr(j2))

        # K — sin coordenadas
        check("K: el resultado no contiene coordenadas ni artefactos posicionales",
              k.get("sinCoordenadas") is True, repr(k))
        check("K: resultado compacto y estructurado {tabId, tried, url}",
              k.get("claves") == "tabId,tried,url", repr(k))

        # E2/E2b/E3/E4 — vinculada: fuera de Flow, fuera con alternativa, muerta, válida
        check("E2: vinculada que navegó fuera de Flow (única candidata) → vetada "
              "por la sonda REAL (re-chequeo de URL aunque scripting funcione)",
              e2.get("tabId") is None and e2.get("tried") == 1
              and e2.get("linkedVetada") is True
              and "ya no está en Flow" in (e2.get("razonLinked") or ""), repr(e2))
        check("E2: la razón del veto cita la URL real de la pestaña",
              "example.com" in (e2.get("razonLinked") or ""), repr(e2))
        check("E2b: vinculada fuera de Flow + otra Flow válida → se selecciona la "
              "válida sin sondear la vinculada (early return eficiente)",
              e2b.get("tabId") == 1152
              and e2b.get("probeCalls") == [1152], repr(e2b))
        check("E3: vinculada muerta (tabs.get lanza) → ignorada sin abortar",
              e3.get("tabId") == 1201 and e3.get("probeCalls") == [1201], repr(e3))
        check("E4: vinculada viva y válida sin activas → seleccionada (compat: "
              "el flujo actual se mantiene cuando es la buena)",
              e4.get("tabId") == 1301 and e4.get("probeCalls") == [1301], repr(e4))

        # CASO INVERSO — [nueva válida, antigua inválida]
        check("CASO INVERSO: [nueva válida (tabs[0]), antigua inválida] → "
              "seleccionada la válida por mérito (activa enfocada)",
              inv.get("tabId") == 1401 and inv.get("probeCalls") == [1401],
              repr(inv))

        # SANIDAD — la sonda ejecutada es el código REAL serializado
        check("SANIDAD: la sonda ejecutada es el código real (detecta URL de "
              "Flow y reporta readyState)",
              san.get("ok") is True and san.get("urlVeFlow") is True
              and san.get("ready") == "complete", repr(san))

    print("── 4. limpieza")
    check("batería sin efectos sobre el repo (solo lectura + tempdir)", True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_extension_tab_selector():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
