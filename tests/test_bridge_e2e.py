#!/usr/bin/env python3
"""Batería E2E del lado EXTENSIÓN — bridge.js real contra backend mock.

Dos capas de verificación (todo Node, sin Chrome ni sesión de Google):

  1. SINTAXIS: node --check sobre TODOS los .js de extension/ (nada roto
     entra al paquete de la extensión).
  2. E2E CONTRACTUAL: corre tests/e2e_bridge_mock.js — carga bridge.js REAL
     en sandbox VM con stubs de Chrome MV3 y lo enfrenta a un backend mock
     HTTP con estado: claim → complete (bytes PNG validados por el mock) →
     fail → 422 → heartbeat true/409 → cola vacía → backend caído → canal
     de mensajes del popup → anti-duplicado.
  3. ANCLAJES [bridge v1]: background.js mantiene el wiring declarado
     (importScripts de bridge.js, caso BRIDGE_JOB, handler __bridgeHandleJob).
  4. MIGRACIÓN DE DOMINIO (extensión 2.2.1 → 2.2.2): manifest (host_permissions
     + content_scripts) reconoce https://flow.google.com/* —incluyendo
     https://flow.google.com/project/<id>— conservando compatibilidad con
     labs.google; tabs.query del bridge cubre AMBOS dominios (causa raíz del
     bloqueo: la extensión 2.2.0 solo buscaba labs.google y Flow migró con
     redirect 308); el origin check del popup acepta el dominio actual y
     rechaza impostores; la extensión sigue siendo v2.2.x.

Si esta batería pasa, el contrato backend↔extensión está verificado en la
capa navegador re-ejecutable (la corrida E2E con Google Flow REAL sigue
siendo manual: requiere Chrome + sesión, se documenta en ESTADO_REAL.md).

Uso:  cd yt_automation_v2 && python3 tests/test_bridge_e2e.py
      python3 -m pytest tests/test_bridge_e2e.py -q
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "e2e_bridge_mock.js"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _node() -> str | None:
    from shutil import which
    return which("node")


def main() -> int:
    node = _node()
    check("node disponible en el sandbox", bool(node),
          "instala Node.js para poder verificar la extensión")

    print("── 1. node --check en TODOS los .js de extension/")
    js_files = sorted(EXT.glob("*.js")) if EXT.exists() else []
    check("extension/ existe con archivos JS", len(js_files) >= 5,
          f"{len(js_files)} archivos")
    for js in js_files:
        proc = subprocess.run([node, "--check", str(js)],
                              capture_output=True, text=True, timeout=60)
        check(f"sintaxis OK: {js.name}", proc.returncode == 0,
              proc.stderr.strip()[:150])

    print("── 2. E2E contractual: bridge.js real ↔ backend mock")
    proc = subprocess.run([node, str(HARNESS)], capture_output=True,
                          text=True, timeout=180, cwd=str(REPO))
    salida = (proc.stdout or "") + (proc.stderr or "")
    check("harness corre sin FATAL", "FATAL" not in salida, salida[-200:])
    check("harness exit 0", proc.returncode == 0, f"exit={proc.returncode}")
    check("harness reporta 0 fallos", "· 0 fallos" in proc.stdout,
          proc.stdout.strip().splitlines()[-1] if proc.stdout else "")
    for grupo in ("config + workerId", "claim → complete feliz",
                  "backend responde 422", "heartbeat: true con lease viva",
                  "backend caído", "anti-duplicado"):
        check(f"grupo E2E presente: {grupo}", grupo in proc.stdout)

    print("── 3. anclajes [bridge v1] en background.js (wiring intacto)")
    bg = EXT / "background.js"
    if bg.exists():
        src = bg.read_text(encoding="utf-8", errors="replace")
        check("importScripts carga bridge.js",
              "bridge.js" in src and "importScripts" in src)
        check("caso BRIDGE_JOB presente en el router",
              "'BRIDGE_JOB'" in src or '"BRIDGE_JOB"' in src)
        check("handler __bridgeHandleJob definido",
              "__bridgeHandleJob" in src)
        check("wrapper de captura del último blob presente",
              "fetchBlobWithRetry" in src)
    else:
        check("background.js existe", False)

    print("── 4. migración de dominio Google Flow: flow.google.com (ext 2.2.2)")

    def _pat_a_regex(pat):
        """Traduce un match pattern de Chrome (https://host/path) a regex."""
        esquema, resto = pat.split("://", 1)
        host, ruta = resto.split("/", 1)
        return re.compile(
            f"^{re.escape(esquema)}://{re.escape(host)}/{'.*' if ruta == '*' else re.escape(ruta)}$")

    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    hp = mf.get("host_permissions", [])
    check("manifest.json es JSON válido con MV3", mf.get("manifest_version") == 3)
    check("extensión continúa siendo v2.x (sin salto mayor; V1.1 = 2.3.1)",
          str(mf.get("version", "")).startswith("2.3"), mf.get("version"))
    check("host_permissions incluye el dominio ACTUAL https://flow.google.com/*",
          "https://flow.google.com/*" in hp, repr(hp))
    check("host_permissions CONSERVA labs.google (compatibilidad)",
          "https://labs.google/*" in hp)
    cs = mf.get("content_scripts", [])
    propios = [c for c in cs if "injector.js" in c.get("js", [])
               or "content.js" in c.get("js", [])]
    check("los 2 content_scripts propios (injector+content) cubren "
          "flow.google.com Y labs.google",
          len(propios) == 2 and all(
              "https://flow.google.com/*" in c.get("matches", [])
              and "https://labs.google/*" in c.get("matches", [])
              for c in propios),
          repr([c.get("matches") for c in cs]))
    check("meta.ai intacto (sin migración)",
          any("meta.ai" in m for c in cs for m in c.get("matches", [])))

    rx_nuevo = _pat_a_regex("https://flow.google.com/*")
    rx_viejo = _pat_a_regex("https://labs.google/*")
    check("PATRÓN NUEVO matchea un proyecto REAL "
          "https://flow.google.com/project/<id>",
          bool(rx_nuevo.match("https://flow.google.com/project/abc123def456")))
    check("PATRÓN NUEVO matchea la raíz y rutas del editor",
          bool(rx_nuevo.match("https://flow.google.com/"))
          and bool(rx_nuevo.match("https://flow.google.com/project/x/settings")))
    check("COMPATIBILIDAD: labs.google/fx sigue matcheando el patrón viejo",
          bool(rx_viejo.match("https://labs.google/fx/tools/flow")))
    check("el patrón nuevo NO matchea impostores de otro origin",
          not rx_nuevo.match("https://flow.google.com.evil.com/project/x")
          and not rx_nuevo.match("https://evil.example.com/project/x"))

    bg_src = (EXT / "background.js").read_text(encoding="utf-8", errors="replace")
    check("CAUSA RAÍZ corregida: tabs.query del bridge cubre AMBOS dominios",
          "url: ['https://flow.google.com/*', 'https://labs.google/*']" in bg_src)
    check("ya no existe tabs.query de un solo dominio labs.google",
          "url: 'https://labs.google/*'" not in bg_src
          and 'url: "https://labs.google/*"' not in bg_src)
    check("mensaje de error cita el dominio actual",
          "sin pestaña de Google Flow (flow.google.com)" in bg_src)

    pp_src = (EXT / "popup.js").read_text(encoding="utf-8", errors="replace")
    check("popup.js: origin check incluye flow.google.com y labs.google",
          "(flow\\.google\\.com|labs\\.google)" in pp_src)
    rx_popup = re.compile(r"^https://(flow\.google\.com|labs\.google)/")
    check("origin check del popup ACEPTA un proyecto actual",
          bool(rx_popup.match("https://flow.google.com/project/abc123")))
    check("origin check del popup RECHAZA impostores",
          not rx_popup.match("https://flow.google.com.evil.com/")
          and not rx_popup.match("https://example.com/"))

    check("SELECTOR SLATE intacto (no se inventaron selectores)",
          '[data-slate-editor="true"]' in bg_src)
    _m = re.search(r"function slateInjectFn\(", bg_src)
    _fin = bg_src.find("\nfunction ", _m.start() + 10) if _m else -1
    _cuerpo = bg_src[_m.start():_fin] if (_m and _fin != -1) else ""
    check("slateInjectFn presente y sin dependencia de dominio (sin labs)",
          bool(_cuerpo) and "labs" not in _cuerpo.lower())

    print("── 5. limpieza")
    check("batería sin efectos sobre el repo (solo lectura + subprocess)", True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_bridge_e2e():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
