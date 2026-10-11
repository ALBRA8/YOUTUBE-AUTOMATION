"""
PHASE 1 · A2/M6 — REGRESIÓN RUNTIME de la seguridad de configuración.

.env NO acepta inyección de saltos de línea (rechazo EXPLÍCITO, sin
sanitizar silenciosamente); los campos system-owned del meta NO se
falsifican vía API; los campos legítimos siguen editables. Runtime HTTP
real. Windows-safe.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_cfg_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
_cfg.ENV_PATH = _TMP / ".env"   # el test JAMÁS toca el backend/.env real
_cfg.ENV_PATH.write_text("# env de prueba\nFPS=30\n", encoding="utf-8")
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
import main as _main  # noqa: E402
import security as _sec  # noqa: E402
import httpx  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _env_text() -> str:
    return _cfg.ENV_PATH.read_text(encoding="utf-8")


# ── A2 · validación central ──
for nombre, val in [("\\n simple", "x\nEVIL=1"),
                    ("\\r retorno", "a\rb"),
                    ("\\r\\n CRLF", "x\r\nMASTER_API_KEY=pwn"),
                    ("NUL", "x\x00y")]:
    try:
        _sec.validate_env_value("NVIDIA_MODEL", val)
        check(f"validate_env_value rechaza {nombre}", False)
    except ValueError:
        check(f"validate_env_value rechaza {nombre}", True)

try:
    _cfg.save_env({"NVIDIA_MODEL": "kimi\nMASTER_API_KEY=pwn\nHOST=0.0.0.0"})
    check("save_env con inyección → ValueError (A2)", False)
except ValueError:
    check("save_env con inyección → ValueError (A2)", True)

env_txt = _env_text()
check(".env NO contiene la variable inyectada", "MASTER_API_KEY=pwn" not in env_txt)
check(".env NO creó entradas nuevas tras el intento", env_txt.count("\n") == 2,
      repr(env_txt[:120]))

# ── A2 vía HTTP: el endpoint responde 400 y no escribe ──
async def _http():
    out = {}
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        out["inyect"] = await c.post(
            "/api/config", json={"NVIDIA_MODEL": "kimi\nNVIDIA_BASE_URL=http://evil/x"})
        out["ok"] = await c.post("/api/config", json={"FPS": "24"})
        PA = db.create_project(title="CFG", mode="idea", meta={})["id"]
        out["meta_qa"] = await c.patch(f"/api/projects/{PA}",
                                       json={"meta_patch": {"qa_final": {"worst": "ok"}}})
        out["meta_binding"] = await c.patch(
            f"/api/projects/{PA}", json={"meta_patch": {"binding": {"x": 1}}})
        out["meta_ok"] = await c.patch(
            f"/api/projects/{PA}", json={"meta_patch": {"via": "dashboard"}})
        meta = (await c.get(f"/api/projects/{PA}")).json().get("meta") or {}
    return out, meta


T, META = asyncio.run(_http())

check("POST /api/config con \\n en valor → 400 (nunca 200 ni 500)",
      T["inyect"].status_code == 400, str(T["inyect"].status_code))
check("el .env siguió intacto tras el intento HTTP",
      "NVIDIA_BASE_URL" not in _env_text())
check("POST /api/config legítimo → 200 (configuración editable intacta)",
      T["ok"].status_code == 200, str(T["ok"].status_code))
check("FPS guardado y aplicado (valor legítimo sin \\n pasa)",
      _cfg.FPS == 24)

# ── M6 · system-owned state NO falsificable ──
check("meta_patch qa_final → 403", T["meta_qa"].status_code == 403,
      str(T["meta_qa"].status_code))
check("meta_patch binding → 403", T["meta_binding"].status_code == 403)
check("meta_patch legítimo (via) → 200", T["meta_ok"].status_code == 200)
check("qa_final/binding NO presentes en meta",
      "qa_final" not in META and "binding" not in META)
check("campo legítimo SÍ persistido", META.get("via") == "dashboard")

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
