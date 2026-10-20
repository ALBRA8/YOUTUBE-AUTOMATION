#!/usr/bin/env python3
"""Batería FLOW START FRAME — DUAL PARSER REAL eb1hJf + REGRESIÓN F1/F2.

Verifica la implementación del parser dual en extension/injector.js:
  1. Parser posicional para RPC real eb1hJf (Protobuf puro).
  2. Normalización de cropCoordinates tanto objeto como array [top, left, bottom, right].
  3. Cero fuga de media ID crudo (solo huella determinista FNV-1a de 12 hex).
  4. Cero falso positivo en telemetría WuwhI (ADD_REFERENCE_INGREDIENT).
  5. No-regresión total de la ruta F2 (MEDIA_GENERATION_SETTINGS con JSON string).
  6. No-regresión total de la ruta F1 (MEDIA_GENERATION_SETTINGS objeto plano).
  7. Alcance estricto: solo extension/ y tests/ modificados.

Uso:
  python tests/test_flow_startframe_eb1hjf.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
BACKEND = REPO / "backend"
HARNESS_EB1HJF = Path(__file__).resolve().parent / "flow_batchexecute_eb1hjf_mock.js"
F1_BATTERY = Path(__file__).resolve().parent / "test_flow_batchexecute.py"
F2_BATTERY = Path(__file__).resolve().parent / "test_flow_startframe_fase2.py"

OK, FAIL = 0, 0


def check(nombre: str, cond: bool, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK] {nombre}")
    else:
        FAIL += 1
        print(f"  [FAIL] {nombre} {extra}")


def main() -> int:
    node = which("node")
    if not node:
        print("ERROR: node no está disponible en PATH")
        return 1

    print("=== DUAL PARSER eb1hJf + NO-REGRESIÓN F1/F2 ===")

    print("\n-- A. Sintaxis JS real")
    for js in ("injector.js", "content.js", "background.js", "bridge.js"):
        p = EXT / js
        if not p.exists():
            continue
        pr = subprocess.run([node, "--check", str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(f"Sintaxis JS OK: {js}", pr.returncode == 0, pr.stderr[:100])

    print("\n-- B. Arnés hermético eb1hJf (injector REAL en VM)")
    proc = subprocess.run([node, str(HARNESS_EB1HJF)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("Arnés eb1hJf ejecuta con código 0", proc.returncode == 0, proc.stderr[:200])

    data = {}
    try:
        data = json.loads(proc.stdout).get("checks", {})
        check("Arnés produce JSON válido", True)
    except Exception as e:
        check("Arnés produce JSON válido", False, str(e))
        return 1

    print("\n-- C. Extracción estructural de eb1hJf posicional (E1)")
    e1 = data.get("e1_eb1hjf_positional", {})
    check("C1. Evento eb1hJf observado", e1.get("observed") is True)
    check("C2. Operación reconocida como MEDIA_GENERATION", e1.get("operation") == "MEDIA_GENERATION")
    check("C3. videoModelKey extraído correctamente (abra_i2v_10s)", e1.get("videoModelKey") == "abra_i2v_10s")
    check("C4. aspectRatio extraído como número (1)", e1.get("aspectRatio") == 1)
    check("C5. count extraído como número (1)", e1.get("count") == 1)
    check("C6. structuredPromptPresent es true", e1.get("structuredPromptPresent") is True)
    check("C7. startFrame.mediaIdPresent es true", e1.get("mediaIdPresent") is True)
    check("C8. fingerprint de 12 hex exacto", e1.get("fp12") is True and e1.get("expectedFp") is True)
    check("C9. ids.firstFrame coincide con huella", e1.get("idPositionMatch") is True)

    print("\n-- D. Normalización de cropCoordinates array -> object (E2)")
    e2 = data.get("e2_crop_array_normalized", {})
    check("D1. cropCoordinates normalizado a objeto plano", e2.get("isObject") is True)
    check("D2. top numérico normalizado", e2.get("top") is True)
    check("D3. bottom numérico normalizado", e2.get("bottom") is True)
    check("D4. right numérico normalizado", e2.get("right") is True)
    check("D5. left null no contamina el objeto", e2.get("leftUndefined") is True)
    check("D6. cropCoordinates reflejado en startFrame", e2.get("startFrameCropMatches") is True)

    print("\n-- E. Confidencialidad y cero fuga de secretos (E3)")
    e3 = data.get("e3_no_raw_media_id_leak", {})
    check("E1. media ID crudo (UUID) JAMÁS presente en la emisión", e3.get("noRawUuid") is True)
    check("E2. Contenido crudo del prompt no filtrado", e3.get("noPromptContent") is True)
    check("E3. f.sid secreto no filtrado", e3.get("noFsId") is True)
    check("E4. Espejo window.__FLOW_RPC_OBS__ activo", e3.get("mirrorMatches") is True)
    check("E5. Espejo window.__FLOW_RPC_OBS__ libre de media ID crudo", e3.get("mirrorNoRawUuid") is True)

    print("\n-- F. Protección contra falsos positivos en telemetría (E4)")
    e4 = data.get("e4_telemetry_no_false_positive", {})
    check("F1. Telemetría ADD_REFERENCE_INGREDIENT no genera MEDIA_GENERATION falsa", e4.get("noMediaGeneration") is True)
    check("F2. operation es null en telemetría", e4.get("operationNull") is True)
    check("F3. startFrame es null en telemetría", e4.get("startFrameNull") is True)

    print("\n-- G. Determinismo de huella y variantes (E7, E8)")
    e7 = data.get("e7_veo_positional", {})
    check("G1. Modelo veo_2_t2v_fast reconocido posicionalmente", e7.get("videoModelKey") == "veo_2_t2v_fast")
    check("G2. Aspect ratio 0 y count 2 en modelo alternativo", e7.get("aspectRatio") == 0 and e7.get("count") == 2)
    e8 = data.get("e8_fingerprint_determinism", {})
    check("G3. Mismo mediaId genera la misma huella determinista (FNV-1a)", e8.get("sameFp") is True)

    print("\n-- H. No-regresión F1 y F2 en el arnés")
    e5 = data.get("e5_f2_nested_regression", {})
    check("H1. F2 nested JSON WuwhI -> MEDIA_GENERATION intacto", e5.get("operation") == "MEDIA_GENERATION" and e5.get("mediaIdPresent") is True)
    e6 = data.get("e6_f1_direct_regression", {})
    check("H2. F1 objeto directo WuwhI -> MEDIA_GENERATION intacto", e6.get("operation") == "MEDIA_GENERATION" and e6.get("mediaIdPresent") is True)

    print("\n-- I. Ejecución de suite de no-regresión F2 completa")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    f2_res = subprocess.run([sys.executable, str(F2_BATTERY)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env, timeout=600)
    check("I1. test_flow_startframe_fase2.py ejecuta y pasa 100%", f2_res.returncode == 0, f2_res.stderr[:200])

    print("\n-- J. Guardias de alcance y límites de repositorio")
    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("J1. Manifest versión 2.6.0 pinned", mf.get("version") == "2.6.0")

    diff_proc = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                               cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
    changed_files = [line.strip() for line in (diff_proc.stdout or "").splitlines() if line.strip()]
    forbidden = ("backend", "contracts", "orchestrator", "flow_jobs", "production_json", "hands", "agent.py")
    leaks = [f for f in changed_files if any(f.startswith(b) for b in forbidden)]
    check("J2. Ningún archivo de backend/contracts/HANDS/orquestador modificado", len(leaks) == 0, repr(leaks))
    only_ext_tests = all(f.startswith(("extension/", "tests/")) for f in changed_files)
    check("J3. Todos los cambios confinados a extension/ y tests/", only_ext_tests, repr(changed_files))

    print(f"\n==========================================")
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print(f"==========================================")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
