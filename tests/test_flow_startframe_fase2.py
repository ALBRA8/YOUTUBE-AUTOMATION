#!/usr/bin/env python3
"""Batería FLOW START FRAME — FASE 2 (parser ANIDADO de batchexecute).

FASE 2 del plan Google Flow Start Frame. ÚNICAMENTE observar y parsear
correctamente el protocolo REAL: NO implementa Start Frame, NO persiste
mediaId, NO toca production_json.py / P1 / Creative Engine /
execution_contract.py / flow_jobs.py / bridge.js / orchestrator / HANDS /
AGENTE-GENERAL, NO recrea WuwhI desde Python, NO hace llamadas HTTP a
Google Flow, NO cambia el protocolo de observación F1.

Causa del bug corregido: MEDIA_GENERATION_SETTINGS trae su VAL como
STRING con JSON dentro (formato LIVE) — hay que JSON.parse de segundo
nivel. F1 buscaba videoModelKey/aspectRatio/count sobre la estructura
externa → nulls.

Los 10 TESTS obligatorios (T1..T10) + extras, EN HERMÉTICO (sin Chrome,
sin red, sin Google Flow real), sobre el código REAL de injector.js:

  T1  LIVE nested settings → operation, videoModelKey, aspectRatio (num),
      count, startFrame {mediaIdPresent, fingerprint}, ids por huella.
  T2  mismo mediaId en inputFrames.firstFrame y firstFrame → misma fp.
  T3  cropCoordinates de AMBAS rutas (top/left/bottom/right exactos).
  T4  sin endFrame → generación NO inválida (nada marca inválido).
  T5  VAL malformado → evidencia parcial diagnóstica; observer NUNCA roto.
  T6  WuwhI sin MEDIA_GENERATION → sin falso positivo.
  T7  RPC distinto → jamás operation=MEDIA_GENERATION (cero eventos).
  T8  secrets regression: f.sid/Authorization/cookie/signed URL/mediaId
      crudo JAMÁS en evidencia; huella sí.
  T9  ReadableStream jamás se consume; fallback actual intacto.
  T10 backward compat: batería F1 completa PASS + formato objeto F1.

Uso:  cd yt_automation_v2 && python3 tests/test_flow_startframe_fase2.py
      python3 -m pytest tests/test_flow_startframe_fase2.py -q
"""
import json
import subprocess
import sys
from pathlib import Path
from shutil import which

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
BACKEND = REPO / "backend"
HARNESS = Path(__file__).resolve().parent / "flow_batchexecute_fase2_mock.js"
F1_BATTERY = Path(__file__).resolve().parent / "test_flow_batchexecute.py"

OK, FAIL = 0, 0

# campos del mock con valor NO booleano legítimo (se validan granulares
# en las secciones B..M) y campos cuyo False ES el resultado esperado
NON_BOOL_OK = {"operation", "count", "countField", "aspectRatio",
               "fingerprint", "videoModelKey", "workflowId"}
