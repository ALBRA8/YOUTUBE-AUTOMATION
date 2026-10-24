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


REQUIRED = ("fastapi uvicorn dotenv multipart httpx google.genai PIL "
            "apscheduler edge_tts yt_dlp googleapiclient google_auth_oauthlib "
            "faster_whisper av").split()


def deps_ok(timeout=120):
    """True si el .venv tiene los 14 modulos de arranque (find_spec: instantaneo).
    Si el entorno esta roto (p.ej. ModuleNotFoundError de dotenv), devuelve False
    y launch() delega en start.bat, que auto-repara con barras de progreso."""
    exe = os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
    if not os.path.exists(exe):
        return False
    code = ("import importlib.util as u,sys;mods=" + repr(REQUIRED) +
            ";sys.exit(0) if all(u.find_spec(m) for m in mods) else sys.exit(1)")
    try:
        r = subprocess.run([exe, "-c", code], cwd=BACKEND, timeout=timeout,
                           capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def disable_quickedit():
    """QuickEdit OFF (0x40) + ENABLE_EXTENDED_FLAGS (0x80) en la consola:
    un click en la ventana pausa stdout y congela pip/uvicorn (aparece
    'Seleccionar' en el titulo). No-op si no hay consola (ruta oculta)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)          # STD_INPUT_HANDLE
        m = ctypes.c_uint(0)
        if k.GetConsoleMode(h, ctypes.byref(m)):
            k.SetConsoleMode(h, (m.value & ~0x40) | 0x80)
    except Exception:
        pass


def launch():
    disable_quickedit()

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

    # 2b. Entorno virtual roto/incompleto -> asistente visible auto-reparador
    #     (start.bat verifica 14 modulos, reinstala con barras y deja el server)
    if not deps_ok():
        subprocess.Popen(
            ["cmd", "/c", os.path.join(BASE, "start.bat")],
            creationflags=0x00000010,  # CREATE_NEW_CONSOLE: ventana visible
        )
        return 0

    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))

    try:
        # 3. Arrancar servidor oculto con log
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        # Fallback SIEMPRE al python del venv (nunca al del sistema: no tiene
        # dotenv/fastapi y reproduciria ModuleNotFoundError en main.py)
        exe = PYW if os.path.exists(PYW) else os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
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
