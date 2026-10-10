#!/usr/bin/env python3
"""Batería 10 ESCENAS — el contrato Flow Bridge a escala (misión: TEST 4).

Las baterías existentes cubren n=1 (chaos), n=2 (boot vivo) y n=3 (bridge,
concurrencia). Esta batería estresa la cola con un proyecto de 10 escenas
reales (19 jobs: 10 imágenes + 9 videos — la última escena es solo-imagen
por el contrato P1) y verifica que NADA se degrada al escalar:

    §2  enqueue → 19 jobs (10 imagen + 9 video, última solo-imagen)
    §3  contrato P1 a escala: sentinels CE10_I{n}/CE10_V{n} verbatim en el
        prompt de CADA job + prompt larguísimo (~3 KB) intacto en escena 7
    §4  orden de claims: TODAS las imágenes (escena asc) antes que videos
        + tokens únicos + cola drenada al final
    §5  ciclo completo: 10 completes de imagen en convención canónica,
        heartbeat en vuelo, fail/retry (attempts), doble complete → None,
        asset intacto, recuperación zombie de lease expirado
    §6  estado final: 19 done / 0 en vuelo, 10/10 escenas mapeadas,
        auto-render disparado UNA vez
    §7  video QA a escala (con forense): status ok, 10 escenas, 0 errores,
        cero flags de pantalla negra/azul/silencio en los 9 clips
    §8  re-enqueue idempotente tras done: 0 jobs nuevos

Uso:  cd yt_automation_v2 && python3 tests/test_10_escenas.py
"""
import asyncio
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar la app: DB y OUTPUT a tmp ──────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="escenas10_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
from services import flow_jobs as fj  # noqa: E402
from services import video_qa as vqa  # noqa: E402
from pipeline import orchestrator  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


# ── assets sanos (cálidos ≥240px, tono audible — la forense no debe alarmar) ─
_PALETTE = [(200, 60, 30), (210, 120, 30), (190, 170, 40), (120, 180, 60),
            (60, 170, 90), (40, 160, 150), (90, 120, 190), (150, 80, 160),
            (200, 70, 120), (220, 140, 90)]


def _png_bytes(n: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (320, 320), _PALETTE[(n - 1) % 10]).save(buf, format="PNG")
    return buf.getvalue()


def _mp4_bytes(dur=15.0) -> bytes:
    out = _TMP / "clip10.mp4"
    # [execution-contract v1] clip CUMPLE el contrato (short → 9:16; sin
    # production_unit → VIDEO_SECONDS=15): complete() valida con ffprobe.
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0xFF8C00:s=720x1280:d={dur}",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", str(dur), "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
        check=True, capture_output=True, timeout=60)
    return out.read_bytes()


def _consent_allow(job) -> dict | None:
    """[execution-contract v1.1] §7.1 — simula la capa mecánica legítima:
    configura y releyó CADA control required del spec del job (verdict
    VERIFIED, observed=requested, configured=True) y pide el consentimiento
    del servidor. Solo para el arnés de tests: el flujo REAL lo ejecuta
    flowConfigFn + /generate-consent."""
    spec = job.get("execution_spec")
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (TypeError, ValueError):
            spec = None
    ctrl = {}
    for control, c in (spec or {}).items():
        if isinstance(c, dict) and c.get("required") \
                and c.get("requested") is not None:
            ctrl[control] = {"verdict": "VERIFIED",
                             "observed": c.get("requested"),
                             "configured": True}
    return fj.generation_consent(job["id"], job["job_token"],
                                 {"control_results": ctrl})


LONG_PROMPT = ("CE10_LARGO_V7 :: " + "movimiento lento de cámara sobre el "
               "valle, luz dorada rasante, polvo suspendido, sin texto, " * 120)


def _proyecto10(pid: str) -> str:
    db.create_project(id=pid, title="Escala 10 escenas", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, [
        {"title": f"Escena {i}", "narration": f"Narración {i}.",
         "image_prompt": f"CE10_I{i} :: wide shot scene {i}, golden hour, "
                         "grove, no text",
         "duration": 0.0, "status": "pending",
         "meta": {"production_unit": {
             "id": f"u{i}", "index": i - 1, "type": "scene",
             "video_prompt": (
                 LONG_PROMPT if i == 7
                 else f"CE10_V{i} :: dolly-in lento, escena {i}"
             ) if i < 10 else None}}}  # P1: última escena solo-imagen
        for i in range(1, 11)])
    return pid


