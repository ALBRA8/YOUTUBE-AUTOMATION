#!/usr/bin/env python3
"""[CIERRE D4/D6/D7] Batería GUARDIÁN del registro canónico + aceptaciones.

  D6 · REGISTRO: cada tests/**/test_*.py del árbol DEBE estar en
       BATERIAS (run_all) o en EXCLUDED_BATTERIES con motivo escrito.
       También: cada entrada existe en disco, sin duplicados, sin
       intersección, y conftest.collect_ignore == PYTEST_IGNORADAS.
  D4 · TIMEOUT: correr tests/test_d4_timeout_sleep.py (duerme 400 s) con
       --timeout-seg 5 debe TERMINAR, reportar "TIMEOUT" y no dejar
       procesos hijos vivos.
  D7 · HERMÉTICA: con tests/hermetic_guard/sitecustomize.py en PYTHONPATH,
       getaddrinfo/connect a hosts externos QUEMAN y el loopback sigue
       funcionando (servidor HTTP real en 127.0.0.1).

Uso:  python tests/test_registro_baterias.py
      python3 -m pytest tests/test_registro_baterias.py -q
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import run_all as ra  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _guardian_registro():
    print("── A. D6: registro canónico de baterías ──")
    en_disco = sorted(
        p.relative_to(TESTS_DIR).as_posix()
        for p in TESTS_DIR.rglob("test_*.py"))
    registradas = set(ra.BATERIAS) | set(ra.EXCLUDED_BATTERIES)
    huerfanas = [f for f in en_disco if f not in registradas]
    check("0 huérfanas: todo test_*.py ∈ BATERIAS ∪ EXCLUDED_BATTERIES",
          not huerfanas, repr(huerfanas))
    check("EXCLUDED_BATTERIES: todas con motivo escrito",
          all((m or "").strip() for m in ra.EXCLUDED_BATTERIES.values()),
          repr([k for k, m in ra.EXCLUDED_BATTERIES.items() if not (m or "").strip()][:5]))
    check("BATERIAS sin duplicados",
          len(ra.BATERIAS) == len(set(ra.BATERIAS)),
          f"n={len(ra.BATERIAS)} unicos={len(set(ra.BATERIAS))}")
    inter = set(ra.BATERIAS) & set(ra.EXCLUDED_BATTERIES)
    check("BATERIAS ∩ EXCLUDED = ∅", not inter, repr(sorted(inter)))
    faltan_b = [b for b in ra.BATERIAS if not (TESTS_DIR / b).is_file()]
    check("todas las BATERIAS existen en disco", not faltan_b, repr(faltan_b))
    faltan_e = [b for b in ra.EXCLUDED_BATTERIES if not (TESTS_DIR / b).is_file()]
    check("todas las EXCLUDED existen en disco", not faltan_e, repr(faltan_e))
    check("PYTEST_IGNORADAS ⊆ EXCLUDED ∪ BATERIAS",
          all(p in ra.EXCLUDED_BATTERIES or p in ra.BATERIAS
              for p in ra.PYTEST_IGNORADAS),
          repr([p for p in ra.PYTEST_IGNORADAS
                if p not in ra.EXCLUDED_BATTERIES and p not in ra.BATERIAS]))
    check("conftest.consume el registro único (D6)",
          "PYTEST_IGNORADAS" in (TESTS_DIR / "conftest.py").read_text(encoding="utf-8"))


def _guardian_timeout():
    print("── B. D4: timeout por batería mata el árbol y reporta ──")
    r = subprocess.run(
        [sys.executable, str(TESTS_DIR / "run_all.py"),
         "--timeout-seg", "5", "-b", str(TESTS_DIR / "test_d4_timeout_sleep.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        timeout=120)
    salida = (r.stdout or "") + (r.stderr or "")
    check("la suite TERMINA pese a la batería que duerme 400 s", True)
    check("run_all sale EN ROJO con la batería cortada", r.returncode != 0,
          f"exit={r.returncode}")
    check("el reporte dice TIMEOUT con el nombre de la batería",
          "TIMEOUT" in salida and "test_d4_timeout_sleep.py" in salida,
          salida[-200:])
    check("el reporte NO la cuenta como verde",
          "Baterías en rojo" in salida, salida[-200:])
    if os.name == "posix":
        vivo = subprocess.run(["pgrep", "-f", "test_d4_timeout_sleep"],
                              capture_output=True, text=True)
        check("sin procesos hijos vivos tras el timeout", vivo.returncode != 0,
              vivo.stdout[:120])


def _guardian_hermetica():
    print("── C. D7: guardia de red (--hermetica) bloquea externo, loopback ok ──")
    script = r'''
import socket, sys, threading, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
fallos = []
# [D7 diseño final]: getaddrinfo pasa (security.validar_url necesita
# resolver para INSPECCIONAR IPs); lo que se quema es connect() externo.
try:
    s = socket.create_connection(("example.com", 80), timeout=5)
    s.close()
    fallos.append("connect externo NO bloqueado")
except OSError as e:
    if "herm" not in str(e).lower():
        fallos.append("error externo inesperado: " + str(e))
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H)
th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
try:
    r = urllib.request.urlopen("http://127.0.0.1:%d/" % srv.server_port, timeout=5)
    if r.status != 200: fallos.append("loopback: HTTP %s" % r.status)
except Exception as e:
    fallos.append("loopback roto bajo guardia: " + repr(e))
srv.shutdown()
if fallos:
    print("FALLOS:", fallos); sys.exit(1)
print("D7 OK: externo bloqueado + loopback permitido")
'''
    env = os.environ.copy()
    previa = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(TESTS_DIR / "hermetic_guard") \
        + (os.pathsep + previa if previa else "")
    r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=60, stdin=subprocess.DEVNULL)
    check("sitecustomize bloquea la red externa y permite loopback",
          r.returncode == 0 and "D7 OK" in (r.stdout or ""),
          ((r.stderr or "") + (r.stdout or ""))[-220:])




def _minidramas():
    """[PASO 0.2] baterías de minidrama: registradas, herméticas y con
    resumen parseable cuando corren como script standalone."""
    print("── D. PASO 0.2: baterías de minidrama registradas y parseables ──")
    for nombre in ("test_minidrama_clip_validator.py", "test_observador_piloto.py"):
        check(f"{nombre} ∈ BATERIAS y existe en disco",
              nombre in ra.BATERIAS and (TESTS_DIR / nombre).is_file())
        check(f"{nombre} no es NON_HERMETIC (hermética)",
              nombre not in ra.NON_HERMETIC_BATTERIES)
        r = subprocess.run(
            [sys.executable, str(TESTS_DIR / nombre)], cwd=str(REPO_ROOT),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300, stdin=subprocess.DEVNULL)
        m = re.findall(r"(\d+)\s+OK\s*·\s*(\d+)\s+fallos", r.stdout or "")
        ok, fallos = (int(n) for n in m[-1]) if m else (0, -1)
        check(f"{nombre} standalone: {ok} OK · {fallos} fallos (resumen parseable)",
              r.returncode == 0 and fallos == 0 and ok > 0,
              ((r.stderr or "") + (r.stdout or ""))[-160:])

def main() -> int:
    _guardian_registro()
    _guardian_timeout()
    _guardian_hermetica()
    _minidramas()
    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_registro_baterias():
    """Entrada pytest: el guardián completo como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
