#!/usr/bin/env python3
"""Batería FLOW BRIDGE v1 — cola de jobs real backend ↔ extensión Chrome.

Prueba el circuito completo EN HERMÉTICO (DB y OUTPUT en tmp, render mockeado):

    enqueue_project (desde build_script_json — única fuente de prompts)
      → claim_next (atómico: BEGIN IMMEDIATE, job_token, lease por tipo)
      → heartbeat (renueva lease) · complete (PNG con PIL / MP4 con ffprobe)
      → fail (attempts → dead) · recuperación de leases expirados
      → auto-render (start_flow_render dispara al completar el proyecto)
      + los 6 endpoints HTTP reales vía httpx ASGI (patrón test_autopublish).

Uso:  cd yt_automation_v2 && python3 tests/test_flow_bridge.py
      python3 -m pytest tests/test_flow_bridge.py -q
"""
import asyncio
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar la app: DB y OUTPUT a tmp ──────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="flow_bridge_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402  (lee config.DB_PATH ya parcheado)
from services import flow_jobs as fj  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _png_bytes(w=32, h=32, color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _mp4_bytes(dur=1.0) -> bytes:
    out = _TMP / f"clip_{dur}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={dur}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
        check=True, capture_output=True, timeout=60)
    return out.read_bytes()


def _proyecto(pid: str, n: int = 3) -> str:
    db.create_project(id=pid, title="Bridge Test", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, [
        {"title": f"Escena {i}", "narration": f"Narración {i}.",
         "image_prompt": f"wide shot stage {i}, golden hour, grove, no text",
         "duration": 0.0, "status": "pending",
         "meta": {"production_unit": {
             "id": f"u{i}", "index": i - 1, "type": "scene",
             "video_prompt": (f"CE_PROMPT_V{i} :: slow dolly-in, dust "
                              "settling" if i < n else None)}}}
        for i in range(1, n + 1)])
    return pid


# ── auto-render mock (el render real necesita ffmpeg completo + voz) ─────────
_RENDER_CALLS: list[str] = []


async def _fake_start_flow_render(pid: str) -> str:
    _RENDER_CALLS.append(pid)
    return f"job_render_{pid}"


