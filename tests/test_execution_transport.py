#!/usr/bin/env python3
"""Batería EXECUTION TRANSPORT — §17-A: la cadena completa del spec de
ejecución desde el Production JSON hasta el job JSON que consume la
extensión, EN HERMÉTICO (DB/OUTPUT en tmp; sin Chrome, sin red, sin Flow):

    meta.production_unit (production_json-style, en scenes de DB)
      → flow_export.build_script_json  (duration/references por entrada)
      → flow_jobs.enqueue_project      (spec JSON + exec_state QUEUED por job)
      → flow_jobs.claim_next           (spec PARSEADO + CLAIMED + job_token)
      → job JSON (json.dumps/parse, lo que main.py/bridge transportan)
      → status_for_project             (counts + exec_counts sin spec crudo)
      → migración DB                   (3 columnas nuevas, patrón PRAGMA)
      → idempotencia                   (done_prev se respeta; P1 byte-equal)

Regla de oro verificada en cada eslabón: el spec es la TERCERA CAPA — la
columna `prompt` (P1) queda byte-igual antes/después de todo; el spec jamás
la edita.

Uso:  cd yt_automation_v2 && python3 tests/test_execution_transport.py
      python3 -m pytest tests/test_execution_transport.py -q
"""
import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar: DB/OUTPUT a tmp (patrón test_flow_video_v3) ───
_TMP = Path(tempfile.mkdtemp(prefix="execution_transport_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
db.init_db()
from pipeline import flow_export as fx  # noqa: E402
from services import flow_jobs as fj  # noqa: E402
from services import execution_contract as ec  # noqa: E402

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


# ── fixture: proyecto + 3 escenas con production_unit en meta (estilo
#    test_golden_fixture §3: la unidad creativa vive en scenes.meta JSON) ─────
_PID = "p_transport"
_REF1 = [{"kind": "image", "url": "https://example.com/ref1.png"},
         {"kind": "image", "url": "https://example.com/ref2.png"}]
_P1_S1 = "CE_SENTINEL_T1: primer plano del reloj deteniéndose"
_P1_S2 = "CE_SENTINEL_T2: la puerta se abre lentamente"


def _crear_proyecto() -> None:
    db.create_project(id=_PID, title="Transport Test", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(_PID, [
        {"title": "Escena 1", "narration": "Uno.",
         "image_prompt": "Reloj detenido sobre mesa de madera",
         "meta": {"production_unit": {
             "duration_target": 8, "video_prompt": _P1_S1,
             "references": list(_REF1)}}},
        {"title": "Escena 2", "narration": "Dos.",
         "image_prompt": "Puerta antigua entreabierta",
         "meta": {"production_unit": {
             "duration_target": 6, "video_prompt": _P1_S2}}},
        {"title": "Escena 3", "narration": "Tres.",
         "image_prompt": "Revelación final del pasillo vacío"},
    ])


def _filas(pid: str = _PID) -> dict:
    """flow_jobs del proyecto indexado por (kind, scene_number)."""
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM flow_jobs WHERE project_id=? ORDER BY kind, "
            "scene_number", (pid,)).fetchall()
    return {(r["kind"], int(r["scene_number"])): dict(r) for r in rows}


def _fila(k: tuple, pid: str = _PID) -> dict:
    return _filas(pid).get(k, {})


def main() -> int:
    print("═══ EXECUTION TRANSPORT §17-A · spec de producción a job JSON ═══")

    print("── 1. Production JSON-style → DB scenes (meta JSON roundtrip)")
    _crear_proyecto()
    project = db.get_project(_PID)
    escenas = db.get_scenes(_PID)
    check("proyecto con 3 escenas en DB", bool(project)
          and len(escenas) == 3, str(len(escenas or [])))
    pu1 = escenas[0]["meta"]["production_unit"]
    check("production_unit sobrevive al meta JSON de la DB",
          pu1.get("duration_target") == 8 and pu1.get("video_prompt") == _P1_S1
          and pu1.get("references") == _REF1, repr(pu1)[:120])
    check("escena 3 SIN production_unit (fuente ausente honesta)",
          not escenas[2]["meta"].get("production_unit"))

    print("── 2. build_script_json: duration/references por entrada")
    data = fx.build_script_json(project, escenas, fmt="transformacion")
    check("export formato short (aspect 9:16 downstream)",
          data.get("format") == "short", repr(data.get("format")))
    sc = data["scenes"]
    check("entrada 1: duration 8 desde duration_target",
          sc[0].get("duration") == 8, repr(sc[0].get("duration")))
    check("entrada 2: duration 6",
          sc[1].get("duration") == 6, repr(sc[1].get("duration")))
    check("entrada 3 sin fuente → VIDEO_SECONDS (jamás None inventado)",
          sc[2].get("duration") == fx.VIDEO_SECONDS,
          repr(sc[2].get("duration")))
    check("entrada 1: references transportadas verbatim",
          sc[0].get("references") == _REF1, repr(sc[0].get("references")))
    check("entrada 3: references [] (no None)",
          sc[2].get("references") == [], repr(sc[2].get("references")))
    check("P1 verbatim en video_prompt.motion (contrato P1 intacto aquí)",
          sc[0]["video_prompt"]["motion"] == _P1_S1
          and sc[1]["video_prompt"]["motion"] == _P1_S2)

    print("── 3. enqueue_project: spec JSON + exec_state QUEUED por job")
    res = fj.enqueue_project(_PID)
    check("3 imágenes + 2 videos encolados",
          res.get("images") == 3 and res.get("videos") == 2, str(res))
    filas = _filas()
    check("5 filas en flow_jobs", len(filas) == 5, str(len(filas)))
    jv1 = filas[("video", 1)]
    jv2 = filas[("video", 2)]
    ji1 = filas[("image", 1)]
    ji3 = filas[("image", 3)]
    check("exec_state QUEUED al encolar (todas las filas)",
          all(f["exec_state"] == ec.EXEC_STATE_QUEUED for f in filas.values()))
    spec_v1 = json.loads(jv1["execution_spec"])
    check("video escena 1: spec duration.requested == 8",
          spec_v1["duration"]["requested"] == 8
          and spec_v1["duration"]["required"] is True,
          repr(spec_v1["duration"]))
    check("video escena 1: aspect 9:16 derivado del formato short",
          spec_v1["aspect_ratio"] == {"requested": "9:16", "required": True},
          repr(spec_v1["aspect_ratio"]))
    check("video escena 1: outputs 1 / model None / references transportadas",
          spec_v1["outputs"]["requested"] == 1
          and spec_v1["model"]["requested"] is None
          and spec_v1["references"] == _REF1,
          repr((spec_v1["outputs"], spec_v1["model"], spec_v1["references"])))
    spec_v2 = json.loads(jv2["execution_spec"])
    check("video escena 2: spec duration.requested == 6",
          spec_v2["duration"]["requested"] == 6, repr(spec_v2["duration"]))
    spec_i1 = json.loads(ji1["execution_spec"])
    check("imagen escena 1: spec duration null (imagen no tiene duración)",
          spec_i1["duration"]["requested"] is None
          and spec_i1["duration"]["required"] is False,
          repr(spec_i1["duration"]))
    check("imagen escena 3 (sin fuente): spec aspect 9:16, duration null, "
          "references []",
          json.loads(ji3["execution_spec"])["aspect_ratio"]["requested"]
          == "9:16"
          and json.loads(ji3["execution_spec"])["duration"]["requested"]
          is None
          and json.loads(ji3["execution_spec"])["references"] == [],
          repr(json.loads(ji3["execution_spec"]))[:140])
    # P1 en el job = video_prompt del export aplanado verbatim (motion + Camera)
    p1_v1 = fj._video_prompt_text(sc[0]["video_prompt"])
    p1_v2 = fj._video_prompt_text(sc[1]["video_prompt"])
    check("P1 en columna prompt: motion verbatim + Camera del export",
          jv1["prompt"] == p1_v1 and p1_v1.startswith(_P1_S1),
          repr(jv1["prompt"])[:90])
    check("P1 en columna prompt: escena 2 verbatim",
          jv2["prompt"] == p1_v2 and p1_v2.startswith(_P1_S2),
          repr(jv2["prompt"])[:90])
    check("spec es tercera capa: prompt_adapted NULL y prompt intacto "
          "al construir el spec",
          all(f["prompt_adapted"] is None for f in filas.values()))
    snapshot_p1 = {k: f["prompt"] for k, f in filas.items()}

    print("── 4. claim_next: spec PARSEADO + CLAIMED + job_token")
    j1 = fj.claim_next("w-transport", pid=_PID)
    check("primer claim = imagen escena 1",
          j1 and j1["kind"] == "image" and j1["scene_number"] == 1,
          repr(j1)[:100] if j1 else "None")
    check("claim entrega execution_spec PARSEADO (dict, no string)",
          isinstance(j1.get("execution_spec"), dict),
          repr(type(j1.get("execution_spec"))))
    check("claim entrega exec_state CLAIMED EN DB (primer claim)",
          _fila(("image", 1))["exec_state"] == ec.EXEC_STATE_CLAIMED
          and _fila(("image", 1))["status"] == "claimed",
          repr(_fila(("image", 1)).get("exec_state")))
    check("claim entrega job_token + lease + worker + spec parseado "
          "(el dict devuelto es el snapshot del job con nonce parcheado)",
          bool(j1.get("job_token")) and bool(j1.get("lease_until"))
          and j1.get("worker") == "w-transport"
          and isinstance(j1.get("execution_spec"), dict),
          repr((bool(j1.get("job_token")), bool(j1.get("lease_until")))))
    check("P1 byte-igual tras el claim",
          j1["prompt"] == snapshot_p1[("image", 1)])

    print("── 5. job JSON end-to-end (lo que transportan main.py/bridge)")
    payload = json.dumps(j1, ensure_ascii=False)
    parsed = json.loads(payload)
    check("job JSON serializa y re-parsea con el spec intacto",
          parsed["execution_spec"]["schema_version"] == "1.0"
          and parsed["execution_spec"]["aspect_ratio"]["requested"] == "9:16",
          repr(parsed.get("execution_spec"))[:100])
    check("job JSON lleva job_token y prompt (contrato del bridge)",
          parsed.get("job_token") == j1["job_token"]
          and parsed.get("prompt") == j1["prompt"])

    print("── 6. complete imagen 1 + idempotencia respeta done_prev")
    r_img = fj.complete(j1["id"], j1["job_token"], _png_bytes())
    check("complete imagen ok (sin contract para kind image)",
          bool(r_img) and r_img.get("ok") and r_img.get("contract") is None,
          str(r_img)[:120])
    done_id = j1["id"]
    res2 = fj.enqueue_project(_PID)
    check("re-enqueue conserva los done (no re-trabaja assets subidos)",
          res2.get("created") == 4, str(res2))
    with db.connect() as con:
        row = con.execute("SELECT * FROM flow_jobs WHERE id=?",
                          (done_id,)).fetchone()
    check("el job done sigue con el MISMO id y status done",
          bool(row) and row["status"] == "done"
          and row["asset_path"] is not None,
          repr(dict(row))[:120] if row else "None")
    filas2 = _filas()
    check("P1 byte-igual en TODAS las filas tras re-enqueue "
          "(el spec jamás muta prompts)",
          all(filas2[k]["prompt"] == snapshot_p1[k] for k in snapshot_p1),
          repr({k: filas2[k]["prompt"][:40] for k in snapshot_p1}))
    check("specs regenerados idénticos (deterministas)",
          json.loads(filas2[("video", 1)]["execution_spec"]) == spec_v1,
          "spec v1 cambió tras re-enqueue")
    check("prompt_adapted sigue NULL en todas las filas (sin P2 espurio)",
          all(f["prompt_adapted"] is None for f in filas2.values()))

    print("── 7. complete de imágenes (drenaje hasta el video)")
    for _ in range(2):
        jx = fj.claim_next("w-transport", pid=_PID)
        check("drenaje imagen escena siguiente",
              jx and jx["kind"] == "image",
              repr(jx)[:80] if jx else "None")
        fj.complete(jx["id"], jx["job_token"], _png_bytes())

    print("── 8. video job: el spec viaja END-TO-END en el job JSON")
    jv = fj.claim_next("w-transport", pid=_PID)
    check("claim del video escena 1", jv and jv["kind"] == "video"
          and jv["scene_number"] == 1, repr(jv)[:90] if jv else "None")
    vpayload = json.dumps(jv, ensure_ascii=False)
    vparsed = json.loads(vpayload)
    vspec = vparsed["execution_spec"]
    check("job JSON del video transporta duration.requested == 8",
          vspec["duration"]["requested"] == 8, repr(vspec["duration"]))
    check("job JSON del video transporta aspect/outputs/references",
          vspec["aspect_ratio"]["requested"] == "9:16"
          and vspec["outputs"]["requested"] == 1
          and vspec["references"] == _REF1,
          repr((vspec["aspect_ratio"], vspec["outputs"]))[:120])
    check("job JSON del video transporta P1 aplanado byte-igual",
          vparsed["prompt"] == fj._video_prompt_text(sc[0]["video_prompt"])
          and vparsed["prompt"].startswith(_P1_S1),
          repr(vparsed["prompt"])[:90])
    jv2b = fj.claim_next("w-transport", pid=_PID)
    check("video escena 2 claimado con spec duration 6",
          jv2b and jv2b["kind"] == "video"
          and jv2b["execution_spec"]["duration"]["requested"] == 6,
          repr(jv2b["execution_spec"]["duration"])
          if jv2b else "no claim")

    print("── 9. status_for_project: counts + exec_counts (sin spec crudo)")
    st = fj.status_for_project(_PID)
    check("status_for_project ok con project_id",
          st.get("ok") is True and st.get("project_id") == _PID)
    check("counts clásicos presentes (queued/claimed/done/dead)",
          st["counts"] == {"queued": 0, "claimed": 2, "done": 3, "dead": 0},
          repr(st["counts"]))
    check("exec_counts presentes (CLAIMED observable)",
          isinstance(st.get("exec_counts"), dict)
          and st["exec_counts"].get("CLAIMED") == 2,
          repr(st.get("exec_counts")))
    check("jobs incluyen exec_state pero NO el spec crudo (payload ligero)",
          all("exec_state" in j and "execution_spec" not in j
              for j in st["jobs"]), repr(st["jobs"][0].keys()))

    print("── 10. migración DB: 3 columnas nuevas sobre esquema viejo")
    mig_path = _TMP / "old_schema.db"
    con_old = sqlite3.connect(mig_path)
    con_old.executescript("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, title TEXT, status TEXT, mode TEXT,
            style TEXT, format TEXT, voice TEXT, tts_provider TEXT,
            source_url TEXT, video_url TEXT, thumbnail_url TEXT,
            youtube_id TEXT, error TEXT, progress INTEGER NOT NULL DEFAULT 0,
            step_label TEXT, meta TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            avatar_id TEXT, platforms TEXT NOT NULL DEFAULT '[]',
            niche TEXT
        );
        CREATE TABLE flow_jobs (
            id           TEXT PRIMARY KEY,
            project_id   TEXT NOT NULL,
            kind         TEXT NOT NULL,
            scene_number INTEGER NOT NULL,
            part         INTEGER NOT NULL DEFAULT 1,
            prompt       TEXT NOT NULL DEFAULT '',
            prompt_adapted TEXT,
            prompt_meta  TEXT,
            status       TEXT NOT NULL DEFAULT 'queued',
            attempts     INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            lease_cycles INTEGER NOT NULL DEFAULT 0,
            worker       TEXT,
            job_token    TEXT,
            lease_until  TEXT,
            error        TEXT,
            asset_path   TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
    """)
    antes = [r[1] for r in con_old.execute(
        "PRAGMA table_info(flow_jobs)").fetchall()]
    check("esquema viejo SIN las 3 columnas nuevas",
          all(c not in antes for c in
              ("execution_spec", "exec_state", "contract_result")),
          repr(antes))
    db._migrate(con_old)
    con_old.commit()
    despues = [r[1] for r in con_old.execute(
        "PRAGMA table_info(flow_jobs)").fetchall()]
    con_old.close()
    check("migración añade execution_spec",
          "execution_spec" in despues, repr(despues))
    check("migración añade exec_state", "exec_state" in despues)
    check("migración añade contract_result", "contract_result" in despues)
    check("migración conserva las columnas previas (lease_cycles/prompt_adapted)",
          all(c in despues for c in
              ("lease_cycles", "prompt_adapted", "prompt", "job_token")))
    con_idem = sqlite3.connect(mig_path)
    try:
        db._migrate(con_idem)
        con_idem.commit()
        idem = [r[1] for r in con_idem.execute(
            "PRAGMA table_info(flow_jobs)").fetchall()]
    finally:
        con_idem.close()
    check("migración es idempotente (segunda pasada: mismas columnas)",
          idem == despues, repr(idem))

    print("── 11. P1 inmutable al cierre de TODA la cadena")
    filas_fin = _filas()
    check("P1 byte-igual al cierre (enqueue → claims → completes → "
          "re-enqueue → migración)",
          all(filas_fin[k]["prompt"] == snapshot_p1[k] for k in snapshot_p1),
          repr({k: filas_fin[k]["prompt"][:40] for k in snapshot_p1}))
    check("prompt_adapted NULL al cierre (P2 jamás escrito por el spec)",
          all(f["prompt_adapted"] is None for f in filas_fin.values()))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
