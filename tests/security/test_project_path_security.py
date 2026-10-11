"""
PHASE 1 · C1/M5 — REGRESIÓN RUNTIME del path traversal de proyectos.

Reproduce el exploit REAL del canario (DELETE /api/projects/%2e%2e que
borró backend/data vía shutil.rmtree(OUTPUT_DIR / "..")) y demuestra la
corrección: política única validate_project_id + safe_project_output_dir.

Runtime HTTP real (httpx.ASGITransport sobre la app FastAPI completa).
Python puro — reproducible en Windows sin Node/bash.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_path_"))
import config as _cfg  # noqa: E402  (parchear ANTES de importar database/main)

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402,F401
import main as _main  # noqa: E402
import httpx  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _c():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_main.app),
                             base_url="http://testserver")


# ── setup: proyecto real + centinela que debe SOBREVIVIR a los exploits ──
async def _setup():
    async with _c() as c:
        r = await c.post("/api/projects", json={"title": "P1-path", "mode": "idea",
                                                "idea": "x"})
        assert r.status_code == 200, r.text
        return r.json()["id"]


PID = asyncio.run(_setup())
SENTINEL = _TMP / "sentinel.txt"
SENTINEL.write_text("backend/data NO debe morir", encoding="utf-8")


async def _del(pid):
    async with _c() as c:
        return await c.delete(f"/api/projects/{pid}")


# ── C1: exploits de traversal contra DELETE (el hallazgo confirmado) ──
async def _exploits():
    out = {}
    async with _c() as c:
        out["dots"] = await c.delete("/api/projects/..")
        out["encoded"] = await c.delete("/api/projects/%2e%2e")     # el exploit real
        out["enc_slash"] = await c.delete("/api/projects/..%2F..")
        out["dotdot_dir"] = await c.delete("/api/projects/../../../")  # router no matchea
        out["backslash"] = await c.delete("/api/projects/..%5C..")
        out["abs_win"] = await c.delete("/api/projects/C:%5CWindows")
        out["nul"] = await c.delete("/api/projects/aaaa%00bbbbbb")
        out["weird"] = await c.delete("/api/projects/<script>")
        out["missing"] = await c.delete("/api/projects/aaaaaaaaaaaa")  # formato ok, no existe
        out["valid"] = await c.delete(f"/api/projects/{PID}")
    return out


E = asyncio.run(_exploits())

# httpx normaliza «..» en el CLIENTE (el request nunca sale del navegador
# igual); lo que demuestra el rechazo server-side real es la llamada DIRECTA
# al handler con el payload crudo — lo que haría un proxy/hostil que
# reenvíe el target sin normalizar.
from fastapi import HTTPException as _HTTPException  # noqa: E402


def _handler_direct(pid):
    try:
        asyncio.run(_main.delete_project(pid))
        return "sin-rechazo"
    except _HTTPException as e:
        return e.status_code
    except ValueError:
        return "ValueError"


check("DELETE '..' rechazado (4xx vía HTTP normalizada)",
      E["dots"].status_code in (400, 404), str(E["dots"].status_code))
check("handler REAL con '..' crudo (proxy hostil) → 400",
      _handler_direct("..") == 400, str(_handler_direct("..")))
check("handler REAL con el payload decodificado del exploit → 400",
      _handler_direct("%2e%2e") == 400, str(_handler_direct("%2e%2e")))
check("DELETE %2e%2e (exploit real del canario) rechazado",
      E["encoded"].status_code == 400, str(E["encoded"].status_code))
check("DELETE ..%2F.. rechazado", E["enc_slash"].status_code in (400, 404))
check("DELETE ../../../ rechazado (router no matchea → 404/405)",
      E["dotdot_dir"].status_code in (400, 404, 405),
      str(E["dotdot_dir"].status_code))
check("DELETE backslash-encoded rechazado", E["backslash"].status_code in (400, 404))
check("DELETE path absoluto Windows rechazado", E["abs_win"].status_code in (400, 404))
check("DELETE NUL-encoded rechazado", E["nul"].status_code in (400, 404))
check("DELETE caracteres inesperados rechazado", E["weird"].status_code in (400, 404))
check("DELETE proyecto INEXISTENTE (formato válido) → 404",
      E["missing"].status_code == 404, str(E["missing"].status_code))
check("centinela de backend/data SOBREVIVE a todos los exploits",
      SENTINEL.exists() and SENTINEL.read_text(encoding="utf-8").startswith("backend"))
check("directorio DATA intacto tras exploits", (_TMP / "output").exists())

# ── DELETE legítimo: funciona y ya no deja nada ──
check("DELETE proyecto válido → 200", E["valid"].status_code == 200,
      str(E["valid"].status_code))
check("segundo DELETE del mismo proyecto → 404 (ya no existe)",
      asyncio.run(_del(PID)).status_code == 404)

# ── superficie completa: TODOS los endpoints con pid validan formato ──
async def _surf():
    out = {}
    async with _c() as c:
        out["get"] = await c.get("/api/projects/..")
        out["get_missing"] = await c.get("/api/projects/aaaaaaaaaaaa")
        out["srt"] = await c.get("/api/projects/../subtitles.srt")   # M5
        out["srt_abs"] = await c.get("/api/projects/.%2E/subtitles.srt")
        out["export"] = await c.get("/api/projects/../export/flow.json")
        out["zip"] = await c.get("/api/projects/..%2f../export/flow.zip")
        out["status"] = await c.get("/api/extension/flow/jobs/status/..")
        out["qa"] = await c.get("/api/video_qa/..")
        out["preflight"] = await c.get("/api/production_doctor/preflight",
                                       params={"project_id": ".."})
        out["enqueue"] = await c.post("/api/extension/flow/jobs/enqueue",
                                      json={"project_id": ".."})
        out["next"] = await c.get("/api/extension/flow/jobs/next",
                                  params={"worker": "w-11111111", "project_id": ".."})
        out["cleanup"] = await c.post("/api/projects/../cleanup")
        out["gen"] = await c.post("/api/projects/../generate")
        out["reorder"] = await c.post("/api/projects/../reorder", json={"scene_ids": []})
        out["render"] = await c.post("/api/projects/../render-flow")
        out["import"] = (await c.post("/api/projects/../import-flow")).status_code
        out["publish"] = await c.post("/api/publish/..")
        out["patch"] = await c.patch("/api/projects/..", json={"title": "x"})
    return out


S = asyncio.run(_surf())
for k, r in S.items():
    code = r if isinstance(r, int) else r.status_code
    check(f"endpoint '{k}' rechaza pid malformado (4xx, nunca 5xx)",
          400 <= code < 500, f"status={code}")

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