def main() -> int:
    # limpieza defensiva
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM scenes")
        con.execute("DELETE FROM projects")

    print("── 1. enqueue desde build_script_json (fuente única de prompts)")
    pid = _proyecto("proj_bridge_1", n=3)
    try:
        fj.enqueue_project("no_existe")
        check("enqueue proyecto inexistente → LookupError", False)
    except LookupError:
        check("enqueue proyecto inexistente → LookupError", True)
    res = fj.enqueue_project(pid)
    check("3 imágenes + 2 videos", res["images"] == 3 and res["videos"] == 2,
          str(res))
    check("total 5 jobs", res["created"] == 5)

    print("── 2. claim atómico + prioridad imagen→video + job_token")
    j1 = fj.claim_next("w-A")
    check("primer job es imagen escena 1",
          j1 and j1["kind"] == "image" and j1["scene_number"] == 1, str(j1)[:80])
    check("job trae job_token nonce", bool(j1.get("job_token")))
    check("lease_until fijado (imagen 8 min)",
          bool(j1.get("lease_until")))
    check("prompt de imagen aplanado desde build_script_json",
          "wide shot stage 1" in j1["prompt"], repr(j1["prompt"])[:80])
    j2 = fj.claim_next("w-A")
    check("segundo job es imagen escena 2",
          j2 and j2["kind"] == "image" and j2["scene_number"] == 2)
    check("tokens distintos por claim", j1["job_token"] != j2["job_token"])
    j3 = fj.claim_next("w-A")
    check("job claimed NO se re-claima (avanza a imagen 3)",
          j3 and j3["kind"] == "image" and j3["scene_number"] == 3)

    print("── 3. heartbeat renueva lease · token inválido → None")
    hb = fj.heartbeat(j1["id"], j1["job_token"])
    check("heartbeat ok con token correcto", bool(hb and hb["ok"]))
    check("heartbeat NO con token erróneo",
          fj.heartbeat(j1["id"], "token-malo") is None)
    check("heartbeat NO con job inexistente",
          fj.heartbeat("job_falso", j1["job_token"]) is None)

    print("── 4. complete: imagen validada con PIL + convención de archivo")
    res_c = fj.complete(j1["id"], j1["job_token"], _png_bytes())
    check("complete ok", bool(res_c and res_c["ok"]))
    expected = fj.OUTPUT_DIR / pid / "flow" / "Escena_01_flow.png"
    check("guardado en flow/Escena_01_flow.png", Path(res_c["asset_path"]) == expected,
          res_c.get("asset_path", ""))
    check("archivo existe y es PNG válido",
          expected.exists() and expected.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n")
    check("complete con token erróneo → None (409)",
          fj.complete(j1["id"], "token-malo", _png_bytes()) is None)
    j2b = j2  # imagen 2 ya reclamada en la sección 2
    check("complete imagen 2 ok",
          bool(fj.complete(j2b["id"], j2b["job_token"], _png_bytes())))
    j3b = j3  # imagen 3 ya reclamada en la sección 2
    try:
        fj.complete(j3b["id"], j3b["job_token"], b"<html>error de flow</html>")
        check("HTML de error NO pasa como imagen (422)", False)
    except ValueError:
        check("HTML de error NO pasa como imagen (422)", True)
    check("tras el 422 el token SIGUE válido (job aún claimed)",
          fj.heartbeat(j3b["id"], j3b["job_token"]) is not None)
    rf = fj.fail(j3b["id"], j3b["job_token"], "Flow devolvió HTML")
    check("fail tras 422 → queued de nuevo (intento 1)",
          rf["status"] == "queued" and rf["attempts"] == 1, str(rf))

    print("── 5. reintentos de imagen + MP4 validado con ffprobe + prompt P1")
    j3r = fj.claim_next("w-A")
    check("imagen escena 3 re-entregada (reintento)",
          j3r and j3r["id"] == j3b["id"] and j3r["attempts"] == 1)
    check("reintento de imagen 3 completa ok",
          bool(fj.complete(j3r["id"], j3r["job_token"], _png_bytes())))
    jv = fj.claim_next("w-A")
    check("tras las imágenes toca el video 1",
          jv and jv["kind"] == "video" and jv["scene_number"] == 1, str(jv)[:80])
    check("prompt de video == motion del Creative Engine (contrato P1)",
          jv["prompt"].startswith("CE_PROMPT_V1 :: slow dolly-in"),
          repr(jv["prompt"])[:80])
    res_v = fj.complete(jv["id"], jv["job_token"], _mp4_bytes(1.0))
    vpath = fj.OUTPUT_DIR / pid / "flow" / "Escena_01_video_1.mp4"
    check("video guardado como Escena_01_video_1.mp4",
          bool(res_v) and Path(res_v["asset_path"]) == vpath,
          str(res_v)[:100])
    jv2 = fj.claim_next("w-A")
    try:
        fj.complete(jv2["id"], jv2["job_token"], b"no es un mp4")
        check("basura NO pasa como video (422)", False)
    except ValueError:
        check("basura NO pasa como video (422)", True)
    fj.fail(jv2["id"], jv2["job_token"], "no es mp4")

    print("── 6. fail: agota a dead (video máx 2) y la cola queda vacía")
    jv3 = fj.claim_next("w-A")
    check("video escena 2 re-entregado (intento 2)",
          jv3 and jv3["kind"] == "video" and jv3["scene_number"] == 2
          and jv3["attempts"] == 1, str(jv3)[:100])
    r2 = fj.fail(jv3["id"], jv3["job_token"], "Flow se trabó otra vez")
    check("fallo 2 de 2 → dead", r2["status"] == "dead", str(r2))
    check("cola vacía → claim None", fj.claim_next("w-A") is None)

    print("── 7. lease expirado se recupera solo (worker muerto)")
    pid_b = _proyecto("proj_bridge_lb", n=1)
    fj.enqueue_project(pid_b)
    jl = fj.claim_next("w-muerto")
    check("job de proyecto B reclamado", bool(jl))
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00+00:00' "
                    "WHERE id=?", (jl["id"],))
    jr = fj.claim_next("w-nuevo")
    check("lease vencido → job re-entregado a otro worker",
          jr and jr["id"] == jl["id"] and jr["worker"] == "w-nuevo")
    check("recuperación NO gasta intento",
          jr["attempts"] == 0, str(jr["attempts"]))

    print("── 8. re-enqueue idempotente (conserva done, recrea dead)")
    res_re = fj.enqueue_project(pid)
    check("re-enqueue recrea SOLO el video dead de la escena 2",
          res_re["created"] == 1 and res_re["videos"] == 1
          and res_re["images"] == 0, str(res_re))

    print("── 9. complete final del proyecto → mapea escenas (renderable)")
    jlast = fj.claim_next("w-A")
    res_last = fj.complete(jlast["id"], jlast["job_token"], _mp4_bytes(1.0))
    check("project_done True al completar el último",
          res_last.get("project_done") is True, str(res_last)[:120])
    check("renderable True (todas las escenas tienen imagen)",
          res_last.get("renderable") is True, str(res_last)[:120])
    sc2 = db.get_scenes(pid)
    imagen_esc2 = [s for s in sc2 if s["idx"] == 1]
    check("escena 2 con image_path mapeado desde flow/",
          bool(imagen_esc2 and imagen_esc2[0]["image_path"]
               and "Escena_02_flow" in imagen_esc2[0]["image_path"]),
          str(imagen_esc2 and imagen_esc2[0].get("image_path")))

    print("── 10. los 6 endpoints HTTP reales (httpx ASGI)")
    import httpx
    import main as main_mod
    from pipeline import orchestrator
    orchestrator.start_flow_render = _fake_start_flow_render  # auto-render mock
    app = main_mod.app
    pid2 = _proyecto("proj_bridge_2", n=2)

    async def _endpoints() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as c:
            r = await c.get("/api/extension/flow/jobs/next", params={"worker": "w-x"})
            check("next sin cola → 204", r.status_code == 204, str(r.status_code))

            r = await c.post("/api/extension/flow/jobs/enqueue",
                             json={"project_id": pid2})
            check("POST enqueue 200 · 2 imágenes + 1 video",
                  r.status_code == 200 and r.json()["images"] == 2
                  and r.json()["videos"] == 1, r.text[:120])

            r = await c.get("/api/extension/flow/jobs/next",
                            params={"worker": "w-x"})
            check("GET next 200 con job de imagen escena 1",
                  r.status_code == 200
                  and r.json()["job"]["kind"] == "image", r.text[:120])
            job = r.json()["job"]

            r = await c.post(f"/api/extension/flow/jobs/{job['id']}/heartbeat",
                             params={"token": job["job_token"]})
            check("POST heartbeat 200", r.status_code == 200, r.text[:100])

            r = await c.post(f"/api/extension/flow/jobs/{job['id']}/complete",
                             params={"token": job["job_token"]},
                             content=_png_bytes(),
                             headers={"Content-Type": "image/png"})
            check("POST complete 200 (PNG vía HTTP)",
                  r.status_code == 200 and r.json()["ok"] is True, r.text[:120])

            r = await c.get(f"/api/extension/flow/jobs/status/{pid2}")
            check("GET status 200 · counts correctos",
                  r.status_code == 200
                  and r.json()["counts"] == {"queued": 2, "claimed": 0,
                                             "done": 1, "dead": 0},
                  r.text[:200])

            r = await c.post("/api/extension/flow/jobs/enqueue",
                             json={"project_id": "proyecto_fantasma"})
            check("enqueue proyecto inexistente → 404", r.status_code == 404)

            r = await c.get("/api/extension/flow/jobs/next", params={})
            check("next sin worker → 400", r.status_code == 400)

            # flujo completo del proyecto 2 vía HTTP → auto-render mock
            # (main_mod llama orchestrator.start_flow_render — ya mockeado)
            done = False
            for _ in range(3):
                r = await c.get("/api/extension/flow/jobs/next",
                                params={"worker": "w-x"})
                if r.status_code == 204:
                    break
                job = r.json()["job"]
                payload = (_png_bytes() if job["kind"] == "image"
                           else _mp4_bytes(1.0))
                ctype = ("image/png" if job["kind"] == "image"
                         else "video/mp4")
                r = await c.post(
                    f"/api/extension/flow/jobs/{job['id']}/complete",
                    params={"token": job["job_token"]}, content=payload,
                    headers={"Content-Type": ctype})
                if r.status_code == 200 and r.json().get("project_done"):
                    done = True
            check("circuito HTTP completo del proyecto 2 → project_done",
                  done)
            check("auto-render disparado (orchestrator mockeado)",
                  "proj_bridge_2" in _RENDER_CALLS, str(_RENDER_CALLS))

    asyncio.new_event_loop().run_until_complete(_endpoints())

    print("── 11. limpieza")
    shutil.rmtree(_TMP, ignore_errors=True)
    check("tmp eliminado", not _TMP.exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_flow_bridge():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