# ── auto-render mock (el endpoint HTTP dispara start_flow_render cuando
#    project_done; aquí lo simulamos igual que test_flow_bridge) ──────────────
_RENDER_CALLS: list[str] = []


async def _fake_start_flow_render(pid: str) -> str:
    _RENDER_CALLS.append(pid)
    return f"job_render_{pid}"


orchestrator.start_flow_render = _fake_start_flow_render  # mock


def main() -> int:
    with db.connect() as con:
        con.execute("DELETE FROM flow_jobs")
        con.execute("DELETE FROM scenes")
        con.execute("DELETE FROM projects")

    print("── 1. proyecto de 10 escenas")
    pid = _proyecto10("proj_10esc")
    check("10 escenas en DB", len(db.get_scenes(pid)) == 10)

    print("── 2. enqueue: 19 jobs (10 imagen + 9 video; última solo-imagen)")
    res = fj.enqueue_project(pid)
    check("images == 10", res["images"] == 10, str(res))
    check("videos == 9 (escena 10 sin video por P1)", res["videos"] == 9)
    check("created == 19", res["created"] == 19)

    print("── 3. contrato P1 a escala: sentinels verbatim en cada job")
    st = fj.status_for_project(pid)
    jobs = st["jobs"]
    img_jobs = sorted((j for j in jobs if j["kind"] == "image"),
                      key=lambda j: j["scene_number"])
    vid_jobs = sorted((j for j in jobs if j["kind"] == "video"),
                      key=lambda j: j["scene_number"])
    check("10 image jobs + 9 video jobs",
          len(img_jobs) == 10 and len(vid_jobs) == 9)
    check("cola: 19 queued · 0 done/dead",
          st["counts"]["queued"] == 19 and st["counts"]["done"] == 0
          and st["counts"]["dead"] == 0)
    # el prompt NO viaja en status_for_project (contrato de superficie);
    # se lee de la DB como hacen las baterías de chaos
    with db.connect() as con:
        prompts = {(r["kind"], r["scene_number"]): (r["prompt"] or "")
                   for r in con.execute(
                       "SELECT kind, scene_number, prompt FROM flow_jobs "
                       "WHERE project_id=?", (pid,)).fetchall()}
    check("prompts de imagen: CE10_I{n} presente en los 10 "
          "(el formatter transformacion lo incrusta en composition)",
          all(f"CE10_I{n}" in prompts[("image", n)]
              for n in range(1, 11)))
    check("prompts de video: VERBATIM al inicio (motion) + sufijo Camera",
          all((prompts[("video", n)].startswith("CE10_LARGO_V7") if n == 7
               else prompts[("video", n)].startswith(f"CE10_V{n}"))
              and "\nCamera: " in prompts[("video", n)]
              for n in range(1, 10)))
    p7 = prompts[("video", 7)]
    check("prompt larguísimo (~11KB) fluye entero hasta la cola "
          "(sentinel + contenido íntegro, sin sustitución)",
          p7.startswith("CE10_LARGO_V7 :: ") and len(p7) >= 9000
          and "polvo suspendido" in p7, f"len={len(p7)}")
    check("NO existe video job para la escena 10",
          ("video", 10) not in prompts)

    print("── 4. orden de claims: imágenes 1→10, luego videos 1→9")
    claims = [fj.claim_next("workerA") for _ in range(19)]
    secuencia = [(j["kind"], j["scene_number"]) for j in claims]
    esperado = ([("image", i) for i in range(1, 11)]
                + [("video", i) for i in range(1, 10)])
    check("secuencia exacta de 19 claims", secuencia == esperado,
          str(secuencia))
    check("19 tokens únicos (nonce por claim)",
          len({j["job_token"] for j in claims}) == 19)
    check("claim #20 → None (cola drenada)", fj.claim_next("workerA") is None)

    by_key = {(j["kind"], j["scene_number"]): j for j in claims}

    print("── 5. heartbeat en vuelo")
    hb = fj.heartbeat(by_key[("video", 1)]["id"], by_key[("video", 1)]["job_token"])
    check("heartbeat de video escena 1 → ok", hb is not None
          and (hb.get("ok") is True or hb.get("lease_until")), str(hb))

    print("── 6. completes de imagen → convención canónica")
    oks = [fj.complete(by_key[("image", n)]["id"],
                       by_key[("image", n)]["job_token"],
                       _png_bytes(n))
           for n in range(1, 11)]
    check("10 completes de imagen → ok", all(r is not None for r in oks))
    flow_dir = _cfg.OUTPUT_DIR / pid / "flow"
    check("10 PNGs en convención Escena_NN_flow.png",
          all((flow_dir / f"Escena_{i:02d}_flow.png").exists()
              for i in range(1, 11)))

    print("── 7. fail/retry a escala (video escena 3)")
    v3 = by_key[("video", 3)]
    fr = fj.fail(v3["id"], v3["job_token"], "proof: proof-lectura fallida")
    check("fail 1/2 video → ok, attempts=1, queued",
          fr is not None and fr.get("status") == "queued"
          and fr.get("attempts") == 1, str(fr))
    rc3 = fj.claim_next("workerA")
    check("re-claim devuelve el MISMO job (escena 3 video)",
          rc3 is not None and rc3["id"] == v3["id"]
          and rc3["scene_number"] == 3 and rc3["kind"] == "video")

    print("── 8. recuperación zombie: lease de video escena 5 expira")
    v5 = by_key[("video", 5)]
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET lease_until=? WHERE id=?",
                    ("2000-01-01T00:00:00", v5["id"]))
    rz = fj.claim_next("workerB")
    check("claim tras expiración devuelve video escena 5 recuperado",
          rz is not None and rz["id"] == v5["id"]
          and rz["worker"] == "workerB", str(rz and rz.get("scene_number")))
    late = fj.complete(v5["id"], v5["job_token"], _mp4_bytes())
    check("token VIEJO del zombie → None (una sola era)", late is None)

    print("── 9. completes de video restantes + doble complete")
    v1 = by_key[("video", 1)]
    _consent_allow(v1)  # [§7.1] consentimiento contractual antes de generar
    c1 = fj.complete(v1["id"], v1["job_token"], _mp4_bytes())
    check("complete video escena 1 → ok", c1 is not None)
    v1_path = Path(c1["asset_path"])
    sha_before = hashlib.sha256(v1_path.read_bytes()).hexdigest()
    check("doble complete con el MISMO token → None (409-equivalente)",
          fj.complete(v1["id"], v1["job_token"], _mp4_bytes()) is None)
    check("asset NO sobreescrito por el segundo complete",
          hashlib.sha256(v1_path.read_bytes()).hexdigest() == sha_before)
    for n in (2, 4, 6, 7, 8, 9):
        j = by_key[("video", n)]
        _consent_allow(j)  # [§7.1] cada video pasa por el gate pre-generación
        check(f"complete video escena {n} → ok",
              fj.complete(j["id"], j["job_token"], _mp4_bytes()) is not None)
    _consent_allow(rz)  # [§7.1] el zombie recuperado también pasa por el gate
    c5 = fj.complete(rz["id"], rz["job_token"], _mp4_bytes())
    check("complete escena 5 recuperada → ok (el proyecto AÚN no cierra: "
          "el reintento de video 3 sigue en disputa)",
          c5 is not None and c5.get("project_done") is False, str(c5)[:120])
    # [execution-contract v1.1] §7.1 — el reintento de video 3 llega con
    # exec_state PROVIDER_FAILURE (huella TERMINAL del intento 1): el
    # re-gate (consent) es ALLOW pero JAMÁS reescribe estado desde un
    # terminal (progress_allowed §9) → la barrera de complete() no ve
    # huella post-gate → fail-closed CONFIG_UNVERIFIABLE (retry sin
    # exec_state limpio no genera, ni siquiera con consent válido).
    con_rc3 = _consent_allow(rc3)
    check("re-gate del reintento (rc3) → consent ALLOW (evidencia válida)",
          con_rc3 is not None and con_rc3.get("allowed") is True,
          repr(con_rc3))
    try:
        fj.complete(rc3["id"], rc3["job_token"], _mp4_bytes())
        c3_err = None
    except ValueError as exc:
        c3_err = str(exc)
    check("reintento de video escena 3 → BARRERA §7.1: ValueError "
          "CONFIG_UNVERIFIABLE (PROVIDER_FAILURE jamás post-gate)",
          bool(c3_err) and c3_err.startswith("CONFIG_UNVERIFIABLE:"),
          repr(c3_err)[:160])
    with db.connect() as con:
        f3 = dict(con.execute(
            "SELECT status, exec_state, asset_path FROM flow_jobs "
            "WHERE id=?", (rc3["id"],)).fetchone())
    check("reintento barrado → dead CONFIG_UNVERIFIABLE, sin asset",
          f3["status"] == "dead" and f3["exec_state"] == "CONFIG_UNVERIFIABLE"
          and not f3["asset_path"], str(f3)[:140])
    # recuperación por la vía legítima: con la cola sin NINGÚN claimed
    # vigente, el re-enqueue recrea SOLO la fila dead del video 3 (fresca,
    # exec_state QUEUED) → ciclo completo consent → complete → done.
    res_v3 = fj.enqueue_project(pid)
    check("re-enqueue recrea SOLO el video 3 barrado (1 video)",
          res_v3["created"] == 1 and res_v3["videos"] == 1
          and res_v3["images"] == 0, str(res_v3))
    v3b = fj.claim_next("workerA")
    check("video 3 recreado → claim fresco (escena 3 video)",
          v3b is not None and v3b["kind"] == "video"
          and v3b["scene_number"] == 3, str(v3b)[:90])
    _consent_allow(v3b)
    c3b = fj.complete(v3b["id"], v3b["job_token"], _mp4_bytes())
    check("ÚLTIMO complete (video 3 recreado tras la barrera) → "
          "project_done + renderable",
          c3b is not None and c3b.get("project_done") is True
          and c3b.get("renderable") is True, str(c3b)[:160])
    check("claim tras done → None", fj.claim_next("workerB") is None)

    print("── 10. estado final + auto-render una sola vez")
    st2 = fj.status_for_project(pid)
    check("19 done · 0 queued · 0 claimed · 0 dead",
          st2["counts"] == {"queued": 0, "claimed": 0, "done": 19, "dead": 0},
          str(st2["counts"]))
    scenes = db.get_scenes(pid)
    check("10/10 escenas con image_path mapeado",
          all(sc.get("image_path") for sc in scenes),
          str([bool(sc.get("image_path")) for sc in scenes]))
    asyncio.run(orchestrator.start_flow_render(pid))  # como hace el endpoint
    check("auto-render disparado EXACTAMENTE una vez con el pid",
          _RENDER_CALLS == [pid], str(_RENDER_CALLS))

    print("── 11. video QA a escala (con forense de medios)")
    qa = vqa.qa_project(pid)
    check("QA corre sin lanzar", qa["ok"] is True)
    check("status 'ok' (assets cálidos sanos, cero warns)",
          qa["status"] == "ok", str(qa["status"]))
    check("10 escenas en el QA", qa["summary"]["scenes"] == 10)
    check("0 errores de imagen y de clip",
          qa["summary"]["image_errors"] == 0
          and qa["summary"]["clip_errors"] == 0)
    check("todas las imágenes source=mapped",
          all(s.get("image", {}).get("source") == "mapped"
              for s in qa["scenes"]))
    clips = [c for s in qa["scenes"] for c in (s.get("clips") or [])]
    check("9 clips QA-ejercitados", len(clips) == 9, str(len(clips)))
    check("cero pantalla negra/azul/silencio en los 9 clips",
          all(not c.get("pantalla_negra") and not c.get("pantalla_azul")
              and not c.get("audio_silencioso") for c in clips))

    print("── 12. re-enqueue idempotente tras done")
    res2 = fj.enqueue_project(pid)
    check("re-enqueue NO recrea jobs done (created=0)",
          res2["created"] == 0 and res2["images"] == 0 and res2["videos"] == 0,
          str(res2))
    st3 = fj.status_for_project(pid)
    check("la cola sigue exacta: 19 done", st3["counts"]["done"] == 19)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
