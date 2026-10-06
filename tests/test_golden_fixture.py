#!/usr/bin/env python3
"""Batería FIXTURE GOLDEN OFICIAL — GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json.

El fixture canónico (tests/fixtures/GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json)
es datos de prueba SINTÉTICOS (sentinels CE_SENTINEL_V1/V2, claramente marcados
como fixture — NO prompts creativos reales) y recorre aquí la CADENA DE
PRODUCCIÓN REAL de punta a punta, con base de datos en disco (no escenas en
memoria como en test_flow_contract_p1.py):

    archivo fixture (JSON en disco)
      → production_json.parse_payload → validate → ingest (proyecto + escenas en DB)
      → escenas LEÍDAS DE LA BASE (roundtrip JSON de meta incluido)
      → flow_export.build_script_json (script.json — contrato P1)
      → flow_jobs.enqueue_project (cola real)
      → claim → complete (PNG validado con PIL → flow/Escena_NN_flow.png)
      → video_qa.qa_project (QA con ffprobe/PIL)

Si esta batería pasa, el fixture Golden oficial es ejecutable por el sistema
real de principio a fin y el video_prompt del Creative Engine llega VERBATIM
a la cola que consume la extensión.

Uso:  cd yt_automation_v2 && python3 tests/test_golden_fixture.py
      python3 -m pytest tests/test_golden_fixture.py -q
"""
import asyncio
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / \
    "GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json"

