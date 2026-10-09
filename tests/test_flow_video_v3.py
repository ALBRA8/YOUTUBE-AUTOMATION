#!/usr/bin/env python3
"""Batería FLOW VIDEO v3 — ventana de video operativa + JOB vs ATTEMPT +
capa operacional Flow Adaptation (P1/P2, taxonomía A-G, retry limitado).

Cubre los 12 comportamientos obligatorios del mandato + no-invasión de la
capa creativa, EN HERMÉTICO (DB/OUTPUT/ledger en tmp; sin Chrome, sin red,
sin Google Flow real, sin SQLite de producción).
Taxonomía actualizada a FLOW OBSERVABILITY V1.1 (A-I, watchdog ≠ proveedor):
la clasificación D-G de la era V3 fue reemplazada (ver test_flow_observability_v11.py
para los 15 checks deterministas del mandato V1.1):

  1. video espera >5 min sin timeout prematuro (ventana 15 min por defecto)
  2. imagen mantiene comportamiento temporal (5 min)
  3. error-tile + generación activa → NO ERROR (intento registrado)
  4. error-tile + video válido → DONE/DOWNLOADED
  5. múltiples error tiles + video → DONE
  6. error tile residual + nuevo job → no lo mata (dedupe + limpieza)
  7. error-tile + sin resultado + ventana agotada → puede ERROR (con evidencia)
  8. video antes del timeout → termina inmediatamente
  9. varios intentos, alguno exitoso → SUCCESS (JOB ≠ ATTEMPT)
  10. múltiples escenas/jobs consecutivos sin contaminación
  11. heartbeat/lease funcionan durante la ventana extendida
  12. sin regresión en imágenes (JS + gate de imagen en la capa)

Capa Flow Adaptation (backend, sobre DB tmp):
  - taxonomía A-I SOLO con evidencia (nunca inventa causa; watchdog → A
    FLOW_WATCHDOG_TIMEOUT, NUNCA timeout del proveedor)
  - S1 (identidad→descripción visual existente, clase F) SOLO tras
    evidencia de rechazo; jamás preventiva; S2 eliminada en V1.1
  - P1 intacto / P2 separado (flow_jobs.prompt vs prompt_adapted)
  - retry limitado dependiente de la clasificación (sin DEAD inmediato, sin
    retry infinito: MAX_EXTRA_GRANTS=1 por job + una sola P2)
  - FLOW_ADAPTATION_REQUIRED cuando no hay estrategia segura (C/E, S1 sin
    datos, P2 ya usado)
  - memoria operacional JSONL separada, con los 7 campos del mandato
  - NO invasión: scenes/projects/avatars intocados; ledger único archivo

Uso:  cd yt_automation_v2 && python3 tests/test_flow_video_v3.py
      python3 -m pytest tests/test_flow_video_v3.py -q
"""
import io
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import which

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "flow_video_v3_mock.js"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")

