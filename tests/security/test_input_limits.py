"""
PHASE 1 · A7/A9/M10/M4/M11 — REGRESIÓN RUNTIME de límites de entrada y
robustez ante inputs malformados.

ZIP bombs rechazadas (nº entradas / descomprimido / comprimido), techo de
unidades de production JSON, JSON anidado → 4xx (nunca 500), imágenes con
demasiados píxeles → rechazo, rotación del ledger. Runtime HTTP real.
Windows-safe.
"""
import asyncio
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_lim_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
_cfg.ENV_PATH = _TMP / ".env"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
import main as _main  # noqa: E402
import httpx  # noqa: E402
from services import production_json as prod_svc  # noqa: E402
from services import flow_adaptation as fa  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


_PID = db.create_project(title="LIM", mode="idea", meta={})["id"]
SID = db.new_id()
db.replace_scenes(_PID, [{"id": SID, "idx": 0, "title": "s1", "narration": "n",
                          "image_prompt": "p", "status": "pending", "meta": {}}])


def _zip_bytes(n_files: int, payload: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(n_files):
            z.writestr(f"Escena_{i + 1:02d}/imagen_{i + 1}.png", payload)
    return buf.getvalue()


async def _post_zip(data: bytes):
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        return await c.post(f"/api/projects/{_PID}/import-flow",
                            files={"file": ("f.zip", data, "application/zip")})


async def main_async():
    out = {}
    # ── M4: cuerpos malformados → 4xx, NUNCA 500 ──
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        out["regen_empty"] = await c.post(f"/api/scenes/{SID}/regenerate-image", json={})
        out["regen_null"] = await c.post(f"/api/scenes/{SID}/regenerate-image", json=None)
        out["regen_wrong"] = await c.post(f"/api/scenes/{SID}/regenerate-image",
                                          json={"project_id": 12345})
        out["render_missing"] = await c.post("/api/projects/aaaaaaaaaaaa/render-flow")
        out["exchange_empty"] = await c.post("/api/publish/exchange", json={})
        out["patch_scene_empty"] = await c.patch(f"/api/scenes/{SID}", json={})
    # ── A7: zip con demasiadas entradas ──
    old = _cfg.LIMITS["MAX_ZIP_FILES"]
    _cfg.LIMITS["MAX_ZIP_FILES"] = 5
    try:
        out["zip_files"] = await _post_zip(_zip_bytes(8))
    finally:
        _cfg.LIMITS["MAX_ZIP_FILES"] = old
    # ── A7: zip bomb lógica (poco comprimido → enorme descomprimido) ──
    old_u = _cfg.LIMITS["MAX_ZIP_UNCOMPRESSED_BYTES"]
    _cfg.LIMITS["MAX_ZIP_UNCOMPRESSED_BYTES"] = 1024 * 1024  # 1 MB
    try:
        out["zip_bomb"] = await _post_zip(_zip_bytes(3, b"\x00" * (2 * 1024 * 1024)))
    finally:
        _cfg.LIMITS["MAX_ZIP_UNCOMPRESSED_BYTES"] = old_u
    # ── A7: comprimido sobre el tope del endpoint (streaming 413) —
    # bytes ALEATORIOS: el deflate de ceros desinfla por debajo del tope ──
    import os as _os
    old_c = _cfg.LIMITS["MAX_ZIP_COMPRESSED_BYTES"]
    _cfg.LIMITS["MAX_ZIP_COMPRESSED_BYTES"] = 1024
    try:
        out["zip_comp"] = await _post_zip(_zip_bytes(3, _os.urandom(4096)))
    finally:
        _cfg.LIMITS["MAX_ZIP_COMPRESSED_BYTES"] = old_c
    # ── A9: production JSON con demasiadas unidades (validador directo) ──
    units = [{"titulo": f"u{i}", "tipo": "listado", "image_prompt": "p",
              "narracion": "n"} for i in range(45)]
    envelope = {"project": {"titulo": "LIM", "formato": "short"},
                "sequence": units}
    try:
        prod_svc.validate(envelope, {"auto"})
        out["units"] = "sin-error"
    except ValueError as e:
        out["units"] = str(e)
    # ── A9: JSON anidado profundo vía HTTP → 400 (antes RecursionError 500) ──
    bomb = '{"a":' * 60000 + "1" + "}" * 60000
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        out["deep"] = await c.post("/api/production_json/validate",
                                   content=bomb,
                                   headers={"Content-Type": "application/json"})
    return out


T = asyncio.run(main_async())

check("regenerate-image {} → 400 (KeyError M4 erradicado)",
      T["regen_empty"].status_code == 400, str(T["regen_empty"].status_code))
check("regenerate-image null → 4xx (nunca 500)",
      T["regen_null"].status_code in (400, 422), str(T["regen_null"].status_code))
check("regenerate-image tipo incorrecto → 400", T["regen_wrong"].status_code == 400)
check("render-flow proyecto inexistente → 404 (antes ValueError 500)",
      T["render_missing"].status_code == 404, str(T["render_missing"].status_code))
check("publish/exchange {} → 400 (nunca 500)", T["exchange_empty"].status_code == 400)
check("patch escena {} (sin campos) → 4xx controlado",
      400 <= T["patch_scene_empty"].status_code < 500,
      str(T["patch_scene_empty"].status_code))
check("ZIP con demasiadas entradas → 4xx", 400 <= T["zip_files"].status_code < 500,
      str(T["zip_files"].status_code))
check("zip-bomb lógica (1MB comprimido → GB descomprimido) → 4xx",
      400 <= T["zip_bomb"].status_code < 500, str(T["zip_bomb"].status_code))
check("ZIP comprimido sobre el tope → 413 streaming",
      T["zip_comp"].status_code == 413, str(T["zip_comp"].status_code))
check("production JSON 45 unidades > tope → ValueError explícito",
      isinstance(T["units"], str) and "demasiadas unidades" in T["units"],
      str(T["units"])[:80])
check("JSON anidado profundo → 400 (nunca 500)",
      T["deep"].status_code == 400, str(T["deep"].status_code))

# ── M10: bomba de descompresión (PIL) ──
from PIL import Image  # noqa: E402

_old_px = _cfg.LIMITS["MAX_IMAGE_PIXELS"]
_cfg.LIMITS["MAX_IMAGE_PIXELS"] = security_px = 500_000
_main.security.harden_pil(security_px)
try:
    big = Image.new("L", (1200, 1200))  # 1.44M px = 2.9× tope → ERROR (no warning)
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    buf.seek(0)
    try:
        Image.open(buf).verify()
        check("PIL rechaza imagen sobre el techo de píxeles (M10)", False)
    except Exception as e:  # noqa: BLE001 — DecompressionBombError/Warning
        check("PIL rechaza imagen sobre el techo de píxeles (M10)",
              "DecompressionBomb" in type(e).__name__ or "pixels" in str(e).lower(),
              type(e).__name__)
finally:
    _cfg.LIMITS["MAX_IMAGE_PIXELS"] = _old_px
    _main.security.harden_pil(_old_px)

# ── M11: rotación del ledger con retención ──
_led = _TMP / "ledger.jsonl"
_led.write_text("\n".join(json.dumps({"i": i}) for i in range(25)) + "\n",
                encoding="utf-8")
fa.LEDGER_PATH = _led
old_l = _cfg.LIMITS["LEDGER_MAX_LINES"]
_cfg.LIMITS["LEDGER_MAX_LINES"] = 20
try:
    fa._rotate_ledger_if_needed()
    n = len(_led.read_text(encoding="utf-8").strip().splitlines())
    check("ledger rotado al 60% del límite (25→12 líneas, M11)", n == 12, f"n={n}")
    fa._rotate_ledger_if_needed()
    n2 = len(_led.read_text(encoding="utf-8").strip().splitlines())
    check("rotación IDEMPOTENTE (segunda pasada no cambia nada)", n2 == 12, f"n2={n2}")
finally:
    _cfg.LIMITS["LEDGER_MAX_LINES"] = old_l

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
