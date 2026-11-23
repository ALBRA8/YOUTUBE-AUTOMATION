#!/usr/bin/env python3
"""[D4] Batería de aceptación del TIMEOUT por batería: DUERME 400 s.

Nadie la ejecuta de serie: está en EXCLUDED_BATTERIES (con motivo) y se
lanza explícitamente con el timeout rebajado, p. ej.

    python tests/run_all.py --timeout-seg 5 -b tests/test_d4_timeout_sleep.py

Aceptación del cierre: la suite TERMINA (~5 s), reporta la batería como
"TIMEOUT" (fallo con nombre) y NO deja procesos hijos vivos.
"""
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OK, FAIL = 0, 0


def main() -> int:
    print("── D4: durmiendo 400 s (el timeout de la runner debe cortarme) ──")
    time.sleep(400)
    # Inalcanzable bajo --timeout-seg 5; si alguien la corse sin timeout,
    # imprime un resumen honesto de 0 checks (SKIP visible, no verde).
    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0


if __name__ == "__main__":
    sys.exit(main())
