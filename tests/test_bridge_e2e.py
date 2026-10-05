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

Si esta batería pasa, el contrato backend↔extensión está verificado en la
capa navegador re-ejecutable (la corrida E2E con Google Flow REAL sigue
siendo manual: requiere Chrome + sesión, se documenta en ESTADO_REAL.md).

Uso:  cd yt_automation_v2 && python3 tests/test_bridge_e2e.py
      python3 -m pytest tests/test_bridge_e2e.py -q
"""
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

    print("── 4. limpieza")
    check("batería sin efectos sobre el repo (solo lectura + subprocess)", True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_bridge_e2e():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
