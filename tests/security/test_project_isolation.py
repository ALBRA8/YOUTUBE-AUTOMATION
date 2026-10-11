"""
PHASE 1 · M3/M6 — REGRESIÓN RUNTIME del IDOR entre proyectos + meta protegida.

scene.project_id == requested_project_id SIEMPRE: un recurso hijo de un
proyecto no es accesible ni modificable citando otro proyecto. Y el estado
interno del sistema (qa_final/publish_state/rutas) no se falsifica vía
meta_patch. Runtime HTTP real (httpx.ASGITransport). Windows-safe.
"""
import asyncio
import base64
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_iso_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
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


# ── setup: proyecto A y B, cada uno con una escena ──
PA = db.create_project(title="ISO-A", mode="idea", meta={})
PB = db.create_project(title="ISO-B", mode="idea", meta={})
db.replace_scenes(PA["id"], [{"id": db.new_id(), "idx": 0, "title": "a1",
                              "narration": "n", "image_prompt": "p",
                              "status": "pending", "meta": {}}])
db.replace_scenes(PB["id"], [{"id": db.new_id(), "idx": 0, "title": "b1",
                              "narration": "n", "image_prompt": "p",
                              "status": "pending", "meta": {}}])
SA = db.get_scenes(PA["id"])[0]["id"]
# imagen real en disco para la escena de A (1x1 PNG)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                       "nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")
_img = _cfg.OUTPUT_DIR / PA["id"]
_img.mkdir(parents=True, exist_ok=True)
(_img / "a.png").write_bytes(PNG)
db.update_scene(SA, image_path=str(_img / "a.png"))


async def _tests():
    out = {}
    async with _c() as c:
        out["patch_cross"] = await c.patch(f"/api/scenes/{SA}",
                                           json={"title": "hack", "project_id": PB["id"]})
        out["patch_ok"] = await c.patch(f"/api/scenes/{SA}",
                                        json={"title": "editado", "project_id": PA["id"]})
        out["patch_sin_pid"] = await c.patch(f"/api/scenes/{SA}", json={"title": "x"})
        out["patch_pid_malo"] = await c.patch(f"/api/scenes/{SA}",
                                              json={"title": "x", "project_id": ".."})
        out["img_cross"] = await c.get(f"/api/scenes/{SA}/image",
                                       params={"project_id": PB["id"]})
        out["img_ok"] = await c.get(f"/api/scenes/{SA}/image",
                                    params={"project_id": PA["id"]})
        out["img_sin_pid"] = await c.get(f"/api/scenes/{SA}/image")
        out["audio_cross"] = await c.get(f"/api/scenes/{SA}/audio",
                                         params={"project_id": PB["id"]})
        out["regen_vacio"] = await c.post(f"/api/scenes/{SA}/regenerate-image", json={})
        out["regen_cross"] = await c.post(f"/api/scenes/{SA}/regenerate-image",
                                          json={"project_id": PB["id"]})
        out["extimg_missing"] = await c.post("/api/extension/images",
                                             json={"url": "https://example.com/x.png",
                                                   "project_id": "bbbbbbbbbbbb"})
        out["extimg_ok"] = await c.post("/api/extension/images",
                                        json={"url": "https://example.com/x.png",
                                              "project_id": PA["id"]})
        out["meta_qa"] = await c.patch(f"/api/projects/{PA['id']}",
                                       json={"meta_patch": {"qa_final": {"worst": "ok"}}})
        out["meta_pub"] = await c.patch(f"/api/projects/{PA['id']}",
                                        json={"meta_patch": {"publish_state": "PUBLISHED"}})
        out["meta_audio"] = await c.patch(f"/api/projects/{PA['id']}",
                                          json={"meta_patch": {"audio_path": "/etc/passwd"}})
        out["meta_ok"] = await c.patch(f"/api/projects/{PA['id']}",
                                       json={"meta_patch": {"subtitle_style": "karaoke"}})
        p = await c.get(f"/api/projects/{PA['id']}")
        out["meta_final"] = p.json().get("meta") or {}
        # M9 vía /api/chat: confirmación destructiva fuzzy → NO ejecuta
        out["chat_fuzzy"] = await c.post("/api/chat", json={
            "confirm": {"action": "delete_project",
                        "params": {"project_name": "ISO"}}})
        out["b_viva_tras_fuzzy"] = db.get_project(PB["id"]) is not None  # snapshot AHORA
        out["chat_exacto"] = await c.post("/api/chat", json={
            "confirm": {"action": "delete_project",
                        "params": {"project_name": "ISO-B"}}})
    return out


