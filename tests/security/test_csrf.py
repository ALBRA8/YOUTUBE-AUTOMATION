"""
PHASE 1 · M2 — REGRESIÓN RUNTIME de la política CSRF/origen en mutaciones.

Un Origin externo (https://evil.example) JAMÁS puede lanzar una mutación;
same-origin, clientes locales y la extensión Chrome sí. Requests sin
Origin/Referer (curl/API/workers) se permiten (compatibilidad). Runtime
HTTP real. Windows-safe.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_csrf_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import main as _main  # noqa: E402
import httpx  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


EXT_ID = "a" * 32  # chrome-extension:// con ID válido (32 chars a-p)


async def _post(headers):
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        return await c.post("/api/projects", json={"title": "csrf", "mode": "idea"},
                            headers=headers)


async def main_async():
    r_evil = await _post({"Origin": "https://evil.example"})
    r_evil_ref = await _post({"Referer": "https://evil.example/attack.html"})
    r_null = await _post({"Origin": "null"})
    r_same = await _post({"Origin": "http://testserver"})
    r_local = await _post({"Origin": "http://localhost:3000"})
    r_loop = await _post({"Origin": "http://127.0.0.1:8000"})
    r_ext = await _post({"Origin": f"chrome-extension://{EXT_ID}"})
    r_noorigin = await _post({})
    r_get_evil = None
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        r_get_evil = await c.get("/api/projects", headers={"Origin": "https://evil.example"})
    # 413 por Content-Length > tope global (restaurado en finally)
    old = _cfg.LIMITS["MAX_BODY_BYTES"]
    _cfg.LIMITS["MAX_BODY_BYTES"] = 10
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r_big = await c.post("/api/projects", json={"title": "x" * 50},
                                 headers={"Content-Length": "5000"})
    finally:
        _cfg.LIMITS["MAX_BODY_BYTES"] = old
    return (r_evil, r_evil_ref, r_null, r_same, r_local, r_loop, r_ext,
            r_noorigin, r_get_evil, r_big)


R = asyncio.run(main_async())
(r_evil, r_evil_ref, r_null, r_same, r_local, r_loop, r_ext,
 r_noorigin, r_get_evil, r_big) = R

check("Origin externo (evil.example) + POST → 403 (CSRF bloqueado)",
      r_evil.status_code == 403, str(r_evil.status_code))
check("Referer externo + POST → 403", r_evil_ref.status_code == 403,
      str(r_evil_ref.status_code))
check("Origin «null» (sandbox) + POST → 403", r_null.status_code == 403,
      str(r_null.status_code))
check("Origin same-host (http://testserver) → NO bloqueado por CSRF",
      r_same.status_code != 403, str(r_same.status_code))
check("Origin http://localhost:3000 → permitido (cliente local)",
      r_local.status_code != 403, str(r_local.status_code))
check("Origin http://127.0.0.1:8000 → permitido",
      r_loop.status_code != 403)
check("Origin chrome-extension (ID válido) → permitido (worker de la extensión)",
      r_ext.status_code != 403, str(r_ext.status_code))
check("POST SIN Origin/Referer (curl/API) → permitido (compatibilidad)",
      r_noorigin.status_code != 403, str(r_noorigin.status_code))
check("GET con Origin externo → permitido (solo mutaciones se protegen)",
      r_get_evil.status_code == 200, str(r_get_evil.status_code))
check("Content-Length sobre el tope global → 413 (anti-DoS)",
      r_big.status_code == 413, str(r_big.status_code))

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
