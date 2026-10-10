#!/usr/bin/env python3
"""Batería FLOW CONTRACT STATES — §17 C/D/E + máquina de estados finos sobre
la cola REAL (flow_jobs), EN HERMÉTICO (DB/OUTPUT/ledger en tmp; sin Chrome,
sin red, sin Flow; MP4/PNG reales via ffmpeg/PIL).

Cubre:

  §9  set_exec_state: progresión lineal (FLOW_TAB_READY → … →
      GENERATION_SUBMITTED), rewind RECHAZADO, estado fantasma RECHAZADO,
      token inválido → None (409), estado vacío → invalid_state.
  §13/E complete con MP4 REAL 8s 9:16 → CONTRACT_OK: done +
      exec_state CONTRACT_VALIDATED + contract_result persistido en DB.
  §13/E complete con MP4 REAL 5s vs spec 8s → ValueError
      "ASSET_INVALID: CONTRACT_VIOLATION": dead terminal ASSET_INVALID,
      contract_result persistido, fail() posterior → None (409, sin retry),
      flow_adaptation clase M (ASSET_CONTRACT_VIOLATION, HIGH, sin requeue,
      sin FLOW_ADAPTATION_REQUIRED) con entrada en el ledger.
  §17-D fail "CONFIG_MISMATCH: …" → TERMINAL: dead + exec_state
      CONFIG_MISMATCH + config_terminal True + attempts==1 (no maxed),
      clase L HIGH (fuente execution_contract), job dead aunque attempts <
      max, SIN prompt_adapted, procesar_fallo_job sin requeue.
  §17-C fail "CONFIG_UNSUPPORTED: …" → dead CONFIG_UNSUPPORTED.
  DEFENSA: complete/heartbeat sobre job terminal CONFIG_* → None (409).
  PROVIDER_FAILURE intacto: fail genérico 1º → queued (attempts 1 < 2) +
      exec_state PROVIDER_FAILURE; dead → el gancho de adaptación concede el
      reencolar con P1 (clase B, attempts=max-1, sin P2); segundo dead →
      LÍMITE de grants, stays dead.
  P1 inmutable en TODO el circuito: prompt byte-igual; prompt_adapted NULL
      salvo adaptación explícita (aquí jamás: B reencola con P1).

Uso:  cd yt_automation_v2 && python3 tests/test_flow_contract_states.py
      python3 -m pytest tests/test_flow_contract_states.py -q
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar: DB/OUTPUT/ledger a tmp (patrón de la casa) ────
_TMP = Path(tempfile.mkdtemp(prefix="flow_contract_states_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
db.init_db()
from services import flow_jobs as fj  # noqa: E402
from services import flow_adaptation as fa  # noqa: E402
from services import execution_contract as ec  # noqa: E402
from services import memorydv as _mem  # noqa: E402
_mem.MEMORY_DIR = _TMP / "memorydv"       # hermeticidad: cero escrituras repo
fa.LEDGER_PATH = _TMP / "flow_adaptation" / "ledger.jsonl"

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


def _mp4_bytes(dur=1.0, size="720x1280") -> bytes:
    """MP4 real (H.264+AAC) con el patrón EXACTO de test_flow_video_v3
    (lavfi color + sine + -shortest) + -t para duración determinista."""
    out = _TMP / f"clip_states_{dur}_{size}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x2288CC:s={size}:d={dur}",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-shortest", "-t", str(dur),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(out)],
        check=True, capture_output=True, timeout=60)
    return out.read_bytes()


def _proyecto_video(pid: str, escenas: int = 1,
                    duracion: int = 8) -> None:
    """Proyecto short con `escenas` escenas; video_prompt (P1) en todas
    menos la última (build_script_json: la última es SOLO imagen)."""
    filas = []
    for i in range(1, escenas + 1):
        sc = {"title": f"Escena {i}", "narration": f"Beat {i}.",
              "image_prompt": f"Visual {i} del proyecto {pid}"}
        if i < escenas:
            sc["meta"] = {"production_unit": {
                "duration_target": duracion,
                "video_prompt": f"P1 {pid} escena {i}: movimiento de cámara "
                                f"lento y continuo"}}
        filas.append(sc)
    db.create_project(id=pid, title=f"States {pid}", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, filas)


def _fila(jid: str) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT * FROM flow_jobs WHERE id=?",
                        (jid,)).fetchone()
        return dict(r) if r else {}


def _contrato(jid: str) -> dict | None:
    cr = _fila(jid).get("contract_result")
    if not cr:
        return None
    try:
        return json.loads(cr)
    except (TypeError, ValueError):
        return None


def _drenar_imagenes(pid: str) -> int:
    """Claim+complete (PNG) de los jobs image PENDIENTES del proyecto.
    Nunca roba un job de video: solo reclama si HAY imagen en cola (el
    claim ordena imagen antes que video, así que si hay imagen es lo que
    devuelve)."""
    n = 0
    while True:
        with db.connect() as con:
            hay = con.execute(
                """SELECT COUNT(*) c FROM flow_jobs
                   WHERE project_id=? AND kind='image' AND status='queued'""",
                (pid,)).fetchone()["c"]
        if not hay:
            return n
        j = fj.claim_next("w-states", pid=pid)
        if not j or j["kind"] != "image":
            raise AssertionError(f"drenaje inesperado: {j!r}")
        fj.complete(j["id"], j["job_token"], _png_bytes())
        n += 1


_PIDS: list[str] = []


def main() -> int:
    print("═══ FLOW CONTRACT STATES · §17 C/D/E + máquina de estados ═══")

    print("── 1. setup: proyecto de 3 escenas → 3 imágenes + 2 videos")
    _proyecto_video("p_states", escenas=3, duracion=8)
    _PIDS.append("p_states")
    res = fj.enqueue_project("p_states")
    check("3 imágenes + 2 videos encolados",
          res.get("images") == 3 and res.get("videos") == 2, str(res))
    check("drenaje de las 3 imágenes", _drenar_imagenes("p_states") == 3)
    vid1 = fj.claim_next("w-states", pid="p_states")
    check("claim del video escena 1 con token",
          vid1 and vid1["kind"] == "video" and vid1["scene_number"] == 1
          and bool(vid1.get("job_token")),
          repr(vid1)[:90] if vid1 else "None")
    vid2 = fj.claim_next("w-states", pid="p_states")
    check("claim del video escena 2 (segundo video disponible)",
          vid2 and vid2["kind"] == "video" and vid2["scene_number"] == 2,
          repr(vid2)[:90] if vid2 else "None")
    check("exec_state CLAIMED en DB tras el claim",
          _fila(vid1["id"])["exec_state"] == ec.EXEC_STATE_CLAIMED,
          repr(_fila(vid1["id"]).get("exec_state")))

    print("── 2. §9 progresión lineal del estado fino")
    secuencia = [ec.EXEC_STATE_TAB_READY, ec.EXEC_STATE_CAPS,
                 ec.EXEC_STATE_CONFIGURED, ec.EXEC_STATE_VERIFIED,
                 ec.EXEC_STATE_SUBMITTED]
    for st in secuencia:
        r = fj.set_exec_state(vid1["id"], vid1["job_token"], st,
                              detail=f"avance a {st}",
                              evidence={"fuente": "arnes"})
        check(f"set_exec_state {st} ok",
              r and r.get("ok") is True and r.get("exec_state") == st,
              repr(r))
        ultimo = r
    check("evidencia registrada en la respuesta (opcional §9)",
          ultimo.get("evidence_registered") is True, repr(ultimo))
    check("estado actual en DB = GENERATION_SUBMITTED",
          _fila(vid1["id"])["exec_state"] == ec.EXEC_STATE_SUBMITTED,
          repr(_fila(vid1["id"]).get("exec_state")))

    print("── 3. §9 rewind/fantasmas/token (jamás rebobina)")
    r_rw = fj.set_exec_state(vid1["id"], vid1["job_token"],
                             ec.EXEC_STATE_CAPS)
    check("rewind SUBMITTED→CAPABILITIES_CAPTURED rechazado",
          r_rw == {"ok": False, "error": "illegal_transition",
                   "current": "GENERATION_SUBMITTED",
                   "requested": "CAPABILITIES_CAPTURED"}, repr(r_rw))
    check("DB sigue en GENERATION_SUBMITTED (el rewind no tocó nada)",
          _fila(vid1["id"])["exec_state"] == ec.EXEC_STATE_SUBMITTED)
    r_fg = fj.set_exec_state(vid1["id"], vid1["job_token"],
                             "ESTADO_FANTASMA")
    check("estado fantasma → illegal_transition",
          r_fg and r_fg.get("ok") is False
          and r_fg.get("error") == "illegal_transition", repr(r_fg))
    check("wrong token → None (409)",
          fj.set_exec_state(vid1["id"], "token_falso",
                            ec.EXEC_STATE_OBSERVED) is None)
    check("estado vacío → invalid_state",
          fj.set_exec_state(vid1["id"], vid1["job_token"], "")
          == {"ok": False, "error": "invalid_state"})

    print("── 4. §13/E complete OK con MP4 REAL 8s 9:16")
    res_ok = fj.complete(vid1["id"], vid1["job_token"], _mp4_bytes(8.0))
    check("complete ok", bool(res_ok) and res_ok.get("ok") is True,
          str(res_ok)[:140])
    check("contract.verdict CONTRACT_OK en la respuesta",
          (res_ok.get("contract") or {}).get("verdict") == ec.CONTRACT_OK,
          repr(res_ok.get("contract"))[:120])
    check("job done con exec_state CONTRACT_VALIDATED",
          _fila(vid1["id"])["status"] == "done"
          and _fila(vid1["id"])["exec_state"] == ec.EXEC_STATE_CONTRACT_OK,
          repr((_fila(vid1["id"])["status"], _fila(vid1["id"])["exec_state"])))
    cr_db = _contrato(vid1["id"])
    check("contract_result persistido en DB (JSON parseable, CONTRACT_OK)",
          cr_db is not None and cr_db["verdict"] == ec.CONTRACT_OK
          and cr_db["summary"] == "CONTRACT_OK", repr(cr_db)[:140])
    check("checks duration/aspect VERIFIED contra ffprobe real",
          cr_db["checks"]["duration"]["verdict"] == "VERIFIED"
          and cr_db["checks"]["aspect_ratio"]["verdict"] == "VERIFIED"
          and abs(cr_db["actual_asset"]["duration"] - 8.0)
          <= ec.TRANSPORT_EPSILON_S,
          repr(cr_db["actual_asset"]))
    check("asset en convención canónica flow/Escena_01_video_1.mp4",
          Path(res_ok["asset_path"]).name == "Escena_01_video_1.mp4"
          and Path(res_ok["asset_path"]).exists(), str(res_ok["asset_path"]))
    check("project_done False (queda el video 2 en vuelo)",
          res_ok.get("project_done") is False
          and res_ok.get("renderable") is False, repr(res_ok)[:120])

    print("── 5. §13/E complete VIOLACIÓN con MP4 REAL 5s vs spec 8s")
    try:
        fj.complete(vid2["id"], vid2["job_token"], _mp4_bytes(5.0))
        violacion = None
    except ValueError as exc:
        violacion = str(exc)
    check("ValueError 'ASSET_INVALID: CONTRACT_VIOLATION: …'",
          bool(violacion) and violacion.startswith(
              "ASSET_INVALID: CONTRACT_VIOLATION"), repr(violacion)[:160])
    check("[CONTRACT_VIOLATION] y 'duration' en el error estructurado",
          "[CONTRACT_VIOLATION]" in (violacion or "")
          and "duration" in (violacion or ""), repr(violacion)[:160])
    f2 = _fila(vid2["id"])
    check("job dead terminal ASSET_INVALID",
          f2["status"] == "dead"
          and f2["exec_state"] == ec.EXEC_STATE_ASSET_INVALID,
          repr((f2["status"], f2["exec_state"])))
    cr_bad = _contrato(vid2["id"])
    check("contract_result persistido con verdict CONTRACT_VIOLATION",
          cr_bad is not None
          and cr_bad["verdict"] == ec.CONTRACT_VIOLATION
          and any("duration" in v for v in cr_bad["violations"]),
          repr(cr_bad)[:160])
    check("error column persistida empieza ASSET_INVALID:",
          f2["error"].startswith("ASSET_INVALID:"), repr(f2["error"])[:120])
    check("worker/token/lease limpiados (sin lease zombi)",
          f2["worker"] is None and f2["job_token"] is None
          and f2["lease_until"] is None)

    print("── 6. sin retry tras ASSET_INVALID (fail posterior → 409)")
    check("fail() con el token antiguo → None (409)",
          fj.fail(vid2["id"], vid2["job_token"], "reintento tardío") is None)
    check("el job SIGUE dead (no reencola)",
          _fila(vid2["id"])["status"] == "dead"
          and _fila(vid2["id"])["exec_state"] == ec.EXEC_STATE_ASSET_INVALID)

    print("── 7. flow_adaptation: clase M terminal (sin requeue, con ledger)")
    dec_m = fa.procesar_fallo_job(vid2["id"])
    check("clase M ASSET_CONTRACT_VIOLATION",
          dec_m and dec_m.get("clase") == "M"
          and dec_m.get("reintentar") is False, repr(dec_m)[:160])
    check("sin reporte FLOW_ADAPTATION_REQUIRED (config/contrato ≠ creativo)",
          not dec_m.get("reporte"), repr(dec_m)[:160])
    check("el job sigue dead (la capa jamás reencola clase M)",
          _fila(vid2["id"])["status"] == "dead"
          and _fila(vid2["id"])["prompt_adapted"] is None)
    led = [json.loads(l) for l in fa.LEDGER_PATH.read_text(
        encoding="utf-8").splitlines() if l.strip()] \
        if fa.LEDGER_PATH.exists() else []
    m_reg = next((r for r in led if r.get("job_id") == vid2["id"]), None)
    check("ledger: entrada M con evidencia estructural HIGH",
          m_reg is not None and m_reg["clasificacion"] == "M"
          and m_reg["classification_confidence"] == "HIGH"
          and m_reg["fuente_evidencia"] == "execution_contract",
          repr(m_reg)[:200])
    check("clasificar() del error M: alcance_causal CONFIGURACION "
          "(el ledger registra la clasificación; el alcance vive en ella)",
          fa.clasificar(_fila(vid2["id"])["error"] or "", "video").get(
              "alcance_causal") == "CONFIGURACION")
    check("ledger: P1 registrado intacto (trazable)",
          m_reg is not None
          and m_reg["prompt_original"] == _fila(vid2["id"])["prompt"]
          and m_reg["prompt_adaptado"] is None)

    print("── 8. §17-D fail CONFIG_MISMATCH → terminal (independiente de "
          "attempts)")
    # 2 escenas: la última es SOLO imagen → 1 job de video (escena 1)
    _proyecto_video("p_cfg", escenas=2, duracion=8)
    _PIDS.append("p_cfg")
    fj.enqueue_project("p_cfg")
    _drenar_imagenes("p_cfg")
    vidB = fj.claim_next("w-states", pid="p_cfg")
    check("video de p_cfg claimado",
          vidB and vidB["kind"] == "video", repr(vidB)[:80] if vidB else "X")
    rB = fj.fail(vidB["id"], vidB["job_token"],
                 "CONFIG_MISMATCH: duration requested=8 observed=5s")
    check("respuesta config_terminal True con exec_state CONFIG_MISMATCH",
          rB and rB.get("ok") is True
          and rB.get("config_terminal") is True
          and rB.get("exec_state") == ec.EXEC_STATE_CONFIG_MISMATCH,
          repr(rB))
    check("attempts==1 (NO maxed): terminal por configuración, no por "
          "agotamiento",
          rB.get("attempts") == 1 and rB.get("max_attempts") == 2,
          repr((rB.get("attempts"), rB.get("max_attempts"))))
    fB = _fila(vidB["id"])
    check("job dead + exec_state CONFIG_MISMATCH en DB",
          fB["status"] == "dead"
          and fB["exec_state"] == ec.EXEC_STATE_CONFIG_MISMATCH
          and int(fB["attempts"] or 0) == 1, repr(fB)[:140])
    clsB = fa.clasificar(fB["error"] or "", "video")
    check("clasificación L CONFIG_MISMATCH HIGH / fuente execution_contract",
          clsB["clase"] == "L"
          and clsB["classification_confidence"] == "HIGH"
          and clsB["fuente_evidencia"] == "execution_contract"
          and clsB.get("alcance_causal") == "CONFIGURACION",
          repr(clsB)[:200])
    check("SIN prompt_adapted (P2 jamás en error de configuración)",
          fB["prompt_adapted"] is None)
    dec_L = fa.procesar_fallo_job(vidB["id"])
    check("procesar_fallo_job → L sin requeue (decision sin otorgado)",
          dec_L and dec_L.get("clase") == "L"
          and dec_L.get("reintentar") is False
          and not dec_L.get("otorgado"), repr(dec_L)[:140])
    check("el job PERMANECE dead aunque attempts < max (terminal)",
          _fila(vidB["id"])["status"] == "dead"
          and int(_fila(vidB["id"])["attempts"] or 0) == 1)

    print("── 9. §17-C variante CONFIG_UNSUPPORTED")
    _proyecto_video("p_uns", escenas=2, duracion=8)
    _PIDS.append("p_uns")
    fj.enqueue_project("p_uns")
    _drenar_imagenes("p_uns")
    vidC = fj.claim_next("w-states", pid="p_uns")
    rC = fj.fail(vidC["id"], vidC["job_token"],
                 "CONFIG_UNSUPPORTED: duration no expuesto")
    check("respuesta config_terminal True (CONFIG_UNSUPPORTED)",
          rC and rC.get("config_terminal") is True
          and rC.get("exec_state") == ec.EXEC_STATE_CONFIG_UNSUPPORTED,
          repr(rC))
    check("job dead CONFIG_UNSUPPORTED",
          _fila(vidC["id"])["status"] == "dead"
          and _fila(vidC["id"])["exec_state"]
          == ec.EXEC_STATE_CONFIG_UNSUPPORTED)
    check("ec.is_config_terminal reconoce los 2 estados creados",
          ec.is_config_terminal(_fila(vidB["id"])["exec_state"])
          and ec.is_config_terminal(_fila(vidC["id"])["exec_state"]))

    print("── 10. defensa del gate: complete/heartbeat sobre terminal "
          "CONFIG_* → 409")
    check("complete sobre job dead CONFIG_* → None",
          fj.complete(vidB["id"], vidB["job_token"],
                      _mp4_bytes(8.0)) is None)
    check("heartbeat sobre job dead CONFIG_* → None",
          fj.heartbeat(vidB["id"], vidB["job_token"]) is None)

    print("── 11. PROVIDER_FAILURE intacto (semántica clásica + gancho)")
    _proyecto_video("p_prov", escenas=2, duracion=8)
    _PIDS.append("p_prov")
    fj.enqueue_project("p_prov")
    _drenar_imagenes("p_prov")
    vidD = fj.claim_next("w-states", pid="p_prov")
    rD1 = fj.fail(vidD["id"], vidD["job_token"], "error tRPC 500")
    check("fail 1/2 → queued (attempts 1 < 2)",
          rD1 and rD1.get("status") == "queued"
          and rD1.get("attempts") == 1, repr(rD1))
    check("sin config_terminal ni adaptacion (no está dead)",
          "config_terminal" not in (rD1 or {})
          and "adaptacion" not in (rD1 or {}), repr(rD1))
    check("exec_state PROVIDER_FAILURE en DB",
          _fila(vidD["id"])["exec_state"] == ec.EXEC_STATE_PROVIDER_FAILURE)
    vidD2 = fj.claim_next("w-states", pid="p_prov")
    check("re-claim del mismo job", vidD2 and vidD2["id"] == vidD["id"])
    rD2 = fj.fail(vidD2["id"], vidD2["job_token"], "error tRPC 500")
    check("fail 2/2 → dead con gancho de adaptación en la respuesta",
          rD2 and rD2.get("status") == "dead"
          and isinstance(rD2.get("adaptacion"), dict), repr(rD2)[:160])
    check("gancho B: reencolar_sin_cambio OTORGADO (P1, sin P2)",
          rD2["adaptacion"].get("clase") == "B"
          and rD2["adaptacion"].get("accion") == "reencolar_sin_cambio"
          and rD2["adaptacion"].get("otorgado") is True,
          repr(rD2.get("adaptacion"))[:160])
    check("reencolado con attempts=max-1 (única oportunidad extra)",
          _fila(vidD["id"])["status"] == "queued"
          and int(_fila(vidD["id"])["attempts"] or 0) == 1
          and int(_fila(vidD["id"])["max_attempts"] or 2) == 2,
          repr(_fila(vidD["id"]))[:140])
    check("P1 reencolado SIN prompt_adapted",
          _fila(vidD["id"])["prompt_adapted"] is None)
    vidD3 = fj.claim_next("w-states", pid="p_prov")
    rD3 = fj.fail(vidD3["id"], vidD3["job_token"], "error tRPC 500")
    check("segundo dead → LÍMITE de grants: la capa NO reencola de nuevo",
          rD3 and rD3.get("status") == "dead"
          and rD3.get("adaptacion", {}).get("reintentar") is False
          and "LÍMITE" in rD3.get("adaptacion", {}).get("motivo", ""),
          repr(rD3.get("adaptacion"))[:200])
    check("el job queda dead definitivo (stays dead)",
          _fila(vidD["id"])["status"] == "dead")

    print("── 12. P1 inmutable en TODO el circuito")
    ok_p1, detalle = True, ""
    for pid in _PIDS:
        with db.connect() as con:
            rows = con.execute(
                "SELECT prompt, prompt_adapted, kind, scene_number "
                "FROM flow_jobs WHERE project_id=?", (pid,)).fetchall()
        for r in rows:
            if r["kind"] == "video" and not r["prompt"].startswith("P1 "):
                ok_p1 = False
                detalle = f"{pid} P1 alterado: {r['prompt'][:60]!r}"
            if r["prompt_adapted"] is not None:
                ok_p1 = False
                detalle = f"{pid} P2 espurio: {r['prompt_adapted'][:60]!r}"
    check("columna prompt intacta y prompt_adapted NULL en los 4 proyectos",
          ok_p1, detalle)
    specs_ok, specs_det = True, ""
    with db.connect() as con:
        for r in con.execute(
                "SELECT id, execution_spec FROM flow_jobs").fetchall():
            if not r["execution_spec"]:
                continue
            try:
                sp = json.loads(r["execution_spec"])
            except (TypeError, ValueError):
                sp = None
            if not isinstance(sp, dict) or sp.get("schema_version") != "1.0":
                specs_ok = False
                specs_det = f"spec alterado en {r['id']}"
    check("los specs sobreviven intactos a fails/completes/adaptación "
          "(columna execution_spec siempre schema 1.0)",
          specs_ok, specs_det)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