T = asyncio.run(_tests())

check("PATCH escena A + project B → 404 (IDOR bloqueado)",
      T["patch_cross"].status_code == 404, str(T["patch_cross"].status_code))
check("la escena A NO fue modificada por el intento cross",
      db.get_scene_for_project(PA["id"], SA)["title"] != "hack")
check("PATCH escena A + project A → 200 (uso legítimo intacto)",
      T["patch_ok"].status_code == 200, str(T["patch_ok"].status_code))
check("PATCH sin project_id → 400 (el padre es OBLIGATORIO)",
      T["patch_sin_pid"].status_code == 400, str(T["patch_sin_pid"].status_code))
check("PATCH con project_id malformado → 400",
      T["patch_pid_malo"].status_code == 400)
check("GET imagen escena A + project B → 404",
      T["img_cross"].status_code == 404, str(T["img_cross"].status_code))
check("GET imagen escena A + project A → 200",
      T["img_ok"].status_code == 200, str(T["img_ok"].status_code))
check("GET imagen SIN project_id → 400",
      T["img_sin_pid"].status_code == 400, str(T["img_sin_pid"].status_code))
check("GET audio cross-project → 404",
      T["audio_cross"].status_code == 404, str(T["audio_cross"].status_code))
check("regenerate-image {} → 400 (nunca KeyError→500, M4)",
      T["regen_vacio"].status_code == 400, str(T["regen_vacio"].status_code))
check("regenerate-image cross-project → 404",
      T["regen_cross"].status_code == 404, str(T["regen_cross"].status_code))
check("ext images con project inexistente → 404",
      T["extimg_missing"].status_code == 404, str(T["extimg_missing"].status_code))
check("ext images con project real → 200",
      T["extimg_ok"].status_code == 200, str(T["extimg_ok"].status_code))
# M6 · system-owned metadata
check("meta_patch qa_final (spoof del QA gate) → 403",
      T["meta_qa"].status_code == 403, str(T["meta_qa"].status_code))
check("meta_patch publish_state (spoof de publicación) → 403",
      T["meta_pub"].status_code == 403)
check("meta_patch audio_path (ruta arbitraria) → 403",
      T["meta_audio"].status_code == 403)
check("qa_final NO quedó escrito en meta", "qa_final" not in T["meta_final"])
check("meta_patch legítimo (subtitle_style) → 200", T["meta_ok"].status_code == 200)
check("meta_patch legítimo SÍ se aplica",
      T["meta_final"].get("subtitle_style") == "karaoke")
# M9 · chat destructivo
check("chat confirm fuzzy («ISO» ambiguo) → NO ejecuta borrado",
      T["chat_fuzzy"].status_code == 200
      and "No ejecuto borrados ambiguos" in T["chat_fuzzy"].json().get("reply", ""),
      T["chat_fuzzy"].json().get("reply", "")[:80])
check("ISO-B sobrevive al intento fuzzy (snapshot inmediato)",
      T["b_viva_tras_fuzzy"])
check("chat confirm con título EXACTO único → ejecuta borrado",
      T["chat_exacto"].status_code == 200
      and T["chat_exacto"].json().get("action") == "delete_project",
      T["chat_exacto"].json().get("reply", "")[:80])
check("ISO-B fue eliminado por la confirmación exacta",
      db.get_project(PB["id"]) is None)

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
