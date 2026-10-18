# -*- coding: utf-8 -*-
"""
LANZADOR SILENCIOSO ALBRA
Corre SIN ventana (invocado por INICIAR-ALBRA.vbs con ventana oculta).
1. Si el servidor ya responde -> solo abre el navegador.
2. Si hay otro lanzador en marcha (lock vivo) -> solo abre el navegador.
3. Si no: arranca el servidor oculto (CREATE_NO_WINDOW, log en .server_log.txt),
   espera a /api/health y abre el navegador cuando responde.
4. Si en 120s no responde: abre el log en el Bloc de notas para ver el error.
"""
import os
import sys
import time
import webbrowser
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))          # raiz del proyecto
BACKEND = os.path.join(BASE, "backend")
PYW = os.path.join(BACKEND, ".venv", "Scripts", "pythonw.exe")
LOG = os.path.join(BASE, ".server_log.txt")
LOCK = os.path.join(BASE, ".server.lock")
CREATE_NO_WINDOW = 0x08000000


def host_port():
    host, port = "127.0.0.1", 8000
    try:
        with open(os.path.join(BACKEND, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("HOST="):
                    host = line.split("=", 1)[1].strip().strip('"') or host
                elif line.startswith("PORT="):
                    port = int(line.split("=", 1)[1].strip() or 8000)
    except Exception:
        pass
    return host, port


HOST, PORT = host_port()
URL = "http://%s:%s" % (HOST, PORT)


def healthy(timeout=2.0):
    try:
        import urllib.request
        return urllib.request.urlopen(URL + "/api/health", timeout=timeout).getcode() == 200
    except Exception:
        return False


def launch():
    # 1. Ya corriendo -> abrir y salir
    if healthy():
        webbrowser.open(URL)
        return 0

    # 2. Otro lanzador en marcha -> abrir y salir
    if os.path.exists(LOCK):
        try:
            pid = int(open(LOCK).read().strip())
            os.kill(pid, 0)  # vivo?
            webbrowser.open(URL)
            return 0
        except Exception:
            try:
                os.remove(LOCK)
            except Exception:
                pass

    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))

    try:
        # 3. Arrancar servidor oculto con log
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        exe = PYW if os.path.exists(PYW) else sys.executable
        subprocess.Popen(
            [exe, "main.py"],
            cwd=BACKEND,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )

        # 4. Esperar health check (max 120s)
        deadline = time.time() + 120
        while time.time() < deadline:
            if healthy():
                webbrowser.open(URL)
                return 0
            time.sleep(2)

        # 5. No respondio -> mostrar el log sin terminal
        subprocess.Popen(["notepad.exe", LOG])
        return 1
    finally:
        try:
            os.remove(LOCK)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(launch())