NEG_FALSE = {"promptContentLeaked", "noRawMediaId", "noEndFrameKeys",
             "brokenJsonNeverInEvidence", "noFsId", "noBearer", "noCookie",
             "noSignedUrl", "notConsumed"}


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
    if not node:
        print("node NO disponible: batería F2 no ejecutable")
        return 1

    print("═══ FLOW START FRAME — FASE 2 · parser ANIDADO de batchexecute ═══")

    # ------------------------------------------------------------------
    print("── A. arnés mock F2 (código REAL de injector.js en VM) — T1..T10")
    proc = subprocess.run(
        [node, str(HARNESS)], capture_output=True, text=True, timeout=120)
    try:
        result = json.loads(proc.stdout)
        checks = result.get("checks", {})
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ mock no ejecutable / salida no parseable: {exc} {proc.stderr[:160]}")
        return 1
    MOCK_ORDER = [
        "t1_live_nested", "t2_same_fp", "t3_crop", "t4_no_endframe",
        "t5_malformed", "t6_wuwhi_no_mg", "t7_other_rpc", "t8_secrets",
        "t9_stream", "t10_f1_compat", "t_startimage_hist",
        "t_protobuf_pair", "t_xhr_nested", "t_correlation",
    ]
    for nombre in MOCK_ORDER:
        c = checks.get(nombre)
        if c is None:
            check(f"A.{nombre}", False, "check ausente en el mock")
            continue
        malos = [k for k, v in c.items()
                 if k not in NON_BOOL_OK
                 and not (v is True or (k in NEG_FALSE and v is False))]
        check(f"A.{nombre}", not malos, str(malos))

    # ------------------------------------------------------------------
    print("── B. T1 LIVE nested: extracción de segundo nivel")
    t1 = checks.get("t1_live_nested", {})
    check("B1. videoModelKey abra_i2v_10s", t1.get("videoModelKey") == "abra_i2v_10s",
          str(t1.get("videoModelKey")))
    check("B2. aspectRatio numérico 1 (LIVE)", t1.get("aspectRatio") == 1,
          repr(t1.get("aspectRatio")))
    check("B3. count 1", t1.get("countField") == 1, repr(t1.get("countField")))
    check("B4. structuredPrompt SOLO presencia", t1.get("structuredPromptPresent") is True)
    check("B5. startFrame.mediaIdPresent true", t1.get("mediaIdPresent") is True)
    check("B6. fingerprint 12 hex", t1.get("fp12") is True, str(t1.get("fingerprint")))
    check("B7. ids.inputFramesFirstFrame huella", t1.get("idIn") is True)
    check("B8. ids.firstFrame huella", t1.get("idSt") is True)
    check("B9. contenido del prompt jamás emitido", t1.get("promptContentLeaked") is False)
    check("B10. mediaId crudo jamás emitido", t1.get("noRawMediaId") is True)

    # ------------------------------------------------------------------
    print("── C. T3 cropCoordinates exactas (captura LIVE)")
    t3 = checks.get("t3_crop", {})
    check("C1. crop inputFrames_firstFrame exacta", t3.get("inCrop") is True)
    check("C2. crop firstFrame (standalone) exacta", t3.get("stCrop") is True)
    check("C3. whitelist estricta top/left/bottom/right", t3.get("noExtraKeys") is True)
    tsi = checks.get("t_startimage_hist", {})
    check("C4. crop startImage (histórico) exacta", tsi.get("cropStartImage") is True)
    tpb = checks.get("t_protobuf_pair", {})
    check("C5. crop vía par protobuf-ish", tpb.get("cropOk") is True)

    # ------------------------------------------------------------------
    print("── D. T5 VAL malformado + T9 pasividad de stream")
    t5 = checks.get("t5_malformed", {})
    check("D1. settingsParseError flag diagnóstico", t5.get("parseErrorFlag") is True)
    check("D2. videoModelKey/startFrame null en evento roto",
          t5.get("videoModelKeyNull") is True and t5.get("startFrameNull") is True)
    check("D3. JSON roto jamás en evidencia", t5.get("brokenJsonNeverInEvidence") is True)
    check("D4. observer vivo tras rotura (siguiente evento OK)", t5.get("observerAlive") is True)
    t9 = checks.get("t9_stream", {})
    check("D5. ReadableStream jamás consumido", t9.get("notConsumed") is True)
    check("D6. observación mínima desde URL con stream intacto", t9.get("minimalObs") is True)
    check("D7. respuesta procesada tras stream (rpc_response)", t9.get("responseReached") is True)

    # ------------------------------------------------------------------
    print("── E. T8 regresión de secretos")
    t8 = checks.get("t8_secrets", {})
    check("E1. sin f.sid", t8.get("noFsId") is True)
    check("E2. sin Bearer/Authorization", t8.get("noBearer") is True)
    check("E3. sin cookie/set-cookie", t8.get("noCookie") is True)
    check("E4. sin URL firmada (googleusercontent)", t8.get("noSignedUrl") is True)
    check("E5. mediaId crudo jamás en evidencia", t8.get("noRawMediaId") is True)
    check("E6. huella fp presente (correlación posible)", t8.get("fpStillPresent") is True)

    # ------------------------------------------------------------------
    print("── F. T2 + T6 + T7 + T10 (falsos positivos y compat objeto F1)")
    t2 = checks.get("t2_same_fp", {})
    check("F1. T2: misma fp en detalles, ids y plano", 
          t2.get("detailFpEqual") is True and t2.get("idsFpEqual") is True
          and t2.get("flatFpMatches") is True)
    t6 = checks.get("t6_wuwhi_no_mg", {})
    check("F2. T6: WuwhI sin MG → operation null", t6.get("operationNull") is True)
    check("F3. T6: sin startFrame/crop + workflowId intacto",
          t6.get("noStartFrame") is True and t6.get("noCrop") is True
          and t6.get("workflowIdStill") is True)
    t7 = checks.get("t7_other_rpc", {})
    check("F4. T7: RPC distinto → cero eventos", t7.get("zeroRpcEvents") is True)
    check("F5. T7: jamás MEDIA_GENERATION falsa", t7.get("noMediaGeneration") is True)
    t10 = checks.get("t10_f1_compat", {})
    check("F6. T10: operation MEDIA_GENERATION",
          t10.get("operation") == "MEDIA_GENERATION", str(t10.get("operation")))
    check("F7. T10: videoModelKey abra_i2v_6s", t10.get("videoModelKey") == "abra_i2v_6s")
    check("F8. T10: aspectRatio string '16:9'", t10.get("aspectRatioString") is True)
    check("F9. T10: Start Frame ambas rutas F1 (in + standalone)",
          t10.get("sfIn") is True and t10.get("sfStandalone") is True)
    check("F10. T10: sin parseError en formato F1", t10.get("noParseError") is True)

    # ------------------------------------------------------------------
    print("── M. compatibilidad histórica y correlación")
    check("M1. startImage NO se asume: mediaIdPresent solo si existe",
          tsi.get("mediaIdPresent") is True)
    check("M2. startImage NO se asume (solo si existe): inputFrames también",
          tsi.get("inputFramesFp") is True)
    check("M3. cropCoordinates.startImage extraídas", tsi.get("cropStartImage") is True)
    check("M4. par protobuf-ish ['MEDIA_GENERATION_SETTINGS', VAL] resuelto",
          tpb.get("operation") == "MEDIA_GENERATION" and tpb.get("mediaIdPresent") is True)
    txhr = checks.get("t_xhr_nested", {})
    check("M5. XHR con formato LIVE: misma extracción",
          txhr.get("operation") == "MEDIA_GENERATION" and txhr.get("cropOk") is True)
    tcor = checks.get("t_correlation", {})
    check("M6. correlación: mismo mediaId → misma fp entre eventos",
          tcor.get("sameFpAcrossEvents") is True and tcor.get("fp12") is True)
    check("M7. espejo __FLOW_RPC_OBS__ coincide con lo emitido",
          tcor.get("mirrorMatches") is True)

    # ------------------------------------------------------------------
    print("── N. guardías de alcance y prohibiciones F2")
    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("N1. manifest 2.6.0 (bump minor [flow-start-frame F2])",
          mf.get("version") == "2.6.0", mf.get("version"))
    bridge = (EXT / "bridge.js").read_text(encoding="utf-8") if (EXT / "bridge.js").exists() else ""
    check("N2. bridge.js SIN tocar (sin canal F1/F2 — nada viaja al backend)",
          "FLOW_RPC_EVIDENCE" not in bridge and "startFrame" not in bridge)
    content = ""
    content_path = EXT / "content.js"
    if content_path.exists():
        content = content_path.read_text(encoding="utf-8")
    check("N3. canal page→extension intacto (content reenvía FLOW_RPC_EVIDENCE)",
          "FLOW_RPC_EVIDENCE" in content)
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                             capture_output=True, text=True, cwd=REPO).stdout.split()
    prohibidos = ("production_json", "execution_contract", "flow_jobs",
                  "bridge", "orchestrator", "hands", "agent.py", "harness",
                  "main.py", "schemas")
    tocados = [f for f in changed if any(p in f for p in prohibidos)]
    check("N4. árbol de trabajo: NINGÚN archivo prohibido modificado",
          not tocados, str(tocados))
    permitidos = ("extension/", "tests/")
    fuera = [f for f in changed if not f.startswith(permitidos)]
    check("N5. cambios de trabajo dentro de extension/ + tests/ únicamente",
          not fuera, str(fuera))
    backend_refs = subprocess.run(
        # Guard N6: cero persistencia del canal F2. El marcador del canal es
        # FLOW_RPC_EVIDENCE; el patrón incluía también "startFrame", pero
        # desde los Gates C.0-C.2 (INT-008/010) "startFrame" es campo
        # legítimo y documentado del contrato Flow video en el backend
        # (flow_mcp_client.py), lo que hacía fallar este guard con un falso
        # positivo PRE-EXISTENTE en main. La protección real (cero
        # FLOW_RPC_EVIDENCE en backend) se mantiene verificada.
        ["rg", "-l", "FLOW_RPC_EVIDENCE", str(BACKEND)],
        capture_output=True, text=True)
    check("N6. backend SIN referencia al canal (cero persistencia, como F1)",
          backend_refs.returncode != 0, backend_refs.stdout[:120])

    # ------------------------------------------------------------------
    print("── S. sintaxis y backward compat total")
    if node:
        sintaxis_ok = True
        detalle = ""
        for js in ("injector.js", "background.js", "bridge.js", "content.js"):
            p = EXT / js
            if not p.exists():
                continue
            pr = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
            if pr.returncode != 0:
                sintaxis_ok = False
                detalle = f"{js}: {pr.stderr[:100]}"
        check("S1. sintaxis JS OK (injector/background/bridge/content)", sintaxis_ok, detalle)
    f1 = subprocess.run([sys.executable, str(F1_BATTERY)],
                        capture_output=True, text=True, timeout=600)
    check("S2. batería F1 completa PASS (backward compat total)",
          f1.returncode == 0 and "64 OK" in f1.stdout, f1.stdout[-160:])

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