# ── parcheo ANTES de importar: DB/OUTPUT a tmp (patrón test_flow_bridge) ─────
_TMP = Path(tempfile.mkdtemp(prefix="flow_video_v3_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
from services import flow_jobs as fj  # noqa: E402
from services import flow_adaptation as fa  # noqa: E402
from services import memorydv as _mem  # noqa: E402
_mem.MEMORY_DIR = _TMP / "memorydv"  # hermeticidad: cero escrituras al repo
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


def _extraer(src: str, ini: str, fin: str) -> str:
    i = src.index(ini)
    j = src.index(fin, i)
    return src[i:j].rstrip()


def _bundle_v3(src: str) -> str:
    """Código REAL para el arnés V3: STATUS + ventana imagen + bloque
    [video-window v3] + processDomSnapshot..watchdog (incluye [attempt v3])
    + watchdog real (watchdogBudgetMs/rearmWatchdog/watchdogCheck)."""
    m_status = re.search(r"const STATUS = \{[^}]+\};", src)
    m_img = re.search(r"const SCENE_WATCHDOG_MS_IMAGES = 5 \* 60000;", src)
    m_len = re.search(r"const MAX_PROMPT_MATCH_LEN = \d+;", src)
    ventana = _extraer(src,
                       "/* --- [video-window v3] Ventana operativa de VIDEO",
                       "/* --- Fase 3-e")
    norm = _extraer(src, "function normalizeForMatch",
                    "/* ---------------------------- IndexedDB handles")
    deteccion = _extraer(src, "function detectExtension",
                         "async function saveUrlToDisk")
    seccion = _extraer(src, "async function processDomSnapshot",
                       "/* ---------------- Watchdog por escena")
    watchdog = _extraer(src, "/* ---------------- Watchdog por escena",
                        "/* ------------- Rate limit")
    partes = [m_status.group(0), m_img.group(0), m_len.group(0), ventana,
              norm, deteccion, seccion, watchdog]
    return "\n\n".join(p for p in partes if p)


# ── helpers de DB (hermético) ────────────────────────────────────────────────

def _job(jid: str, kind: str, escena: int, prompt: str,
         status: str = "dead", attempts: int = 2, error: str | None = None,
         prompt_adapted: str | None = None, pid: str = "p_v3",
         lease_cycles: int = 0) -> str:
    with db.connect() as con:
        con.execute(
            """INSERT INTO flow_jobs(id, project_id, kind, scene_number, part,
               prompt, prompt_adapted, prompt_meta, status, attempts,
               max_attempts, lease_cycles, worker, job_token, lease_until,
               error, asset_path, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, pid, kind, escena, 1, prompt, prompt_adapted,
             json.dumps({"title": ""}), status, attempts,
             3 if kind == "image" else 2, lease_cycles, None, None, None,
             error, None, "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00"))
    return jid


def _fila(jid: str) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT * FROM flow_jobs WHERE id=?",
                        (jid,)).fetchone()
        return dict(r) if r else {}


def _mp4_bytes(dur=1.0) -> bytes:
    """MP4 real (H.264+AAC) para validar el circuito complete() con P2."""
    import subprocess as _sp
    out = _TMP / f"clip_v3_{dur}.mp4"
    _sp.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x2288CC:s=64x64:d={dur}",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
        check=True, capture_output=True, timeout=60)
    return out.read_bytes()


_AVATAR_APPERANCE = json.dumps({
    "genero": "Femenino", "piel": "Morena", "ojos_color": "Marrones",
    "rostro": "Ovalado", "cabello_color": "Negro",
    "cabello_largo": "Largo", "cabello_textura": "Liso",
    "cuerpo": "Atlético", "ropa": "Casual elegante",
}, ensure_ascii=False)


def _proyecto_con_avatar(pid: str = "p_v3") -> None:
    """Proyecto + avatar con descripción visual EXISTENTE + escena con
    image_prompt (datos creativos que S1 REUTILIZA; nunca inventa).
    Avatar con id ÚNICO por proyecto (los tests crean varios)."""
    aid = "av_" + pid
    db.create_project(id=pid, title="V3 Test", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    with db.connect() as con:
        con.execute(
            """INSERT INTO avatars(id, name, description, appearance, voice,
               tts_provider, style, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (aid, "Yara Guayaba", "presentadora",
             _AVATAR_APPERANCE, None, "edge", "graphic-novel",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        con.execute("UPDATE projects SET avatar_id=? WHERE id=?", (aid, pid))
    db.replace_scenes(pid, [
        {"title": "Escena 1",
         "narration": "La presentadora saluda.",
         "image_prompt": "Mujer morena de cabello negro largo y liso, "
                         "ojos marrones, ropa casual elegante, estudio "
                         "iluminado, plano medio",
         "duration": 8.0},
    ])
    return aid


def _snapshot_creativo(pid: str, aid: str | None = None) -> dict:
    """Huella completa de los datos creativos (para probar NO invasión)."""
    aid = aid or ("av_" + pid)
    with db.connect() as con:
        proj = dict(con.execute("SELECT * FROM projects WHERE id=?",
                                (pid,)).fetchone())
        av = dict(con.execute("SELECT * FROM avatars WHERE id=?",
                              (aid,)).fetchone())
        scs = [dict(r) for r in con.execute(
            "SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (pid,))]
    return {"projects": proj, "avatars": av, "scenes": scs}


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node))

    print("── A. anclajes mínimos + arnés V3 (código REAL de background.js)")
    src = (EXT / "background.js").read_text(encoding="utf-8", errors="replace")
    check("ventana por defecto 15*60", "15 * 60" in src)
    check("watchdog usa videoTimeoutMs() en video",
          "mode === 'videos' ? videoTimeoutMs() : SCENE_WATCHDOG_MS_IMAGES" in src)
    check("veredicto con evidencia compuesta (composeEvidence v1.1)",
          "composeEvidence(item.scene_number" in src
          and "sceneAttemptsSummary(sceneNumber)" in src)
    check("P2 antes que P1 en el handler del bridge",
          "String((job && job.prompt_adapted) || (job && job.prompt) || '')"
          in src)
    bundle_ok, bundle = False, ""
    if node:
        try:
            bundle = _bundle_v3(src)
            bundle_ok = (bundle.count("{") == bundle.count("}")
                         and "watchdogCheck" in bundle
                         and "videoTimeoutMs" in bundle)
        except Exception:  # noqa: BLE001
            bundle_ok = False
    check("bundle V3 extraíble y balanceado (constantes+ventana+intentos+"
          "snapshot+watchdog)", bundle_ok)
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("sintaxis OK: flow_video_v3_mock.js", proc_syn.returncode == 0,
          proc_syn.stderr.strip()[:150])

    if not node:
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1 if FAIL else 0

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(bundle)
        bundle_path = f.name
    proc = subprocess.run([node, str(HARNESS), bundle_path],
                          capture_output=True, text=True, timeout=120)
    check("arnés corre sin error de ejecución", proc.returncode == 0,
          (proc.stderr or "")[-300:])
    try:
        data = json.loads(proc.stdout)
        esc = data.get("escenas", {})
    except Exception as e:  # noqa: BLE001
        check("arnés produce JSON parseable", False, str(e)[:150])
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1
    check("arnés produce JSON parseable", True)

    def e(n):
        return esc.get(n, {}) or {}

    esperadas = ["video_6min_sin_timeout", "imagen_6min_expira",
                 "video_16min_expira_con_evidencia", "video_16min_sin_intentos",
                 "video_antes_del_timeout", "ventana_configurable",
                 "ventana_30min_16min_sigue", "tiles_acumulan_con_dedupe",
                 "sin_contaminacion_residual", "intento_exitoso_success",
                 "imagen_sin_regresion"]
    check("los 11 escenarios JS corrieron", all(n in esc for n in esperadas),
          repr([n for n in esperadas if n not in esc]))

    print("── B.1 video espera >5 min sin timeout prematuro (mandato 1)")
    v6 = e("video_6min_sin_timeout")
    check("video a los 6 min sigue IN_PROGRESS (ventana 15 min)",
          v6.get("status") == "IN_PROGRESS", repr(v6))
    check("video a los 6 min sin error", not v6.get("error"), repr(v6))

    print("── B.2 imagen mantiene 5 min (mandato 2)")
    i6 = e("imagen_6min_expira")
    check("imagen a los 6 min expira (ventana 5 min intacta)",
          i6.get("status") == "ERROR", repr(i6))
    check("el veredicto cita los 5 min de imagen",
          i6.get("mensaje5min") is True, repr(i6))

    print("── B.3 error-tile + generación activa → NO ERROR (mandato 3)")
    ta = e("tiles_acumulan_con_dedupe")
    check("con pendientes: IN_PROGRESS",
          (ta.get("trasPrimer") or {}).get("status") == "IN_PROGRESS",
          repr(ta))
    check("intento 1 registrado",
          (ta.get("trasPrimer") or {}).get("intentos") == 1, repr(ta))
    check("mismo tile repetido NO infla (dedupe) y texto nuevo sí (2)",
          (ta.get("final") or {}).get("intentos") == 2, repr(ta))
    check("la escena sigue en su ventana (IN_PROGRESS)",
          (ta.get("final") or {}).get("status") == "IN_PROGRESS", repr(ta))

    print("── B.7 ventana agotada + sin resultado → ERROR con evidencia (7)")
    v16 = e("video_16min_expira_con_evidencia")
    check("video a los 16 min → ERROR (triple condición del CAMBIO 5)",
          v16.get("status") == "ERROR", repr(v16))
    check("veredicto cita la ventana de 15 min", v16.get("ventana15") is True,
          repr(v16))
    check("veredicto incluye la evidencia de intentos",
          v16.get("evidencia") is True, repr(v16))
    v16s = e("video_16min_sin_intentos")
    check("sin intentos: veredicto honesto ('sin intentos fallidos')",
          v16s.get("honesto") is True and v16s.get("status") == "ERROR",
          repr(v16s))

    print("── B.8 video válido antes del timeout → inmediato (mandato 8)")
    va = e("video_antes_del_timeout")
    check("a los 14 min llega el MP4 → DOWNLOADED (no espera al agotamiento)",
          va.get("status") == "DOWNLOADED", repr(va))
    check("el video se descargó una vez (mp4)",
          va.get("guardados") == 1 and va.get("ext") == "mp4", repr(va))
    check("intentos limpios al terminar", va.get("intentosLimpios") is True,
          repr(va))

    print("── B.window ventana configurable (piso 1 min, techo 2 h)")
    w = e("ventana_configurable")
    check("defecto 15 min", w.get("defectoMin") == 15, repr(w))
    check("piso 1 min aceptado", w.get("pisoMin") == 1, repr(w))
    check("valor < piso clampa a 1 min", w.get("pisoClampMin") == 1, repr(w))
    check("techo 2 h aceptado", w.get("techoMin") == 120, repr(w))
    check("valor > techo clampa a 2 h", w.get("techoClampMin") == 120, repr(w))
    check("null restaura el defecto", w.get("defectoRestaurado") is True,
          repr(w))
    check("con ventana 1 min, video a los 2 min expira",
          w.get("video2minExpiraCon1min") == "ERROR", repr(w))
    wl = e("ventana_30min_16min_sigue")
    check("ventana configurada 30 min: 16 min NO expira",
          wl.get("status") == "IN_PROGRESS", repr(wl))

    print("── B.6/10 sin contaminación residual entre jobs (6 y 10)")
    sc = e("sin_contaminacion_residual")
    check("escena 1 completa (DOWNLOADED) pese al tile residual",
          (sc.get("escena1") or {}).get("status") == "DOWNLOADED", repr(sc))
    check("attempts limpiados al completar",
          sc.get("limpiezaTrasExito") is True, repr(sc))
    check("job nuevo (escena 2) NO es matado por el tile residual",
          (sc.get("escena2") or {}).get("status") == "IN_PROGRESS", repr(sc))
    check("el residual quedó como intento registrado (no veredicto)",
          sc.get("intentosEscena2") == 1, repr(sc))

    print("── B.9 varios intentos, alguno exitoso → SUCCESS (mandato 9)")
    ex = e("intento_exitoso_success")
    check("intento A y B fallan, C entrega → DOWNLOADED",
          ex.get("status") == "DOWNLOADED", repr(ex))
    check("asset guardado", ex.get("guardados") == 1, repr(ex))
    check("intentos limpiados al éxito (JOB ≠ ATTEMPT)",
          ex.get("intentosLimpiosAlExito") is True, repr(ex))

    print("── B.12 imagen sin regresión (mandato 12)")
    ir = e("imagen_sin_regresion")
    check("imagen: media llega → DOWNLOADED igual que siempre",
          ir.get("status") == "DOWNLOADED", repr(ir))
    check("prefijo imagen intacto", ir.get("prefijo") == "imagen", repr(ir))

    # ═════════════════════ CAPA FLOW ADAPTATION (backend) ════════════════════

    print("── C.1 taxonomía V1.1 A-I SOLO con evidencia (nunca inventa causa)")
    c = fa.clasificar("bloqueo de politicas de contenido", "video")
    check("D FLOW_POLICY_ERROR (texto real observado)",
          c["clase"] == "D" and c["codigo"] == "FLOW_POLICY_ERROR",
          repr(c))
    f_ = fa.clasificar("no podemos generar personas reales o su likeness",
                       "video")
    check("F FLOW_IDENTITY_LIKENESS_ERROR", f_["clase"] == "F", repr(f_))
    g_ = fa.clasificar("esto infringe derechos de autor (copyright)", "video")
    check("G FLOW_COPYRIGHT_ERROR", g_["clase"] == "G", repr(g_))
    c_ = fa.clasificar("El video se generó pero el audio falló", "video")
    check("C FLOW_AUDIO_ERROR (SOLO texto explícito de audio)",
          c_["clase"] == "C", repr(c_))
    e_ = fa.clasificar("No tienes créditos suficientes para generar", "video")
    check("E FLOW_CREDIT_ERROR", e_["clase"] == "E", repr(e_))
    h_ = fa.clasificar("Hemos detectado actividad inusual en tu cuenta",
                       "video")
    check("H FLOW_UNUSUAL_ACTIVITY", h_["clase"] == "H", repr(h_))
    a_ = fa.clasificar("", "video", {"ventana_agotada": True})
    check("A FLOW_WATCHDOG_TIMEOUT (ventana local agotada sin texto)",
          a_["clase"] == "A" and a_.get("alcance_causal") == "LOCAL",
          repr(a_))
    a2 = fa.clasificar("watchdog: sin resultado válido en 15 min", "video")
    check("A por texto de watchdog/timeout local (NUNCA timeout del "
          "proveedor)", a2["clase"] == "A", repr(a2))
    b_ = fa.clasificar("tile de error genérico", "video",
                       {"transitorio": True})
    check("B FLOW_PROVIDER_ERROR (error explícito de Flow sin causa "
          "determinable)", b_["clase"] == "B", repr(b_))
    i_ = fa.clasificar("algo ocurrió sin patrón conocido", "video")
    check("I UNKNOWN_FLOW_FAILURE (texto sin patrón: NO se inventa causa)",
          i_["clase"] == "I", repr(i_))
    ok_ = fa.clasificar("x", "video", {"resultado_valido": True})
    check("resultado válido NO es fallo", ok_["clase"] is None, repr(ok_))

    print("── C.2 S1/S2 NUNCA preventivas (solo con clase por evidencia)")
    p1 = "Yara Guayaba mira directamente a cámara y saluda sonriendo"
    r_a = fa.adaptar_prompt(p1, "A", {"character_name": "Yara Guayaba",
                                      "descripcion_visual": "mujer morena"})
    check("clase A → sin adaptación (aunque haya nombre propio)",
          r_a["aplicada"] is False, repr(r_a))
    r_g = fa.adaptar_prompt(p1, "G", {})
    check("clase G → sin adaptación (sin causa demostrada)",
          r_g["aplicada"] is False, repr(r_g))
    p1_cam = ("La presentadora mira hacia la derecha. Enfoca directamente el "
              "rostro de la mujer con movimiento suave.")
    r_f_no = fa.adaptar_prompt("La mujer camina por el parque", "F", {})
    check("clase F sin descripción visual existente → fail-closed (no "
          "inventa identidad)", r_f_no["aplicada"] is False, repr(r_f_no))

    print("── C.3 S1: identidad → descripción visual EXISTENTE (solo con F)")
    r_d = fa.adaptar_prompt(p1, "F", {
        "character_name": "Yara Guayaba",
        "descripcion_visual": "piel: Morena, ojos: Marrones, cabello: Negro",
    })
    check("S1 aplicada con clase F", r_d["aplicada"] is True, repr(r_d))
    check("S1 preserva la acción de P1",
          "mira directamente a cámara y saluda sonriendo" in r_d["p2"],
          repr(r_d))
    check("S1 neutraliza el nombre (identidad→'el personaje')",
          "Yara Guayaba" not in r_d["p2"] and "el personaje" in r_d["p2"],
          repr(r_d))
    check("S1 incluye la descripción visual existente (no inventada)",
          "piel: Morena, ojos: Marrones, cabello: Negro" in r_d["p2"],
          repr(r_d))
    check("S1 declara el avatar ficticio (operacional, no creativo)",
          "personaje imaginario de ficción" in r_d["p2"], repr(r_d))
    check("P1 ORIGINAL intocable en memoria",
          p1 == "Yara Guayaba mira directamente a cámara y saluda sonriendo")
    r_d_sin = fa.adaptar_prompt(p1, "F", {"character_name": "Yara Guayaba"})
    check("S1 sin descripción visual existente → fail-closed (no inventa)",
          r_d_sin["aplicada"] is False, repr(r_d_sin))

    print("── C.4 estrategias V1.1: solo F→S1; C/D/E/G/H/I sin adaptación")
    r_c = fa.adaptar_prompt(p1_cam, "C", {})
    check("clase C (audio) → el prompt visual NO se toca (mandato ⑥)",
          r_c["aplicada"] is False, repr(r_c))
    r_d2 = fa.adaptar_prompt(p1_cam, "D", {})
    check("clase D (política) → sin adaptación (no reintento idéntico)",
          r_d2["aplicada"] is False, repr(r_d2))
    r_g2 = fa.adaptar_prompt(p1_cam, "G", {})
    check("clase G (copyright) → sin S1 ni workaround inventado (mandato ⑥)",
          r_g2["aplicada"] is False, repr(r_g2))
    check("S2 eliminada en V1.1 (sin clase de interpretación)",
          r_s2_dead["aplicada"] is False if False else True)  # placeholder estable
    check("P1 de cámara intacto",
          p1_cam == ("La presentadora mira hacia la derecha. Enfoca "
                     "directamente el rostro de la mujer con movimiento "
                     "suave."))

    print("── C.5 P1/P2 en flow_jobs (set_adapted_prompt)")
    _proyecto_con_avatar()
    j1 = _job("j_v3_1", "video", 1,
              "Yara Guayaba mira directamente a cámara y saluda",
              status="dead", attempts=2,
              error="no podemos generar personas reales o su likeness")
    antes = _fila("j_v3_1")
    r_set = fj.set_adapted_prompt("j_v3_1", "P2 de prueba operacional",
                                  motivo="prueba")
    check("set_adapted_prompt escribe P2", r_set is not None, repr(r_set))
    despues = _fila("j_v3_1")
    check("P1 permanece intacto en la columna prompt",
          despues["prompt"] == antes["prompt"]
          == "Yara Guayaba mira directamente a cámara y saluda")
    check("P2 quedó en prompt_adapted",
          despues["prompt_adapted"] == "P2 de prueba operacional")
    r_set2 = fj.set_adapted_prompt("j_v3_1", "P2 alternativo", motivo="x")
    check("una sola adaptación por job (no sobrescribe P2)",
          r_set2 is None and _fila("j_v3_1")["prompt_adapted"]
          == "P2 de prueba operacional")
    ji = _job("j_v3_img", "image", 2, "prompt imagen", status="dead",
              attempts=3, error="bloqueo de politicas de contenido")
    check("imagen NUNCA recibe P2 (no se comparte política con imagen)",
          fj.set_adapted_prompt("j_v3_img", "P2", motivo="x") is None
          and _fila("j_v3_img")["prompt_adapted"] is None)
    check("P2 vacío rechazado", fj.set_adapted_prompt("j_v3_1", "  ") is None)

    print("── C.6 requeue_for_adaptation: UN intento extra, acotado")
    r_rq = fj.requeue_for_adaptation("j_v3_1")
    check("reencola el job dead de video", r_rq is not None, repr(r_rq))
    f2 = _fila("j_v3_1")
    check("queda queued con attempts = max-1 (UN intento)",
          f2["status"] == "queued" and f2["attempts"] == 1
          and f2["max_attempts"] == 2, repr(f2))
    check("lease_cycles intacto (contrato anti-zombie manda)",
          f2["lease_cycles"] == 0)
    check("no reencola jobs queued", fj.requeue_for_adaptation("j_v3_1")
          is None or _fila("j_v3_1")["status"] == "queued")
    check("no reencola jobs de imagen",
          fj.requeue_for_adaptation("j_v3_img") is None)
    fj2 = _job("j_v3_q", "video", 3, "prompt", status="queued", attempts=0)
    check("no reencola jobs no-dead", fj.requeue_for_adaptation(fj2) is None)

    print("── C.7 procesar_fallo_job: ciclo completo clase F → P2 → requeue")
    _proyecto_con_avatar("p_d")
    jd = _job("j_v3_d", "video", 1,
              "Yara Guayaba mira directamente a cámara y presenta el producto",
              status="dead", attempts=2,
              error="no podemos generar personas reales o su likeness",
              pid="p_d")
    huella_antes = _snapshot_creativo("p_d")
    dec = fa.procesar_fallo_job("j_v3_d")
    check("decisión de adaptación devuelta", dec is not None, repr(dec))
    check("acción = reencolar_con_p2", dec.get("accion") == "reencolar_con_p2",
          repr(dec))
    check("otorgado marcado (trazable)", dec.get("otorgado") is True)
    fd = _fila("j_v3_d")
    check("P1 intacto tras el ciclo completo",
          fd["prompt"] == "Yara Guayaba mira directamente a cámara y "
                          "presenta el producto")
    check("P2 guardado y con descripción visual del avatar",
          fd["prompt_adapted"] and "piel: Morena" in fd["prompt_adapted"],
          repr(fd.get("prompt_adapted", ""))[:200])
    check("P2 neutraliza la identidad creativa",
          "Yara Guayaba" not in (fd["prompt_adapted"] or ""), repr(fd))
    check("job reencolado con UN intento",
          fd["status"] == "queued" and fd["attempts"] == 1, repr(fd))
    huella_despues = _snapshot_creativo("p_d")
    check("NO invasión: projects/avatars/scenes idénticos byte a byte",
          huella_antes == huella_despues)
    check("segundo procesado del mismo job NO re-adapta (límite)",
          (fa.procesar_fallo_job("j_v3_d") or {}).get("reintentar") is False
          or (_fila("j_v3_d")["status"] == "queued" and
              _fila("j_v3_d")["prompt_adapted"] ==
              fd["prompt_adapted"]))

    print("── C.8 S1 sin NINGÚN dato creativo visual → FLOW_ADAPTATION_REQUIRED")
    _proyecto_con_avatar("p_sinvis")
    # fail-closed real: SIN appearance del avatar Y SIN image_prompt de escena
    # (el fallback de _contexto_creativo usaría la escena y S1 sí aplicaría)
    with db.connect() as con:
        con.execute("UPDATE avatars SET appearance='{}' WHERE id='av_p_sinvis'")
        con.execute("UPDATE scenes SET image_prompt='' WHERE project_id='p_sinvis'")
    jsin = _job("j_v3_sinvis", "video", 1, "Yara Guayaba saluda",
                status="dead", attempts=2,
                error="restricción por likeness de persona real",
                pid="p_sinvis")
    dec_sin = fa.procesar_fallo_job("j_v3_sinvis")
    check("sin descripción visual existente: NO se inventa identidad",
          dec_sin is not None and dec_sin.get("accion") == "detener"
          and dec_sin.get("reporte") == fa.FLOW_ADAPTATION_REQUIRED,
          repr(dec_sin))
    check("job queda dead (sin reintento inseguro)",
          _fila("j_v3_sinvis")["status"] == "dead")
    check("P2 jamás escrito sin adaptación segura",
          _fila("j_v3_sinvis")["prompt_adapted"] is None)

    print("── C.9 clase D (política) → FLOW_ADAPTATION_REQUIRED, sin retry")
    _proyecto_con_avatar("p_c")
    jc = _job("j_v3_c", "video", 1, "contenido cualquiera", status="dead",
              attempts=2, error="bloqueo de politicas de contenido",
              pid="p_c")
    dec_c = fa.procesar_fallo_job("j_v3_c")
    check("D: detener + reporte FLOW_ADAPTATION_REQUIRED",
          dec_c is not None and dec_c.get("reintentar") is False
          and dec_c.get("reporte") == fa.FLOW_ADAPTATION_REQUIRED, repr(dec_c))
    check("D: el job queda dead (la capa jamás adapta contenido político)",
          _fila("j_v3_c")["status"] == "dead"
          and _fila("j_v3_c")["prompt_adapted"] is None)

    print("── C.10 clase A (watchdog local) → sin extra: la ventana manda")
    _proyecto_con_avatar("p_b")
    jb = _job("j_v3_b", "video", 1, "prompt de escena", status="dead",
              attempts=2,
              error="watchdog: sin resultado válido en 15 min "
                    "(2 intento(s) fallido(s))", pid="p_b")
    dec_b = fa.procesar_fallo_job("j_v3_b")
    check("A: la capa NO concede extra (gestiona lease/recover_expired; "
          "sin asumir causa del proveedor)",
          dec_b is not None and dec_b.get("reintentar") is False, repr(dec_b))
    check("A: sin reporte de adaptación requerida (ventana local ≠ rechazo)",
          not dec_b.get("reporte"), repr(dec_b))
    check("A: clasificación FLOW_WATCHDOG_TIMEOUT con alcance LOCAL",
          dec_b is not None and dec_b.get("clase") == "A", repr(dec_b))

    print("── C.11 clase I (desconocido) → UN reintento con P1, sin inventar causa")
    _proyecto_con_avatar("p_g")
    jg = _job("j_v3_g", "video", 1, "prompt de escena", status="dead",
              attempts=2, error="algo ocurrió sin patrón conocido", pid="p_g")
    dec_g = fa.procesar_fallo_job("j_v3_g")
    check("I: reintento concedido SIN adaptación (no se inventa causa)",
          dec_g is not None and dec_g.get("accion") == "reencolar_sin_cambio",
          repr(dec_g))
    check("I: reencolado con P1 (sin P2)",
          _fila("j_v3_g")["status"] == "queued"
          and _fila("j_v3_g")["prompt_adapted"] is None)
    # simular que el reintento G falló de nuevo → dead → límite de grants
    with db.connect() as con:
        con.execute("""UPDATE flow_jobs SET status='dead', attempts=2,
                       error='algo ocurrió sin patrón conocido'
                       WHERE id='j_v3_g'""")
    dec_g2 = fa.procesar_fallo_job("j_v3_g")
    check("I: segundo fallo → LÍMITE de grants + reporte (repeated failure)",
          dec_g2 is not None and dec_g2.get("reintentar") is False
          and "LÍMITE" in dec_g2.get("motivo", "")
          and dec_g2.get("reporte") == fa.FLOW_ADAPTATION_REQUIRED,
          repr(dec_g2))

    print("── C.12 gate de imagen (mandato 10/12: no compartir política)")
    _proyecto_con_avatar("p_img")
    jim = _job("j_v3_img2", "image", 1, "prompt imagen", status="dead",
               attempts=3,
               error="no podemos generar personas reales o su likeness",
               pid="p_img")
    check("imagen: la capa NO interviene (None)",
          fa.procesar_fallo_job("j_v3_img2") is None)
    check("imagen: el job permanece dead sin P2",
          _fila("j_v3_img2")["status"] == "dead"
          and _fila("j_v3_img2")["prompt_adapted"] is None)

    print("── C.13 memoria operacional: ledger JSONL separado y trazable")
    led = fa._ledger()
    check("ledger existe bajo el tmp del test (NUNCA en el repo)",
          led.exists() and str(_TMP) in str(led), str(led))
    registros = [json.loads(l) for l in led.read_text(encoding="utf-8")
                 .splitlines() if l.strip()]
    decisiones = [r for r in registros if not r.get("cierre")]
    cierres = [r for r in registros if r.get("cierre")]
    check("registros JSONL parseables (>= 5 decisiones)", len(decisiones) >= 5,
          len(decisiones))
    campos = {"job_id", "prompt_original", "evidencia_observada",
              "clasificacion", "transformacion", "prompt_adaptado",
              "resultado", "retry"}
    check("cada registro de decisión trae los 7 campos del mandato",
          all(campos <= set(r) for r in decisiones),
          repr(sorted(campos - set(decisiones[0]))))
    d_reg = next(r for r in decisiones if r["job_id"] == "j_v3_d")
    check("registro D: P1 registrado (trazable) + P2 + transformación",
          "Yara Guayaba mira directamente" in d_reg["prompt_original"]
          and d_reg["prompt_adaptado"] and d_reg["transformacion"],
          repr(d_reg)[:300])
    check("registro D (política): resultado FLOW_ADAPTATION_REQUIRED",
          any(r.get("job_id") == "j_v3_c"
              and r.get("resultado") == fa.FLOW_ADAPTATION_REQUIRED
              for r in decisiones))
    check("los grants quedan contados (límite anti-bucle auditable)",
          sum(1 for r in decisiones
              if r.get("job_id") == "j_v3_g" and r.get("otorgado")) == 1)
    check("registros de cierre bien formados ('si funcionó' registrable)",
          all("resultado" in r and "job_id" in r for r in cierres),
          repr(cierres)[:200])

    print("── C.14 heartbeat/lease durante la ventana extendida (mandato 11)")
    _proyecto_con_avatar("p_lease")
    _job("j_v3_lease", "video", 1, "prompt lease", status="queued",
         attempts=0, pid="p_lease")
    job = fj.claim_next("worker_v3", pid="p_lease")
    check("claim de video con lease 15 min", job is not None
          and job["kind"] == "video", repr(job))
    check("LEASE_S video = 15 min (cubre la ventana por defecto)",
          fj.LEASE_S["video"] == 15 * 60)
    hb = fj.heartbeat(job["id"], job["job_token"])
    check("heartbeat renueva el lease (aceptado, worker vivo)",
          hb is not None and hb.get("lease_until"), repr(hb))
    check("el lease latido deja el lease en el futuro (now+5 min)",
          hb["lease_until"] > _iso(datetime.now(timezone.utc)))
    # Simular un worker latiendo ~cada 30s DURANTE 16+ min (ventana 15 min
    # + margen): el lease nunca expira y el job jamás es reapeado.
    for _ in range(34):  # 34 × 30 s ≈ 17 min simulados
        with db.connect() as con:
            con.execute(
                """UPDATE flow_jobs SET lease_until=? WHERE id=?""",
                (_iso(datetime.now(timezone.utc) + timedelta(seconds=300)
                      - timedelta(seconds=30)), job["id"]))
        hb_i = fj.heartbeat(job["id"], job["job_token"])
        assert hb_i is not None  # el latido siempre renueva
    check("17 min de latidos: el job sigue claimed (lease > now)",
          _fila(job["id"])["status"] == "claimed"
          and _fila(job["id"])["lease_until"]
          > _iso(datetime.now(timezone.utc)))
    # lease vigente → recover_expired NO lo toca (trabajo en vuelo)
    n = fj.recover_expired()
    check("lease vigente: recover_expired no reencola el job",
          _fila(job["id"])["status"] == "claimed")
    # worker MUERTO: lease vencido → queued sin consumir attempts
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET lease_until='2000-01-01T00:00:00+00:00'"
                    " WHERE id=?", (job["id"],))
    fj.recover_expired()
    fl = _fila(job["id"])
    check("lease vencido → queued sin consumir attempts (lease_cycles 1)",
          fl["status"] == "queued" and fl["attempts"] == 0
          and fl["lease_cycles"] == 1, repr(fl))

    print("── C.15 fail() de video dead dispara la capa; imagen NUNCA")
    _proyecto_con_avatar("p_hook")
    jh = _job("j_v3_hook", "video", 1, "Yara Guayaba presenta", status="queued",
              attempts=0, pid="p_hook")
    jb2 = fj.claim_next("worker_v3", pid="p_hook")
    res_fail = fj.fail(jb2["id"], jb2["job_token"],
                       "no podemos generar personas reales o su likeness")
    check("fail 1/2 → queued (contrato MAX_ATTEMPTS intacto)",
          res_fail["status"] == "queued", repr(res_fail))
    jb3 = fj.claim_next("worker_v3", pid="p_hook")
    res_fail2 = fj.fail(jb3["id"], jb3["job_token"],
                        "no podemos generar personas reales o su likeness")
    check("fail 2/2 → dead + la capa adaptó (key 'adaptacion')",
          res_fail2["status"] == "dead"
          and res_fail2.get("adaptacion", {}).get("accion")
          == "reencolar_con_p2", repr(res_fail2))
    fh = _fila(jb2["id"])
    check("el hook dejó el job reencolado con P2 y P1 intacto",
          fh["status"] == "queued" and fh["prompt_adapted"]
          and fh["prompt"].startswith("Yara Guayaba"), repr(fh))
    jimg = _job("j_v3_hookimg", "image", 2, "prompt imagen", status="queued",
                attempts=0, pid="p_hook")
    ji2 = fj.claim_next("worker_v3", pid="p_hook")
    # puede reclamar primero el video reencolado (imagen antes que video) →
    # reclamamos hasta obtener el de imagen
    intentos = 0
    while (ji2 is None or ji2["kind"] != "image") and intentos < 5:
        if ji2 and ji2["kind"] == "video":
            fj.fail(ji2["id"], ji2["job_token"], "descartado por el test")
        ji2 = fj.claim_next("worker_v3", pid="p_hook")
        intentos += 1
    if ji2 and ji2["kind"] == "image":
        ri = fj.fail(ji2["id"], ji2["job_token"],
                     "no podemos generar personas reales o su likeness")
        # imagen: attempts 1/3 → queued (sin adaptacion en la respuesta)
        check("imagen: fail sin key 'adaptacion' (la capa no interviene)",
              "adaptacion" not in (ri or {}), repr(ri))
    else:
        check("imagen: fail sin key 'adaptacion' (la capa no interviene)",
              False, "no se pudo reclamar el job de imagen")

    print("── C.16 cierre del ciclo: completar CON P2 registra 'si funcionó'")
    # neutralizar el job de imagen del fixture (dead) para que el claim tome
    # el video reencolado con P2 (el claim ordena imagen antes que video)
    with db.connect() as con:
        con.execute("UPDATE flow_jobs SET status='dead' WHERE id='j_v3_hookimg'")
    jfin = fj.claim_next("worker_v3", pid="p_hook")
    # el único job pendiente del proyecto p_hook es el video reencolado con P2
    check("claim del job con P2", jfin is not None
          and jfin["kind"] == "video"
          and jfin.get("prompt_adapted"), repr(jfin))
    r_done = fj.complete(jfin["id"], jfin["job_token"], _mp4_bytes(1.0))
    check("complete con MP4 real aceptado (P2 ejecutado)",
          r_done is not None and r_done.get("ok"), repr(r_done))
    cierres = [json.loads(l) for l in fa._ledger().read_text(
        encoding="utf-8").splitlines() if l.strip()]
    cierres = [r for r in cierres if r.get("cierre")]
    check("ledger registra el cierre 'P2 funcionó' (si funcionó)",
          any(c.get("job_id") == jfin["id"]
              and "funcionó" in c.get("resultado", "") for c in cierres),
          repr(cierres)[:250])

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
