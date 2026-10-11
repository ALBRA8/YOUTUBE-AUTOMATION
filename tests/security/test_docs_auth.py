"""
PHASE 1 · M1 — REGRESIÓN RUNTIME: /docs, /redoc y /openapi.json exigen auth.

Con MASTER_API_KEY activada, la documentación y el schema abierto quedan
dentro del mismo guard que /api/* (sin auth → 401; con auth → 200). Sin
clave configurada (modo local) siguen abiertas: cero ruptura. Runtime
HTTP real. Windows-safe.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_docs_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import main as _main  # noqa: E402
import security as _security  # noqa: E402
import httpx  # noqa: E402

OK, FAIL = 0, 0
KEY = "clave-p1-docs-123"


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


async def _get(path, headers=None):
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        return await c.get(path, headers=headers or {})


_results = {}

# ── modo local (sin MASTER_API_KEY): /docs abierto, cero ruptura ──
_security.reload()  # lee el entorno real: sin clave en este proceso de test
_results["local_docs"] = asyncio.run(_get("/docs"))
_results["local_openapi"] = asyncio.run(_get("/openapi.json"))

# ── modo protegido: clave activada (patrón del repo: inyección directa) ──
_security._key = KEY
try:
    _results["docs_noauth"] = asyncio.run(_get("/docs"))
    _results["redoc_noauth"] = asyncio.run(_get("/redoc"))
    _results["openapi_noauth"] = asyncio.run(_get("/openapi.json"))
    _results["docs_oauth_noauth"] = asyncio.run(_get("/docs/oauth2-redirect"))
    _results["docs_auth"] = asyncio.run(_get("/docs", {"X-API-Key": KEY}))
    _results["openapi_auth"] = asyncio.run(_get("/openapi.json", {"X-API-Key": KEY}))
    _results["redoc_auth"] = asyncio.run(_get("/redoc", {"Authorization": f"Bearer {KEY}"}))
    _results["api_noauth"] = asyncio.run(_get("/api/projects"))
    _results["api_auth"] = asyncio.run(_get("/api/projects", {"X-API-Key": KEY}))
    _results["health_public"] = asyncio.run(_get("/api/health"))
finally:
    _security.reload()  # restaura el estado real (sin clave)

R = _results
check("modo local: /docs sigue abierto (cero ruptura)",
      R["local_docs"].status_code == 200, str(R["local_docs"].status_code))
check("modo local: /openapi.json sigue abierto",
      R["local_openapi"].status_code == 200)
check("protegido: /docs SIN auth → 401",
      R["docs_noauth"].status_code == 401, str(R["docs_noauth"].status_code))
check("protegido: /redoc SIN auth → 401", R["redoc_noauth"].status_code == 401)
check("protegido: /openapi.json SIN auth → 401",
      R["openapi_noauth"].status_code == 401, str(R["openapi_noauth"].status_code))
check("protegido: /docs/oauth2-redirect SIN auth → 401",
      R["docs_oauth_noauth"].status_code == 401)
check("protegido: /docs con X-API-Key → 200",
      R["docs_auth"].status_code == 200, str(R["docs_auth"].status_code))
check("protegido: /openapi.json con X-API-Key → 200 (schema no eliminado)",
      R["openapi_auth"].status_code == 200
      and b"openapi" in R["openapi_auth"].content[:200])
check("protegido: /redoc con Bearer → 200", R["redoc_auth"].status_code == 200)
check("protegido: /api/projects SIN auth → 401 (guard intacto)",
      R["api_noauth"].status_code == 401)
check("protegido: /api/projects con auth → 200",
      R["api_auth"].status_code == 200)
check("/api/health sigue PÚBLICA (monitorización)",
      R["health_public"].status_code == 200)

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
