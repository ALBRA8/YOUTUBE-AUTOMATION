# -*- coding: utf-8 -*-
"""
Waiter del lanzador dev (start.bat / start.sh) — ALBRA.
Espera a que /api/health responda y abre el dashboard en el navegador.

Se ejecuta en un proceso APARTE (ventana minimizada en Windows), por lo que
nunca bloquea el arranque de uvicorn en primer plano: el «npm run dev»
mantiene los logs vivos y este helper solo se encarga del navegador.

Uso:
    python _dev_wait_open.py [URL]        (default: http://127.0.0.1:8000)

Variables de entorno:
    ALBRA_WAIT_TIMEOUT   segundos maximos de espera (default 120)
    ALBRA_NO_OPEN=1      solo espera/verifica, NO abre navegador (testeable)

Salida:
    0  servidor sano (navegador abierto, o modo NO_OPEN)
    1  el servidor no respondio dentro del timeout
"""
import os
import sys
import time
import urllib.request
import webbrowser

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("ALBRA_WAIT_TIMEOUT", "120"))
HEALTH = URL + "/api/health"


def healthy(timeout=2.0):
    try:
        return urllib.request.urlopen(HEALTH, timeout=timeout).getcode() == 200
    except Exception:
        return False


def main():
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if healthy():
            if os.getenv("ALBRA_NO_OPEN") == "1":
                print("[waiter] servidor listo:", URL)
            else:
                try:
                    webbrowser.open(URL)
                except Exception:
                    print("[waiter] no se pudo abrir el navegador;", URL)
            return 0
        time.sleep(2)
    print("[waiter] el servidor no respondio en %.0fs: %s" % (TIMEOUT, HEALTH))
    return 1


if __name__ == "__main__":
    sys.exit(main())
