#!/usr/bin/env python3
"""Batería EXECUTION CONTRACT V1.0 — unidad del contrato (sin DB, sin red).

Cubre el núcleo determinista de backend/services/execution_contract.py:

  §1  build_execution_spec — tercera capa del contrato (P1 jamás tocado):
      duration transportada (video) / None honesta (imagen), aspect derivado
      del formato del PROYECTO (short→9:16, long→16:9, None/unknown→null SIN
      inventar), outputs=1 (hecho del transporte), model/audio/resolution
      null+not-required, references transportadas tal cual, compatibility_policy
      (allow_inherited_state false / generate_requires_verified true /
      retry_on_config_error false), verification (ffprobe, tolerance 0 +
      TRANSPORT_EPSILON_S 0.25, aspect rel 0.02, audio register_only,
      outputs transport).
  §6  config_gate — matriz de decisiones: sin evidencia → CONFIG_UNVERIFIABLE;
      VERIFIED con normalización ('8s' == 8) → ALLOW_GENERATE; MISMATCH,
      UNSUPPORTED (prioridad), outputs MISMATCH bloquea, outputs/audio
      REGISTERED no bloquean, required-con-null → UNVERIFIABLE sin crash,
      model requested null jamás bloquea.
  §13 validate_asset_contract — duración |d-r| <= tol + 0.25 (8.02 OK,
      8.3 violación, 5.0 violación), aspect ratio rel 2% (1920x1080 en
      spec 9:16 → violación), probe None → UNVERIFIABLE, audio REGISTERED
      (has_audio False NO bloquea), references UNVERIFIABLE honesto sin
      romper el veredicto global, outputs_count 2 vs 1 → violación.
  §13 REAL  probe_asset con ffprobe sobre MP4 reales (ffmpeg lavfi) +
      validación contractual real (8s OK / 5s violación de duration).
  §9  máquina de estados: progress_allowed (adelante sí, atrás jamás,
      terminal no rebobina, terminal alcanzable desde cualquier no-terminal),
      is_config_terminal (3 CONFIG_*), spec_summary.
  §10 prefijos estructurales para fail()/clasificar (ASSET_INVALID / CONFIG_*).

Determinista: sin Flow real, sin red, sin credenciales; MP4 local via ffmpeg.

Uso:  cd yt_automation_v2 && python3 tests/test_execution_contract.py
      python3 -m pytest tests/test_execution_contract.py -q
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# ── parcheo ANTES de importar: rutas a tmp (patrón de la casa; esta batería
#    no abre DB, pero blindamos cero escrituras al repo) ──────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="execution_contract_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

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


def _mp4_bytes(dur=1.0, size="64x64", con_audio=True) -> bytes:
    """MP4 real (H.264+AAC) con el patrón EXACTO de test_flow_video_v3
    (lavfi color + sine + -shortest) + -t para duración determinista
    (-shortest solo puede arrastrar jitter de entrelazado del muxer).
    Determinista, local, sin red."""
    out = _TMP / f"clip_{dur}_{size.replace(':', 'x')}_{int(con_audio)}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"color=c=0x2288CC:s={size}:d={dur}"]
    if con_audio:
        cmd += ["-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=44100", "-shortest"]
    cmd += ["-t", str(dur), "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    return out.read_bytes()


_REF = [{"kind": "image", "url": "https://example.com/r.png"}]
_ENTRADA = {"scene_number": 1, "duration": 8, "references": list(_REF),
            "title": "Escena 1"}


def main() -> int:
    print("═══ EXECUTION CONTRACT V1.0 · núcleo determinista ═══")

    # ── §1 spec builder ────────────────────────────────────────────────────
    print("── 1. build_execution_spec (video short)")
    spec = ec.build_execution_spec(_ENTRADA, kind="video",
                                   project_format="short")
    check("schema_version 1.0", spec.get("schema_version") == "1.0",
          repr(spec.get("schema_version")))
    check("duration requested 8 / required / tolerance 0",
          spec["duration"] == {"requested": 8, "required": True,
                               "tolerance_seconds": 0},
          repr(spec.get("duration")))
    check("aspect 9:16 derivado de short y required",
          spec["aspect_ratio"] == {"requested": "9:16", "required": True},
          repr(spec.get("aspect_ratio")))
    check("outputs 1 required (hecho del transporte)",
          spec["outputs"] == {"requested": 1, "required": True},
          repr(spec.get("outputs")))
    check("model/audio/resolution null + not-required (no invención)",
          spec["model"] == {"requested": None, "required": False}
          and spec["audio"] == {"requested": None, "required": False}
          and spec["resolution"] == {"requested": None, "required": False},
          repr((spec.get("model"), spec.get("audio"), spec.get("resolution"))))
    check("references transportadas verbatim",
          spec.get("references") == _REF, repr(spec.get("references")))
    check("compatibility_policy §6/§10",
          spec.get("compatibility_policy") == {
              "allow_inherited_state": False,
              "generate_requires_verified": True,
              "retry_on_config_error": False},
          repr(spec.get("compatibility_policy")))
    ver = spec.get("verification") or {}
    check("verification duration ffprobe tol 0 + epsilon 0.25",
          ver.get("duration", {}).get("method") == "ffprobe"
          and ver["duration"].get("tolerance_seconds") == 0
          and ver["duration"].get("transport_epsilon_s")
          == ec.TRANSPORT_EPSILON_S == 0.25,
          repr(ver.get("duration")))
    check("verification aspect ffprobe rel 0.02",
          ver.get("aspect_ratio", {}).get("method") == "ffprobe"
          and ver["aspect_ratio"].get("relative_tolerance")
          == ec.ASPECT_REL_TOLERANCE == 0.02,
          repr(ver.get("aspect_ratio")))
    check("verification audio register_only / outputs transport",
          ver.get("audio", {}).get("gate") == "register_only"
          and ver.get("outputs", {}).get("method") == "transport",
          repr((ver.get("audio"), ver.get("outputs"))))
    check("start_frame/end_frame sin contrato → None",
          spec.get("start_frame") is None and spec.get("end_frame") is None)
    raw = json.dumps(spec, ensure_ascii=False)
    check("P1 jamás tocado: el spec NO contiene campos de prompt",
          "prompt" not in raw.lower(), raw[:120])

    print("── 1b. variantes del spec (duración y formato)")
    spec6 = ec.build_execution_spec({**_ENTRADA, "duration": 6},
                                    kind="video", project_format="short")
    check("beat 6 → duration 6",
          spec6["duration"]["requested"] == 6
          and spec6["duration"]["required"] is True,
          repr(spec6["duration"]))
    specimg = ec.build_execution_spec(_ENTRADA, kind="image",
                                      project_format="short")
    check("kind image → duration None/not-required",
          specimg["duration"] == {"requested": None, "required": False,
                                  "tolerance_seconds": 0},
          repr(specimg["duration"]))
    speclong = ec.build_execution_spec(_ENTRADA, kind="video",
                                       project_format="long")
    check("format long → aspect 16:9",
          speclong["aspect_ratio"]["requested"] == "16:9"
          and speclong["aspect_ratio"]["required"] is True,
          repr(speclong["aspect_ratio"]))
    specnone = ec.build_execution_spec(_ENTRADA, kind="video",
                                       project_format=None)
    check("format None → aspect null + not-required (NO se inventa)",
          specnone["aspect_ratio"] == {"requested": None, "required": False},
          repr(specnone["aspect_ratio"]))
    specunk = ec.build_execution_spec(_ENTRADA, kind="video",
                                      project_format="cuadrado")
    check("format desconocido ('cuadrado') → aspect null + not-required",
          specunk["aspect_ratio"] == {"requested": None, "required": False},
          repr(specunk["aspect_ratio"]))
    specsd = ec.build_execution_spec({"scene_number": 1}, kind="video",
                                     project_format="short")
    check("escena video SIN duración → requested None required False "
          "(honesto; build_script_json garantiza duración upstream)",
          specsd["duration"] == {"requested": None, "required": False,
                                 "tolerance_seconds": 0},
          repr(specsd["duration"]))
    specnr = ec.build_execution_spec({"scene_number": 1},
                                     kind="video", project_format="short")
    check("sin references en la entrada → [] (no None)",
          specnr.get("references") == [], repr(specnr.get("references")))

    # ── §6 gate de configuración ──────────────────────────────────────────
    print("── 2. config_gate (matriz §6)")
    g = ec.config_gate(spec, None, None)
    check("sin evidencia → CONFIG_UNVERIFIABLE (jamás estado heredado)",
          g["decision"] == ec.CONFIG_UNVERIFIABLE, repr(g["decision"]))
    check("detail nombra duration CONFIG_UNVERIFIABLE",
          "duration" in g.get("detail", "")
          and "CONFIG_UNVERIFIABLE" in g.get("detail", ""),
          repr(g.get("detail"))[:140])
    ok_res = {"duration": {"verdict": "VERIFIED", "observed": "8s",
                           "configured": True},
              "aspect_ratio": {"verdict": "VERIFIED", "observed": "9:16",
                               "configured": True}}
    g2 = ec.config_gate(spec, {"duration": {"supported": True},
                               "aspect_ratio": {"supported": True}}, ok_res)
    check("VERIFIED '8s' + '9:16' → ALLOW_GENERATE (normalización '8s'==8)",
          g2["decision"] == ec.ALLOW_GENERATE, repr(g2["decision"]))
    check("gate registra observed sin bloquear",
          g2["control_results"]["duration"]["observed"] == "8s"
          and g2["control_results"]["duration"]["verdict"] == "VERIFIED",
          repr(g2["control_results"].get("duration")))
    check("model requested null → VERIFIED sin bloquear (jamás exige)",
          g2["control_results"]["model"]["verdict"] == "VERIFIED",
          repr(g2["control_results"].get("model")))
    g3 = ec.config_gate(spec, {}, {"duration": {"verdict": "MISMATCH",
                                                "observed": "5s"},
                                   "aspect_ratio": {"verdict": "VERIFIED",
                                                    "observed": "9:16"}})
    check("duration MISMATCH → CONFIG_MISMATCH",
          g3["decision"] == ec.CONFIG_MISMATCH, repr(g3["decision"]))
    g4 = ec.config_gate(spec, {}, {"duration": {"verdict": "UNSUPPORTED"},
                                   "aspect_ratio": {"verdict": "MISMATCH",
                                                    "observed": "1:1"}})
    check("UNSUPPORTED tiene prioridad sobre MISMATCH",
          g4["decision"] == ec.CONFIG_UNSUPPORTED, repr(g4["decision"]))
    g5 = ec.config_gate(spec, {}, {"duration": {"verdict": "UNVERIFIABLE"},
                                   "aspect_ratio": {"verdict": "VERIFIED",
                                                    "observed": "9:16"}})
    check("UNVERIFIABLE explícito → CONFIG_UNVERIFIABLE",
          g5["decision"] == ec.CONFIG_UNVERIFIABLE, repr(g5["decision"]))
    g6 = ec.config_gate(spec, {}, {**ok_res,
                                   "outputs": {"verdict": "MISMATCH",
                                               "observed": 2}})
    check("outputs MISMATCH (evidencia en contra) → CONFIG_MISMATCH",
          g6["decision"] == ec.CONFIG_MISMATCH, repr(g6["decision"]))
    g7 = ec.config_gate(spec, {}, {**ok_res,
                                   "audio": {"verdict": "MISMATCH",
                                             "observed": "silencioso"}})
    check("audio requested null → JAMÁS gatea (sin exigencia inventada; "
          "evidencia registrada, decisión intacta)",
          g7["decision"] == ec.ALLOW_GENERATE
          and g7["control_results"]["audio"]["verdict"] == "VERIFIED",
          repr(g7["control_results"].get("audio")))
    g8 = ec.config_gate(spec, {}, ok_res)
    check("outputs sin resultado → REGISTERED (transport), ALLOW_GENERATE",
          g8["decision"] == ec.ALLOW_GENERATE
          and g8["control_results"]["outputs"]["verdict"] == "REGISTERED",
          repr(g8["control_results"].get("outputs")))
    spec_rn = json.loads(json.dumps(spec))
    spec_rn["aspect_ratio"] = {"requested": None, "required": True}
    g9 = ec.config_gate(spec_rn, {}, ok_res)
    check("required con requested null → control UNVERIFIABLE honesto, "
          "sin crash y sin bloqueo falso (no ocurre por construcción)",
          g9["control_results"]["aspect_ratio"]["verdict"] == "UNVERIFIABLE"
          and g9["decision"] == ec.ALLOW_GENERATE,
          repr((g9["decision"], g9["control_results"].get("aspect_ratio"))))
    check("verdicts por defecto: sin resultado → UNVERIFIABLE",
          ec.config_gate(spec, {}, {})["decision"] == ec.CONFIG_UNVERIFIABLE)

    # ── §6.1 gate v1.1 — allow_inherited_state + required_gate_controls ──
    print("── 2b. config_gate v1.1 (§7.1: heredado ≠ configuración propia)")
    heredado = {"duration": {"verdict": "VERIFIED", "observed": 8},
                "aspect_ratio": {"verdict": "VERIFIED", "observed": "9:16",
                                 "configured": True}}
    gi = ec.config_gate(spec, {}, heredado)
    check("TEST 9: VERIFIED sin configured + policy false → "
          "CONFIG_UNVERIFIABLE (heredado jamás aceptado)",
          gi["decision"] == ec.CONFIG_UNVERIFIABLE
          and "allow_inherited_state" in gi.get("detail", ""),
          repr(gi)[:180])
    propia = {"duration": {"verdict": "VERIFIED", "observed": 8,
                           "configured": True},
              "aspect_ratio": {"verdict": "VERIFIED", "observed": "9:16",
                               "configured": True}}
    gp = ec.config_gate(spec, {}, propia)
    check("TEST 9: configured=True (set+relectura propios) → ALLOW_GENERATE",
          gp["decision"] == ec.ALLOW_GENERATE, repr(gp["decision"]))
    spec_pol = json.loads(json.dumps(spec))
    spec_pol["compatibility_policy"]["allow_inherited_state"] = True
    gh = ec.config_gate(spec_pol, {}, heredado)
    check("allow_inherited_state=true: heredado EN el valor pedido → ALLOW "
          "(política explícita, no silenciosa)",
          gh["decision"] == ec.ALLOW_GENERATE, repr(gh["decision"]))
    check("TEST 9: capa mecánica declara configured en el resultado "
          "(trazabilidad heredado vs propio)",
          gp["control_results"]["duration"].get("verdict") == "VERIFIED",
          repr(gp["control_results"].get("duration")))
    rgc = ec.required_gate_controls(spec)
    check("required_gate_controls: duration+aspect ffprobe requeridos",
          rgc == ["duration", "aspect_ratio"], repr(rgc))
    check("required_gate_controls: outputs (transport) y audio "
          "(register_only) NO exigen gate pre-generación",
          "outputs" not in rgc and "audio" not in rgc, repr(rgc))
    check("required_gate_controls: spec no-dict → [] (honesto)",
          ec.required_gate_controls(None) == []
          and ec.required_gate_controls("x") == [])
    check("§7.1: EXEC_STATE_WATCHDOG existe y NO es terminal de máquina",
          ec.EXEC_STATE_WATCHDOG == "FLOW_WATCHDOG_TIMEOUT"
          and ec.EXEC_STATE_WATCHDOG not in ec.TERMINAL_EXEC_STATES)

    # ── §13 validación contractual (sintética) ────────────────────────────
    print("── 3. validate_asset_contract (sintético §13)")
    r_ok = ec.validate_asset_contract(
        spec, actual={"duration": 8.02, "width": 1080, "height": 1920,
                      "has_audio": True},
        observed={"duration": "8s", "aspect_ratio": "9:16"}, outputs_count=1)
    check("8.02s 1080x1920 → CONTRACT_OK",
          r_ok["verdict"] == ec.CONTRACT_OK, repr(r_ok["summary"]))
    check("checks duration/aspect VERIFIED con observed_flow registrado",
          r_ok["checks"]["duration"]["verdict"] == "VERIFIED"
          and r_ok["checks"]["aspect_ratio"]["verdict"] == "VERIFIED"
          and r_ok["checks"]["duration"]["observed_flow"] == "8s",
          repr(r_ok["checks"]["duration"]))
    r_e = ec.validate_asset_contract(
        spec, actual={"duration": 8.3, "width": 1080, "height": 1920,
                      "has_audio": True})
    check("8.3s → CONTRACT_VIOLATION (tolerance 0 + epsilon 0.25)",
          r_e["verdict"] == ec.CONTRACT_VIOLATION
          and "duration" in r_e["violations"][0],
          repr(r_e["summary"]))
    r_5 = ec.validate_asset_contract(
        spec, actual={"duration": 5.0, "width": 1080, "height": 1920,
                      "has_audio": True})
    check("5.0s vs 8 → CONTRACT_VIOLATION duration",
          r_5["verdict"] == ec.CONTRACT_VIOLATION
          and "duration" in r_5["violations"][0], repr(r_5["summary"]))
    r_a = ec.validate_asset_contract(
        spec, actual={"duration": 8.0, "width": 1920, "height": 1080,
                      "has_audio": True})
    check("8s 1920x1080 vs 9:16 → CONTRACT_VIOLATION aspect",
          r_a["verdict"] == ec.CONTRACT_VIOLATION
          and any("aspect_ratio" in v for v in r_a["violations"]),
          repr(r_a["summary"]))
    r_n = ec.validate_asset_contract(
        spec, actual={"duration": None, "width": 1080, "height": 1920,
                      "has_audio": False})
    check("duration None → CONTRACT_UNVERIFIABLE (probe 0/None honesto)",
          r_n["verdict"] == ec.CONTRACT_UNVERIFIABLE
          and "duration" in r_n["unverifiable"], repr(r_n["summary"]))
    check("has_audio False → audio REGISTERED (register_only, NO gatea)",
          r_ok["checks"]["audio"]["verdict"] == "REGISTERED"
          and r_n["checks"]["audio"]["asset_native_audio"] is False
          and r_n["checks"]["audio"]["verdict"] == "REGISTERED",
          repr(r_n["checks"]["audio"]))
    r_o = ec.validate_asset_contract(
        spec, actual={"duration": 8.0, "width": 1080, "height": 1920,
                      "has_audio": True}, outputs_count=2)
    check("outputs_count 2 vs requested 1 → CONTRACT_VIOLATION outputs",
          r_o["verdict"] == ec.CONTRACT_VIOLATION
          and any("outputs" in v for v in r_o["violations"]),
          repr(r_o["summary"]))
    spec_ref = ec.build_execution_spec(_ENTRADA, kind="video",
                                       project_format=None)
    r_ref = ec.validate_asset_contract(
        spec_ref, actual={"duration": 8.0, "width": 1080, "height": 1920,
                          "has_audio": True})
    check("references no vacías → check UNVERIFIABLE registrado HONESTO "
          "sin romper el veredicto global (references jamás gatean)",
          r_ref["verdict"] == ec.CONTRACT_OK
          and r_ref["checks"]["references"]["verdict"] == "UNVERIFIABLE"
          and r_ref["checks"]["references"]["requested"] == 1,
          repr(r_ref["checks"]["references"]))
    check("contract_result JSON-serializable (se persiste en flow_jobs)",
          json.loads(json.dumps(r_ok))["verdict"] == ec.CONTRACT_OK)
    check("resumen CONTRACT_OK literal",
          r_ok["summary"] == "CONTRACT_OK", repr(r_ok["summary"]))

    # ── §13 REAL: ffprobe sobre MP4 reales ────────────────────────────────
    print("── 4. probe_asset REAL (ffmpeg + ffprobe)")
    try:
        clip8 = _mp4_bytes(8.0)
        clip5 = _mp4_bytes(5.0)
        clips_ok = True
    except Exception as exc:  # pragma: no cover — entorno sin ffmpeg
        clips_ok = False
        check("ffmpeg disponible para MP4 reales", False, repr(exc))
    if clips_ok:
        p8 = ec.probe_asset(_TMP / "clip_8.0_64x64_1.mp4")
        check("probe 8s: duration ≈ 8 (±0.25 epsilon de transporte)",
              p8["duration"] is not None
              and abs(p8["duration"] - 8.0) <= ec.TRANSPORT_EPSILON_S,
              repr(p8))
        check("probe 8s: width/height 64x64", p8["width"] == 64
              and p8["height"] == 64, repr(p8))
        check("probe 8s: has_audio es bool (pista sine detectada)",
              isinstance(p8["has_audio"], bool) and p8["has_audio"] is True,
              repr(p8))
        p5 = ec.probe_asset(_TMP / "clip_5.0_64x64_1.mp4")
        check("probe 5s: duration ≈ 5",
              p5["duration"] is not None
              and abs(p5["duration"] - 5.0) <= ec.TRANSPORT_EPSILON_S,
              repr(p5))
        check("probe de archivo inexistente → todo None (UNVERIFIABLE, no 0)",
              ec.probe_asset(_TMP / "fantasma.mp4") == {
                  "duration": None, "width": None, "height": None,
                  "has_audio": None},
              repr(ec.probe_asset(_TMP / "fantasma.mp4")))
        # validación contractual REAL: clip 9:16 de 8s vs spec short(8)
        clip916 = _mp4_bytes(8.0, size="720x1280")
        p916 = ec.probe_asset(_TMP / "clip_8.0_720x1280_1.mp4")
        r_real = ec.validate_asset_contract(spec, actual=p916)
        check("REAL: clip 8s 9:16 vs spec(8, short) → CONTRACT_OK",
              r_real["verdict"] == ec.CONTRACT_OK, repr(r_real["summary"]))
        r_bad = ec.validate_asset_contract(
            spec, actual=ec.probe_asset(_TMP / "clip_5.0_64x64_1.mp4"),
            outputs_count=1)
        check("REAL: clip 5s (64x64) vs spec(8, short) → CONTRACT_VIOLATION "
              "con violations[0] 'duration'",
              r_bad["verdict"] == ec.CONTRACT_VIOLATION
              and "duration" in r_bad["violations"][0],
              repr(r_bad["summary"]))

    # ── §9 máquina de estados ─────────────────────────────────────────────
    print("── 5. máquina de estados finos (§9)")
    check("QUEUED→CLAIMED ok",
          ec.progress_allowed(ec.EXEC_STATE_QUEUED, ec.EXEC_STATE_CLAIMED))
    check("adelante: CLAIMED→FLOW_TAB_READY ok",
          ec.progress_allowed("CLAIMED", "FLOW_TAB_READY"))
    check("adelante: CAPABILITIES_CAPTURED→CONTROLS_CONFIGURED ok",
          ec.progress_allowed("CAPABILITIES_CAPTURED", "CONTROLS_CONFIGURED"))
    check("salto adelante permitido (evidencia tardía de un intento)",
          ec.progress_allowed("CAPABILITIES_CAPTURED",
                              "GENERATION_SUBMITTED"))
    check("rewind GENERATION_SUBMITTED→CAPABILITIES_CAPTURED rechazado",
          not ec.progress_allowed("GENERATION_SUBMITTED",
                                  "CAPABILITIES_CAPTURED"))
    check("rewind CLAIMED→QUEUED rechazado (jamás rebobina)",
          not ec.progress_allowed("CLAIMED", "QUEUED"))
    check("terminal CONFIG_MISMATCH no avanza a nada",
          not ec.progress_allowed("CONFIG_MISMATCH", "FLOW_TAB_READY"))
    check("terminal ASSET_INVALID no llega a DONE",
          not ec.progress_allowed("ASSET_INVALID", "DONE"))
    check("target terminal alcanzable desde no-terminal",
          ec.progress_allowed("CLAIMED", "CONFIG_MISMATCH")
          and ec.progress_allowed(None, "PROVIDER_FAILURE"))
    check("bogus 'ESTADO_FANTASMA' rechazado",
          not ec.progress_allowed("CLAIMED", "ESTADO_FANTASMA"))
    check("None→QUEUED ok (estado inicial)",
          ec.progress_allowed(None, ec.EXEC_STATE_QUEUED))
    check("is_config_terminal: exactamente los 3 CONFIG_*",
          all(ec.is_config_terminal(s) for s in
              ("CONFIG_UNSUPPORTED", "CONFIG_UNVERIFIABLE",
               "CONFIG_MISMATCH"))
          and not any(ec.is_config_terminal(s) for s in
                      ("PROVIDER_FAILURE", "ASSET_INVALID", "DEAD",
                       "CONTRACT_VALIDATED", "CLAIMED", None)))
    check("TERMINAL_EXEC_STATES incluye los 6 terminales",
          ec.TERMINAL_EXEC_STATES == {
              "CONFIG_UNSUPPORTED", "CONFIG_UNVERIFIABLE", "CONFIG_MISMATCH",
              "PROVIDER_FAILURE", "ASSET_INVALID", "DEAD"},
          repr(ec.TERMINAL_EXEC_STATES))
    check("spec_summary contiene la duración pedida",
          "duration=8" in ec.spec_summary(spec)
          and "aspect=9:16" in ec.spec_summary(spec)
          and "outputs=1" in ec.spec_summary(spec),
          repr(ec.spec_summary(spec)))
    check("spec_summary de None honesto",
          ec.spec_summary(None) == "execution_spec: null")

    # ── §10 prefijos estructurales ────────────────────────────────────────
    print("── 6. prefijos estructurales para fail()/clasificar")
    pfx = ec.contract_error_prefix(r_bad)
    check("contract_error_prefix empieza 'ASSET_INVALID: '",
          pfx.startswith("ASSET_INVALID: "), repr(pfx))
    check("contract_error_prefix lleva summary + verdict",
          "CONTRACT_VIOLATION" in pfx and pfx.endswith("[CONTRACT_VIOLATION]"),
          repr(pfx))
    check("gate_error_prefix 'CONFIG_MISMATCH: '",
          ec.gate_error_prefix(ec.CONFIG_MISMATCH) == "CONFIG_MISMATCH: ",
          repr(ec.gate_error_prefix(ec.CONFIG_MISMATCH)))
    check("gate_error_prefix/contract_error_prefix son reconocibles por "
          "flow_adaptation (startswith de _PREFIJOS_CONTRACTO)",
          pfx.startswith("ASSET_INVALID:")
          and ec.gate_error_prefix("CONFIG_UNSUPPORTED").startswith(
              "CONFIG_UNSUPPORTED:"))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