# ── parcheo ANTES de importar: DB y OUTPUT a tmp ─────────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="golden_fixture_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
from services import production_json as pj  # noqa: E402
from services.themes import STYLES  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _png_bytes(w=720, h=1280, color=(20, 160, 90)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _ingest_fixture() -> str:
    """Cadena REAL: fixture → parse → ingest (crea proyecto + escenas en DB)."""
    raw = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(raw)

    def _crear(g: dict) -> dict:
        pmeta = {}
        if g.get("project_extra"):
            pmeta["production_project_extra"] = g["project_extra"]
        if g.get("root_extra"):
            pmeta["production_root_extra"] = g["root_extra"]
        return db.create_project(
            title=(g.get("titulo") or "Golden Fixture"),
            mode="production_json",
            style=g.get("estilo") or "auto",
            format=g.get("formato") or "short",
            meta=pmeta,
            platforms=g.get("plataformas") or ["youtube"],
            niche=g.get("nicho"),
        )

    res = asyncio.new_event_loop().run_until_complete(pj.ingest(
        payload, {s["id"] for s in STYLES}, _crear,
        auto_start_override=False))
    pid = (res or {}).get("project_id") or (res or {}).get("id")
    if not pid:
        # algunas versiones devuelven el dict del proyecto directamente
        pid = (res or {}).get("project", {}).get("id") if isinstance(res, dict) else None
    return pid, res


def main() -> int:
    print("═══ FIXTURE GOLDEN OFICIAL · cadena completa con DB real ═══")

    print("── 1. el fixture existe y es JSON válido")
    check("fixture presente en tests/fixtures/", FIXTURE.exists())
    raw = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(raw)
    check("3 unidades en sequence", len(payload["sequence"]) == 3)
    check("unidades del tipo canónico",
          all(u["type"] == "functional_shot_transformation_beat"
              for u in payload["sequence"]))
    s1 = payload["sequence"][0]["motion_prompt"]
    s2 = payload["sequence"][1]["motion_prompt"]
    check("sentinels únicos presentes (synthetic test data)",
          s1.startswith("CE_SENTINEL_V1") and s2.startswith("CE_SENTINEL_V2"))

    print("── 2. ingest REAL: parse → validate → proyecto + escenas en DB")
    pid, res_ing = _ingest_fixture()
    check("ingest devuelve proyecto", bool(pid), str(res_ing)[:150])
    if not pid:
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1
    project = db.get_project(pid)
    check("proyecto creado en DB (mode production_json)",
          bool(project) and project["mode"] == "production_json")
    escenas = db.get_scenes(pid)
    check("3 escenas en DB", len(escenas) == 3, str(len(escenas)))
    original_guardado = _cfg.OUTPUT_DIR / pid / "production.json"
    check("production.json original guardado por ingest",
          original_guardado.exists(), str(original_guardado))

    print("── 3. roundtrip DB: la unidad creativa sobrevive a meta JSON")
    pu1 = escenas[0]["meta"]["production_unit"]
    u1 = escenas[0]["meta"]["unit"]
    check("video_prompt == CE_SENTINEL_V1 verbatim desde la DB",
          pu1["video_prompt"] == s1, repr(pu1.get("video_prompt"))[:90])
    check("duration_target 8 desde la DB", pu1.get("duration_target") == 8,
          str(pu1.get("duration_target")))
    check("initial_state/action/change/final_state desde la DB",
          u1["initial_state"] == payload["sequence"][0]["initial_state"]
          and u1["action"] == payload["sequence"][0]["action"]
          and u1["change"] == payload["sequence"][0]["change"]
          and u1["final_state"] == payload["sequence"][0]["final_state"])
    check("casting/story_function/niche_extra desde la DB",
          u1["casting"] == payload["sequence"][0]["casting"]
          and u1["story_function"] == payload["sequence"][0]["story_function"]
          and u1["niche_extra"] == payload["sequence"][0]["niche_extra"])
    check("audio + references desde la DB",
          pu1["audio"] == payload["sequence"][0]["audio"]
          and pu1["references"] == payload["sequence"][0]["references"])

    print("── 4. script.json (contrato P1) generado desde escenas de DB")
    from pipeline import flow_export as fx
    data = fx.build_script_json(project, escenas, fmt="transformacion")
    sc = data["scenes"]
    check("3 escenas en el export", len(sc) == 3)
    check("escena 1 motion == CE_SENTINEL_V1 verbatim",
          sc[0]["video_prompt"]["motion"] == s1,
          repr(sc[0]["video_prompt"]["motion"])[:90])
    check("escena 2 motion == CE_SENTINEL_V2 verbatim",
          sc[1]["video_prompt"]["motion"] == s2)
    check("última escena SOLO imagen",
          "video_prompt" not in sc[2] and "videoPrompt" not in sc[2])
    check("duration_target llega al export (8 y 6)",
          sc[0].get("duration") == 8 and sc[1].get("duration") == 6,
          f"{sc[0].get('duration')}/{sc[1].get('duration')}")
    check("image_prompt aplanado contiene el visual_prompt",
          "jade mask" in json.dumps(sc[0].get("image_prompt"),
                                    ensure_ascii=False).lower()
          or "jade mask" in str(sc[0].get("image_prompt")).lower())

    print("── 5. cola real desde el fixture: enqueue → claim → prompts")
    from services import flow_jobs as fj
    from services import video_qa as vqa
    res_q = fj.enqueue_project(pid)
    check("3 imágenes + 2 videos encolados",
          res_q["images"] == 3 and res_q["videos"] == 2, str(res_q))
    j1 = fj.claim_next("w-golden")
    check("primer job = imagen escena 1 con prompt del visual_prompt",
          j1 and j1["kind"] == "image" and j1["scene_number"] == 1
          and "jade mask" in j1["prompt"].lower(), repr(j1["prompt"])[:90])
    check("complete imagen escena 1 ok",
          bool(fj.complete(j1["id"], j1["job_token"], _png_bytes())))
    jv1 = None
    got_video = None
    for _ in range(4):  # drena imágenes hasta el primer video
        jx = fj.claim_next("w-golden")
        if jx and jx["kind"] == "video":
            got_video = jx
            break
        if jx:
            fj.complete(jx["id"], jx["job_token"], _png_bytes())
    check("video escena 1 con prompt == CE_SENTINEL_V1 verbatim (base)",
          got_video is not None and got_video["prompt"].startswith(s1),
          repr(got_video["prompt"])[:90] if got_video else "no video job")

    print("── 6. complete del video → asset en convención canónica")
    import subprocess
    out_clip = _TMP / "golden_clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0xFF8C00:s=720x1280:d=1.0",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(out_clip)],
        check=True, capture_output=True, timeout=60)
    res_v = fj.complete(got_video["id"], got_video["job_token"],
                        out_clip.read_bytes())
    vpath = _cfg.OUTPUT_DIR / pid / "flow" / "Escena_01_video_1.mp4"
    check("clip guardado en flow/Escena_01_video_1.mp4",
          bool(res_v) and Path(res_v["asset_path"]) == vpath,
          str(res_v)[:120])

    print("── 7. QA del proyecto en progreso (video_qa)")
    qa = vqa.qa_project(pid)
    check("QA corre sin lanzar (status ok/warn)", qa["ok"] is True)
    check("QA escena 1: imagen válida 720x1280",
          qa["scenes"][0]["image"]["width"] == 720
          and qa["scenes"][0]["image"]["height"] == 1280)
    check("QA escena 1: clip válido con ffprobe (1.0s)",
          qa["scenes"][0]["clips"]
          and qa["scenes"][0]["clips"][0]["duration_s"] >= 0.3)
    check("QA marca escenas pendientes como warn (no error)",
          qa["status"] in ("ok", "warn"), qa["status"])
    try:
        vqa.qa_project("proyecto_fantasma")
        check("QA proyecto inexistente → LookupError", False)
    except LookupError:
        check("QA proyecto inexistente → LookupError", True)

    print("── 8. limpieza")
    shutil.rmtree(_TMP, ignore_errors=True)
    check("tmp eliminado", not _TMP.exists())

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_golden_fixture():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
