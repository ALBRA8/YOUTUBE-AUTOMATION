#!/usr/bin/env python3
"""Batería FLOW START FRAME — FASE 1 (observación PASIVA de batchexecute).

FASE 1 del plan Google Flow Start Frame. ÚNICAMENTE observación pasiva:
  - NO implementa Start Frame; NO persiste mediaId en backend; NO toca
    execution_contract.py / flow_jobs.py / P1 / Production JSON / HANDS /
    AGENTE-GENERAL; NO automatiza DOM.

Cubre, EN HERMÉTICO (sin Chrome, sin red, sin Google Flow real):

  ①  WuwhI request → FLOW_RPC_EVIDENCE rpc_request con operation=
     MEDIA_GENERATION, videoModelKey (abra_i2v_6s), aspectRatio, count y los
     DOS campos Start Frame (inputFrames.firstFrame.mediaId y firstFrame.
     mediaId) como huellas fp de 12 hex — mediaId JAMÁS en crudo.
  ②  PASIVIDAD: init/body llegan INTACTOS al fetch original (misma
     referencia, sin props extra); ReadableStream jamás se consume.
  ③  Respuestas wrb.fr de eb1hJf / WuwhI / jwpduf / as29s: identificadores
     de lista blanca (videoId/jobId/toolId/...), estados y huellas mediaId.
  ④  rpcid desconocido → CERO observaciones.
  ⑤  Secretos (Authorization/cookie/SAPISID/api_key/token en query) jamás
     aparecen en ninguna emisión; URL siempre sin query.
  ⑥  Sin regresión: tRPC 200 → FLOW_BATCH_RESPONSE intacto; tRPC 403 →
     FLOW_NETWORK_EVIDENCE endpoint=trpc; batchexecute 403 → endpoint=
     batchexecute; batchexecute NO entra al canal tRPC.
  ⑦  Huella determinista (misma entrada → misma fp).
  ⑧  Canal page→extension: injector emite, content.js reenvía, background
     valida y guarda en anillo acotado; snapshot expone rpcObs.
  ⑨  Confidencialidad estructural: bridge.js SIN referencia al canal nuevo;
     backend SIN referencia (la observación NO sale de la extensión).
  ⑩  ALCANCE FASE 1: el diff toca SOLO extension/ y tests/ (guardía git);
     manifest >= 2.5.0 (2.6.0 desde F2); sintaxis JS OK.

Uso:  cd yt_automation_v2 && python3 tests/test_flow_batchexecute.py
      python3 -m pytest tests/test_flow_batchexecute.py -q
"""
import json
import subprocess
import sys
from pathlib import Path
from shutil import which

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
BACKEND = REPO / "backend"
HARNESS = Path(__file__).resolve().parent / "flow_batchexecute_mock.js"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node))

    print("── A. sintaxis del código real")
    for js in ("injector.js", "content.js", "background.js"):
        proc = subprocess.run([node, "--check", str(EXT / js)],
                              capture_output=True, text=True, timeout=60)
        check(f"sintaxis OK: {js}", proc.returncode == 0,
              (proc.stderr or "").strip()[:150])
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("sintaxis OK: flow_batchexecute_mock.js", proc_syn.returncode == 0,
          (proc_syn.stderr or "").strip()[:150])

    print("── B. arnés hermético (injector REAL en sandbox VM)")
    h = {}
    if node:
        proc = subprocess.run([node, str(HARNESS)], capture_output=True,
                              text=True, timeout=120)
        check("arnés corre sin error de ejecución", proc.returncode == 0,
              (proc.stderr or "")[-300:])
        try:
            h = json.loads(proc.stdout).get("checks", {})
            check("arnés produce JSON parseable", True)
        except Exception as e:  # noqa: BLE001
            check("arnés produce JSON parseable", False, str(e)[:150])
            h = {}

    print("── C. ① WuwhI request: MEDIA_GENERATION + Start Frame (fp, sin crudo)")
    w = h.get("wuwhi_request", {})
    check("C1. exactamente UNA observación rpc_request WuwhI", w.get("count") == 1, repr(w))
    check("C2. operation=MEDIA_GENERATION (sin inventar)", w.get("operation") == "MEDIA_GENERATION", repr(w.get("operation")))
    check("C3. videoModelKey=abra_i2v_6s", w.get("videoModelKey") == "abra_i2v_6s", repr(w.get("videoModelKey")))
    check("C4. aspectRatio=16:9", w.get("aspectRatio") == "16:9", repr(w.get("aspectRatio")))
    check("C5. count=1", w.get("countField") == 1, repr(w.get("countField")))
    check("C6. inputFrames.firstFrame.mediaId presente (fp 12 hex)",
          w.get("sfIn") is True, repr(w.get("sfIn")))
    check("C7. firstFrame.mediaId presente (fp 12 hex)",
          w.get("sfStandalone") is True, repr(w.get("sfStandalone")))
    check("C8. workflowId (id no sensible) capturado", w.get("workflowId") == "wf_forensic_001", repr(w.get("workflowId")))
    check("C9. URL sin query", w.get("urlNoQuery") is True, repr(w.get("urlNoQuery")))
    check("C10. método POST + ts", w.get("method") == "POST" and w.get("hasTs") is True, repr(w))
    check("C11. mediaId JAMÁS en crudo en ninguna emisión", w.get("noRawMediaId") is True, repr(w.get("noRawMediaId")))

    print("── D. ② pasividad (la página manda)")
    p = h.get("passivity", {})
    check("D1. init llega al fetch original por REFERENCIA", p.get("sameInitRef") is True, repr(p))
    check("D2. body idéntico (sin mutación)", p.get("sameBody") is True, repr(p))
    check("D3. init sin propiedades añadidas", p.get("noExtraProps") is True, repr(p))
    check("D4. la request llegó a destino (Flow funciona)", p.get("responseReached") is True, repr(p))
    s = h.get("stream_body", {})
    check("D5. ReadableStream NUNCA se consume", s.get("notConsumed") is True, repr(s))
    check("D6. stream + rpcid en URL → obs mínima sin estructura", s.get("minimalObs") is True, repr(s))

    print("── E. ③ respuestas wrb.fr de los 4 rpcids")
    e1 = h.get("eb1hjf_response", {})
    check("E1. eb1hJf: videoId", e1.get("videoId") == "vid_forensic_abc123", repr(e1.get("videoId")))
    check("E2. eb1hJf: toolId", e1.get("toolId") == "tool_77", repr(e1.get("toolId")))
    check("E3. eb1hJf: mediaId como huella única", e1.get("mediaFp") is True, repr(e1.get("mediaFp")))
    check("E4. eb1hJf: estado (status=DONE)", e1.get("states") is True, repr(e1.get("states")))
    check("E5. eb1hJf: mediaId jamás en crudo", e1.get("noRawMediaId") is True, repr(e1.get("noRawMediaId")))
    e2 = h.get("wuwhi_response", {})
    check("E6. WuwhI resp: jobId + estado", e2.get("jobId") == "job_990" and e2.get("state") == "GENERATING", repr(e2))
    check("E7. WuwhI resp: mediaId como huella", e2.get("mediaFp") is True, repr(e2.get("mediaFp")))
    e3 = h.get("jwpduf_response", {})
    check("E8. jwpduf: jobId + estado", e3.get("jobId") == "job_jw_1" and e3.get("status") == "RUNNING", repr(e3))
    e4 = h.get("as29s_response", {})
    check("E9. as29s: videoId + estado", e4.get("videoId") == "vid_as29_1" and e4.get("state") == "COMPLETED", repr(e4))

    print("── F. ④ rpcid desconocido → cero ruido")
    u = h.get("unknown_rpcid", {})
    check("F1. FdrFJe → CERO observaciones", u.get("rpcEvents") == 0, repr(u))

    print("── G. ⑤ secretos jamás")
    g = h.get("secrets_never", {})
    check("G1. Bearer ausente", g.get("noBearer") is True, repr(g))
    check("G2. SAPISID/cookie ausente", g.get("noSapisid") is True, repr(g))
    check("G3. api_key ausente", g.get("noApiKey") is True, repr(g))
    check("G4. solo huella de mediaId", g.get("mediaFpOnly") is True, repr(g))
    q = h.get("url_query_stripped", {})
    check("G5. token de query fuera de la URL capturada", q.get("noToken") is True, repr(q))
    x = h.get("xhr_batchexecute", {})
    check("G6. XHR: request WuwhI con Start Frame", x.get("request") is True, repr(x))
    check("G7. XHR: respuesta eb1hJf", x.get("response") is True, repr(x))
    check("G8. XHR: mediaId jamás en crudo", x.get("noRawMediaId") is True, repr(x.get("noRawMediaId")))

    print("── H. ⑥ sin regresión (canales preexistentes intactos)")
    t = h.get("trpc_regression", {})
    check("H1. tRPC 200 → FLOW_BATCH_RESPONSE intacto", t.get("batchEmit") is True, repr(t))
    check("H2. mediaId de tRPC sigue llegando al background", t.get("mediaIdInside") is True, repr(t))
    check("H3. tRPC NO genera observaciones rpc", t.get("zeroRpcEvents") is True, repr(t))
    t4 = h.get("trpc_403", {})
    check("H4. tRPC 403 → evidencia endpoint=trpc", t4.get("status") == 403 and t4.get("endpoint") == "trpc", repr(t4))
    b4 = h.get("batchexec_403", {})
    check("H5. batchexecute 403 → evidencia endpoint=batchexecute", b4.get("status") == 403 and b4.get("endpoint") == "batchexecute", repr(b4))

    print("── I. ⑦ huella determinista")
    f = h.get("fingerprint", {})
    check("I1. fp presente", f.get("present") is True, repr(f))
    check("I2. misma entrada → misma fp", f.get("deterministic") is True, repr(f))
    check("I3. fp de 12 hex", f.get("len12") is True, repr(f))
    m = h.get("mirror", {})
    check("I4. espejo __FLOW_RPC_OBS__ = emisiones (prueba manual)", m.get("sameAsEmitted") is True, repr(m))

    print("── J. ⑧ canal page→extension→background")
    inj = (EXT / "injector.js").read_text(encoding="utf-8")
    con = (EXT / "content.js").read_text(encoding="utf-8")
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    check("J1. injector emite FLOW_RPC_EVIDENCE", "FLOW_RPC_EVIDENCE" in inj)
    check("J2. content.js reenvía FLOW_RPC_EVIDENCE (aduana existente)",
          "FLOW_RPC_EVIDENCE" in con and "chrome.runtime.sendMessage({ type: 'FLOW_RPC_EVIDENCE'" in con)
    check("J3. background atiende FLOW_RPC_EVIDENCE en su router",
          "case 'FLOW_RPC_EVIDENCE':" in bg and "handleRpcEvidence(msg)" in bg)
    check("J4. anillo acotado (RPC_OBS_MAX = 50)", "const RPC_OBS_MAX = 50" in bg)
    check("J5. rpcObservations persiste en sesión y se hidrata defensivo",
          "rpcObservations," in bg and "rpcObservations = Array.isArray(o.rpcObservations)" in bg)
    check("J6. snapshot expone rpcObs (inspección GET_STATE)",
          "rpcObs: {" in bg)
    check("J7. resetAll limpia rpcObservations", "rpcObservations = [];" in bg)
    check("J8. validación estricta de rpcid en background",
          "/^(eb1hJf|WuwhI|jwpduf|as29s)$/.test(rpcid)" in bg)

    print("── K. ⑨ confidencialidad estructural (NADA sale de la extensión)")
    bridge = (EXT / "bridge.js").read_text(encoding="utf-8")
    check("K1. bridge.js SIN referencia al canal F1 (no viaja al backend)",
          "FLOW_RPC_EVIDENCE" not in bridge and "rpcObservations" not in bridge)
    leaks = []
    for py in sorted(BACKEND.rglob("*.py")):
        try:
            if "FLOW_RPC_EVIDENCE" in py.read_text(encoding="utf-8", errors="ignore"):
                leaks.append(str(py.relative_to(REPO)))
        except OSError:
            pass
    check("K2. backend SIN referencia al canal F1 (cero persistencia)",
          not leaks, ",".join(leaks[:3]))

    print("── L. ⑩ alcance FASE 1 (guardías de prohibiciones)")
    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("L1. manifest 2.6.0 (bump minor [flow-start-frame F2] parser anidado)",
          mf.get("version") == "2.6.0", mf.get("version"))
    forbidden = ("execution_contract", "flow_jobs", "production_json",
                 "hands", "agent.py", "harness")
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                             cwd=str(REPO), capture_output=True, text=True)
    files = [f.strip() for f in (changed.stdout or "").splitlines() if f.strip()]
    bad = [f for f in files if any(b in f for b in forbidden)
           and not f.startswith(("extension/", "tests/"))]
    check("L2. diff SOLO extension/ + tests/ (sin backend/contracts/HANDS/P1)",
          not bad, ",".join(bad[:5]))
    ok_paths = all(f.startswith(("extension/", "tests/")) for f in files)
    check("L3. archivos modificados dentro del alcance declarado",
          ok_paths, ",".join(files[:8]))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
