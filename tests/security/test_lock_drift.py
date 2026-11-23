#!/usr/bin/env python3
"""F1 · Guardia «declarado == instalado»: el LOCKFILE vs el venv REAL.

Incidente que esta batería impide repetir (P4.2/F1): opencv-python-headless
estaba DECLARADO en requirements.txt y en requirements-lock.txt, pero NO
instalado en el venv — `pip list` no se consultaba nunca y los 4 endpoints
de e-commerce (/api/product/badge, /api/product/callout-layer,
/api/product/studio-preview, /api/avatars/{id}/circle-pip) fallaban en
producción con ImportError ruidoso (ecommerce_overlays.py:115).

Qué hace: parsea backend/requirements-lock.txt (name==version) y compara
CONTRA los distribuciones realmente visibles por el intérprete EN EJECUCIÓN
(importlib.metadata.distributions()). Falta → fallo NOMBRANDO el paquete;
versión distinta → fallo nombrando pin vs instalada. El sentido comprobado
es declarado ⊆ instalado: paquetes extra del venv (dev: pytest, ruff, ...)
son legítimos y no se penalizan.

Sin backend, sin DB, sin red: solo stdlib + metadata del intérprete.
Ejecutar: python3 tests/security/test_lock_drift.py
(está en BATERIAS + PYTEST_IGNORADAS de run_all: batería standalone aislada)
"""
import re
import sys
from importlib import metadata as importlib_metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "backend" / "requirements-lock.txt"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _canon(name: str) -> str:
    """PEP 503: normaliza nombre de distribución (opencv_python-headless →
    opencv-python-headless) para comparar lock vs pip sin falsos negativos."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries() -> list[tuple[str, str]]:
    """(nombre, pin) de cada línea `name==version` del lockfile, en orden."""
    entries: list[tuple[str, str]] = []
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)", line)
        if m:
            entries.append((m.group(1), m.group(2)))
    return entries


# ── 1 · El lockfile existe y es parseable ────────────────────────────────
print("── F1: lockfile declarado == instalado en el venv en ejecución")
check("requirements-lock.txt existe", LOCK.is_file(), str(LOCK))
entries = _lock_entries() if LOCK.is_file() else []
check("lockfile parseable con >=20 pins exactos", len(entries) >= 20,
      f"pins encontrados={len(entries)}")

# ── 2 · Mapa del venv REAL (intérprete en ejecución) ─────────────────────
instaladas: dict[str, str] = {}
for dist in importlib_metadata.distributions():
    nombre, version = dist.metadata.get("Name"), dist.version
    if nombre:
        instaladas[_canon(nombre)] = version

# ── 3 · Cada pin del lock debe estar instalado con la MISMA versión ──────
for nombre, pin in entries:
    canon = _canon(nombre)
    if canon not in instaladas:
        check(f"{nombre}=={pin} instalado",
              False, "FALTA en el venv (incidente P4.2/F1: declarado pero "
                     "no instalado) — pip install -r backend/requirements-lock.txt")
        continue
    real = instaladas[canon]
    check(f"{nombre}=={pin} instalado", real == pin,
          f"DRIFT de versión: lock pide {pin}, el venv tiene {real}")

# ── 4 · El paquete del incidente importa y expone su versión upstream ────
try:
    import cv2  # noqa: F401 — es exactamente el import que rompía los endpoints
    cv2_ok = True
except Exception as e:  # ImportError y cualquier carga rota
    cv2_ok = False
    cv2_extra = repr(e)[:120]
check("import cv2 funciona (consumidor ecommerce_overlays.py/face_tracker.py)",
      cv2_ok, cv2_extra if not cv2_ok else "")
if cv2_ok:
    check("importlib.metadata: opencv-python-headless==4.13.0.90",
          instaladas.get("opencv-python-headless") == "4.13.0.90",
          f"instalada={instaladas.get('opencv-python-headless')} "
          f"(cv2.__version__ upstream={cv2.__version__})")

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
sys.exit(1 if FAIL else 0)
