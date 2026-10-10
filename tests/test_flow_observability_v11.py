#!/usr/bin/env python3
"""Batería FLOW OBSERVABILITY V1.1 — los 15 checks deterministas del mandato.

Cubre, EN HERMÉTICO (sin Chrome, sin red, sin Google Flow real):

  ①  4xx/5xx capturados como EVIDENCIA cruda por el interceptor REAL
     (fetch + XHR; status/statusText/ok/url-sin-query/método/ts/endpoint/
     cuerpo con redacción de secretos y truncado determinista; éxito 200
     intacto; URLs no relevantes intactas)
  ②  notificaciones del sistema de Flow (source=flow_notification; tipo
     SOLO con texto claro; genérico → FLOW_GENERATION_FAILURE UNKNOWN)
  ③  separación WATCHDOG_TIMEOUT (A) vs PROVIDER_ERROR (B) vs taxonomía
     C-H (solo texto claro) vs I (sin evidencia)
  ④  prioridad de evidencia (red > notificación > tile > DOM > watchdog >
     sin resultado; la débil jamás contradice a la fuerte)
  ⑤  JOB vs ATTEMPT: evidencia por intento sin contaminación entre jobs
  ⑥  reglas de adaptación por clase (A no asume causa; B sin adaptación
     inventada; D/G sin reintento idéntico → FLOW_ADAPTATION_REQUIRED;
     F→S1 con datos existentes; C no toca el prompt visual)
  ⑦  configuración de generación solo REAL (cfg: …, source=
     flow_generation_settings; unknown si no está; jamás desde la URL)
  ⑧  audio del video: unknown salvo evidencia DOM explícita (nunca false)
  ⑨  "No se pudo generar el video" NO es fallo de audio
  ⑩  evidencia cruda + estructura preservadas (la clasificación no
     reemplaza lo observado) + classification_confidence
  ⑪  confianza HIGH/MEDIUM/LOW por fuente de evidencia
  12  P1 raw intacto / P2 solo ejecución
  13  Creative Engine byte-idéntico al ref remoto (git)
  14  production_json.py byte-idéntico al ref remoto (git)
  15  flow_export.py byte-idéntico al ref remoto (git)

Uso:  cd yt_automation_v2 && python3 tests/test_flow_observability_v11.py
      python3 -m pytest tests/test_flow_observability_v11.py -q
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "flow_observability_mock.js"

# ── parcheo ANTES de importar: DB/OUTPUT a tmp (patrón test_flow_video_v3) ───
_TMP = Path(tempfile.mkdtemp(prefix="flow_observability_v11_"))
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


def _job(jid, kind, escena, prompt, status="dead", attempts=2,
         error=None, pid="p_v11"):
    with db.connect() as con:
        con.execute(
            """INSERT INTO flow_jobs(id, project_id, kind, scene_number, part,
               prompt, prompt_adapted, prompt_meta, status, attempts,
               max_attempts, lease_cycles, worker, job_token, lease_until,
               error, asset_path, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, pid, kind, escena, 1, prompt, None,
             json.dumps({"title": ""}), status, attempts,
             3 if kind == "image" else 2, 0, None, None, None,
             error, None, "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00"))
    return jid


def _fila(jid):
    with db.connect() as con:
        r = con.execute("SELECT * FROM flow_jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else {}


# Composiciones EXACTAS en el formato composeEvidence (ext 2.3.1, ≤490)
W_PURE = ("watchdog: sin resultado válido en 15 min (sin intentos fallidos "
          "registrados) | cfg: m=unknown,r=unknown,d=unknown,o=unknown,"
          "n=unknown | audio=unknown")
W_TILE_GENERIC = ("watchdog: sin resultado válido en 15 min (2 intento(s) "
                  "fallido(s) · última evidencia: flow-error-tile: Something "
                  "went wrong) | tile: flow-error-tile: Something went wrong "
                  "while generating | cfg: m=unknown,r=unknown,d=unknown,"
                  "o=unknown,n=unknown | audio=unknown")
W_403_POLICY = ("watchdog: sin resultado válido en 15 min (1 intento(s) "
                "fallido(s) · última evidencia: flow-error-tile: Something) "
                "| http: 403 POST | http-body: Your prompt violates our "
                "content policy | tile: flow-error-tile: Something went "
                "wrong | cfg: m=unknown,r=unknown,d=unknown,o=unknown,"
                "n=unknown | audio=unknown")
W_403_GENERIC = ("http: 403 POST | http-body: Request could not be "
                 "processed | cfg: m=unknown,r=unknown,d=unknown,o=unknown,"
                 "n=unknown | audio=unknown")
N_GENERIC_NOTIF = ("watchdog: sin resultado válido en 15 min (1 intento(s) "
                   "fallido(s) · última evidencia: flow-error-tile: No se "
                   "pudo) | notif: \"No se pudo generar el video\" | tile: "
                   "flow-error-tile: No se pudo completar la acción | cfg: "
                   "m=unknown,r=unknown,d=unknown,o=unknown,n=unknown | "
                   "audio=unknown")
N_AUDIO = ("watchdog: sin resultado válido en 15 min (1 intento(s) "
           "fallido(s) · última evidencia: x) | notif: \"El video se generó "
           "pero el audio falló\" | cfg: m=unknown,r=unknown,d=unknown,"
           "o=unknown,n=unknown | audio=unknown")
N_POLICY = ("notif: \"Tu prompt viola nuestras políticas de contenido\" | "
            "cfg: m=unknown,r=unknown,d=unknown,o=unknown,n=unknown | "
            "audio=unknown")
N_CREDIT = ("notif: \"No tienes créditos suficientes para generar\" | cfg: "
            "m=unknown,r=unknown,d=unknown,o=unknown,n=unknown | audio="
            "unknown")
N_UNUSUAL = ("notif: \"Detectamos actividad inusual en tu cuenta\" | cfg: "
             "m=unknown,r=unknown,d=unknown,o=unknown,n=unknown | audio="
             "unknown")
TILE_POLICY = ("watchdog: sin resultado válido en 15 min (1 intento(s) "
               "fallido(s) · última evidencia: tile) | http: 403 POST | "
               "http-body: content policy violation detected | tile: "
               "bloqueo de politicas de contenido | cfg: m=unknown,"
               "r=unknown,d=unknown,o=unknown,n=unknown | audio=unknown")


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node))

    # ════════════ A. INTERCEPTOR REAL (P0-①: red como evidencia) ════════════
    print("── A. interceptor REAL: 4xx/5xx + fallos de red como evidencia (①)")
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("sintaxis OK: flow_observability_mock.js", proc_syn.returncode == 0,
          proc_syn.stderr.strip()[:150])
    check("sintaxis OK: injector.js real",
          subprocess.run([node, "--check", str(EXT / "injector.js")],
                         capture_output=True).returncode == 0)
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
    else:
        h = {}

    a = h.get("http200_success_preserved", {})
    check("1. HTTP 200 → extracción existente intacta (FLOW_BATCH_RESPONSE)",
          a.get("batchEmit") is True and a.get("mediaId") is True, repr(a))
    check("1b. HTTP 200 → cero emisiones de error (sin regresión)",
          a.get("noErrorEmit") is True, repr(a))

    p4 = h.get("http403_policy", {})
    check("2a. 403 capturado con campos completos (status/statusText/ok/"
          "método/ts/endpoint)",
          p4.get("status") == 403 and p4.get("statusText") == "Forbidden"
          and p4.get("ok") is False and p4.get("method") == "POST"
          and p4.get("hasTs") is True and p4.get("endpoint") == "trpc",
          repr(p4))
    check("2b. 403: cuerpo con la evidencia de política preservada",
          p4.get("bodyHasPolicy") is True and p4.get("urlNoQuery") is True,
          repr(p4))

    g4 = h.get("http403_generic", {})
    check("3a. 403 genérico capturado crudo (sin inferir causa)",
          g4.get("status") == 403 and g4.get("method") == "GET"
          and "processed" in (g4.get("body") or ""), repr(g4))

    t5 = h.get("http500_truncated", {})
    check("4a. 500 con cuerpo largo: truncado determinista con marca [TRUNCATED]",
          t5.get("truncated") is True and t5.get("endsWithMarker") is True
          and t5.get("total") == 3004, repr(t5))
    check("4b. misma entrada → misma salida (determinismo)",
          t5.get("deterministic") is True, repr(t5))

    rj = h.get("fetch_rejection", {})
    check("5. rechazo de red → kind network_failure (sin status inventado)",
          rj.get("kind") == "network_failure" and rj.get("status") is None
          and rj.get("error") is True, repr(rj))

    sec = h.get("secrets_redacted", {})
    check("6. secretos REDACTADOS (bearer/cookie/api_key) — texto normal intacto",
          sec.get("noBearer") and sec.get("noCookieSid") and sec.get("noApiKey")
          and sec.get("hasRedacted") and sec.get("keepsText"), repr(sec))

    xh = h.get("xhr", {})
    check("7. XHR 403 capturado + 200 batch intacto + error de red capturado",
          xh.get("http403") and xh.get("batchIntacto")
          and xh.get("networkFailure") and xh.get("method") == "POST",
          repr(xh))

    ir = h.get("irrelevant_url", {})
    check("8. URL no relevante → cero emisiones (la página no se toca)",
          ir.get("emits") == 0, repr(ir))

    uq = h.get("url_query_stripped", {})
    check("9. query string SIEMPRE fuera de la URL (tokens/firmas no viajan)",
          uq.get("noToken") is True, repr(uq))

    # ════════════ B. composición REAL de la extensión (②⑤⑦⑧⑨) ════════════
    print("── B. composición REAL de evidencia (código REAL de background.js)")
    comp = {}
    if node:
        src = (EXT / "background.js").read_text(encoding="utf-8",
                                                errors="replace")
        try:
            bloque = _extraer(src, "function recordSceneAttempt",
                              "/* ---- fin [observability v1.1]")
            balanceado = bloque.count("{") == bloque.count("}")
            check("bloque de evidencia v1.1 extraíble y balanceado",
                  balanceado and "composeEvidence" in bloque
                  and "recordSceneNotification" in bloque)
        except Exception:  # noqa: BLE001
            bloque = ""
            check("bloque de evidencia v1.1 extraíble y balanceado", False)
        if bloque:
            harness_comp = (
                "const fs=require('fs'),vm=require('vm');\n"
                "const bloque=fs.readFileSync(process.argv[2],'utf8');\n"
                "const sb={setTimeout,clearTimeout,console:{log(){},error(){}},\n"
                "  persistState(){}, sceneAttempts:new Map(), sceneEvidence:new Map(),\n"
                "  sceneSettings:new Map(), orphanNetwork:[]};\n"
                "vm.createContext(sb); vm.runInContext(bloque,sb);\n"
                "sb.recordSceneAttempt(1,'flow-error-tile: Something went wrong');\n"
                "sb.recordSceneAttempt(1,'fallo distinto');\n"
                "sb.recordSceneNotification(1,{text:'No se pudo generar el video',role:'status'});\n"
                "sb.recordSceneNotification(1,{text:'El video se generó pero el audio falló',role:'alert'});\n"
                "sb.recordSceneNotification(1,{text:'No se pudo generar el video'}); // dedupe\n"
                "sb.recordSceneNetwork(1,{kind:'http_error',status:403,method:'POST',url:'https://flow.google.com/fx/api/trpc/x',body:'Your prompt violates our content policy',ts:1});\n"
                "sb.recordSceneSilent(1,'ausente');\n"
                "sb.sceneSettings.set(1,{settings:{model:'veo-3',resolution:'720p',durationSec:'8'},source:'flow_generation_settings',ts:1});\n"
                "const msg1=sb.composeEvidence(1,'watchdog: sin resultado válido en 15 min');\n"
                "const n1=sb.sceneEvidence.get(1).notifications;\n"
                "sb.clearSceneAttempts(1);\n"
                "sb.recordSceneNotification(2,{text:'Detectamos actividad inusual en tu cuenta'});\n"
                "const msg2=sb.composeEvidence(2,'watchdog: sin resultado válido en 15 min');\n"
                "const msg3=sb.composeEvidence(3,'watchdog: sin resultado válido en 15 min');\n"
                "process.stdout.write(JSON.stringify({msg1,msg2,msg3,n1}));\n")
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as f:
                f.write(bloque)
                bpath = f.name
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as f2:
                f2.write(harness_comp)
                hpath = f2.name
            pc = subprocess.run([node, hpath, bpath],
                                capture_output=True, text=True, timeout=60)
            try:
                comp = json.loads(pc.stdout)
                check("composición v1.1 corre en SW simulado", True)
            except Exception as e:  # noqa: BLE001
                check("composición v1.1 corre en SW simulado", False,
                      (pc.stderr or "")[-250:])
                comp = {}

    m1 = comp.get("msg1") or ""
    n1 = comp.get("n1") or []
    check("② notificación registrada con source=flow_notification",
          any(n.get("source") == "flow_notification" for n in n1), repr(n1))
    check("② notificación con metadata ARIA real (role) preservada",
          any(n.get("role") == "status" or n.get("role") == "alert"
              for n in n1), repr(n1))
    check("② dedupe: la misma notificación repetida NO infla",
          len(n1) == 2, repr(len(n1)))
    gen = next((n for n in n1 if "No se pudo generar el video" in n.get("text", "")), {})
    check("②⑨ genérica → FLOW_GENERATION_FAILURE causa UNKNOWN (nunca error "
          "del proveedor ni audio)",
          gen.get("inferredType") == "FLOW_GENERATION_FAILURE"
          and gen.get("cause") == "UNKNOWN", repr(gen))
    aud = next((n for n in n1 if "audio falló" in n.get("text", "")), {})
    check("⑨ audio explícito → VIDEO_GENERATED_AUDIO_FAILED (solo con texto "
          "claro de audio)",
          aud.get("inferredType") == "VIDEO_GENERATED_AUDIO_FAILED", repr(aud))
    check("① capa de red registrada en la evidencia (403 + cuerpo política)",
          "http: 403 POST" in m1
          and "http-body: Your prompt violates our content policy" in m1,
          repr(m1[:200]))
    check("⑦ configuración REAL capturada (m=veo-3,r=720p,d=8) — no URL",
          "cfg: m=veo-3,r=720p,d=8" in m1, repr(m1[:260]))
    check("⑧ audio=ausente con evidencia DOM explícita (nunca false por defecto)",
          "audio=ausente" in m1, repr(m1[-120:]))
    check("⑤ veredicto ≤490 (cabe en el transporte de 500 existente)",
          len(m1) <= 490, repr(len(m1)))
    m2 = comp.get("msg2") or ""
    m3 = comp.get("msg3") or ""
    check("⑤ escena 2 SIN contaminación de la escena 1 (solo su propia "
          "notificación)",
          "actividad inusual" in m2 and "audio falló" not in m2
          and "403" not in m2, repr(m2[:200]))
    check("⑤ escena 3 sin evidencia → honesto ('sin intentos fallidos "
          "registrados' + unknown)",
          "sin intentos fallidos registrados" in m3
          and "audio=unknown" in m3 and "cfg: m=unknown" in m3,
          repr(m3[:200]))

    # ════════════ C. clasificación backend V1.1 (③④⑦⑧⑨⑩⑪) ════════════
    print("── C. clasificación V1.1 (prioridad de evidencia ④, sin inventar)")
    c1 = fa.clasificar(W_PURE, "video", {"ventana_agotada": True})
    check("4. watchdog puro → A FLOW_WATCHDOG_TIMEOUT (NUNCA timeout del "
          "proveedor), alcance LOCAL, conf LOW",
          c1["clase"] == "A" and c1["codigo"] == "FLOW_WATCHDOG_TIMEOUT"
          and c1.get("alcance_causal") == "LOCAL"
          and c1["classification_confidence"] == "LOW", repr(c1["clase"]))

    c2 = fa.clasificar(W_TILE_GENERIC, "video", {"ventana_agotada": True})
    check("4b. tile genérico + watchdog → A (la evidencia débil no lo "
          "convierte en error del proveedor)",
          c2["clase"] == "A", repr(c2["clase"]))

    c3 = fa.clasificar(N_GENERIC_NOTIF, "video", {"ventana_agotada": True})
    check("4c. notificación genérica ('No se pudo generar el video') + "
          "watchdog → A; nunca PROVIDER_ERROR interno",
          c3["clase"] == "A", repr(c3["clase"]))

    c4 = fa.clasificar(W_403_POLICY, "video", {"ventana_agotada": True})
    check("2. 403 + cuerpo de política → D FLOW_POLICY_ERROR (la red manda "
          "sobre el watchdog), HIGH",
          c4["clase"] == "D" and c4["codigo"] == "FLOW_POLICY_ERROR"
          and c4["classification_confidence"] == "HIGH"
          and c4["fuente_evidencia"] == "http_response", repr(c4["clase"]))

    c5 = fa.clasificar(W_403_GENERIC, "video")
    check("3. 403 genérico (sin watchdog) → B FLOW_PROVIDER_ERROR; un status "
          "aislado NO infiere causa",
          c5["clase"] == "B" and c5["codigo"] == "FLOW_PROVIDER_ERROR"
          and c5["classification_confidence"] == "MEDIUM", repr(c5["clase"]))

    c6 = fa.clasificar(N_AUDIO, "video", {"ventana_agotada": True})
    check("5. notificación de audio → C FLOW_AUDIO_ERROR (HIGH)",
          c6["clase"] == "C" and c6["codigo"] == "FLOW_AUDIO_ERROR"
          and c6["classification_confidence"] == "HIGH", repr(c6["clase"]))

    c7 = fa.clasificar(N_POLICY, "video")
    check("6. notificación de política → D FLOW_POLICY_ERROR (HIGH, fuente "
          "flow_notification)",
          c7["clase"] == "D" and c7["fuente_evidencia"] == "flow_notification",
          repr(c7["clase"]))

    c8 = fa.clasificar(N_CREDIT, "video")
    check("7. notificación de créditos → E FLOW_CREDIT_ERROR",
          c8["clase"] == "E" and c8["codigo"] == "FLOW_CREDIT_ERROR",
          repr(c8["clase"]))

    c9 = fa.clasificar(N_UNUSUAL, "video")
    check("8. notificación de actividad inusual → H FLOW_UNUSUAL_ACTIVITY",
          c9["clase"] == "H" and c9["codigo"] == "FLOW_UNUSUAL_ACTIVITY",
          repr(c9["clase"]))

    c10 = fa.clasificar(TILE_POLICY, "video", {"ventana_agotada": True})
    check("9. HTTP error + tile (ambos con causa) → la RED prioriza "
          "(fuente=http_response, no flow_error_tile)",
          c10["clase"] == "D" and c10["fuente_evidencia"] == "http_response",
          repr(c10.get("fuente_evidencia")))

    c11 = fa.clasificar("algo ocurrió sin patrón conocido", "video")
    check("11b. texto sin patrón y sin ventana → I UNKNOWN_FLOW_FAILURE "
          "(no se inventa causa)",
          c11["clase"] == "I" and c11["codigo"] == "UNKNOWN_FLOW_FAILURE",
          repr(c11["clase"]))

    okc = fa.clasificar("x", "video", {"resultado_valido": True})
    check("1c. resultado válido NO es fallo (clase None)",
          okc["clase"] is None, repr(okc["clase"]))

    print("── C.2 ⑩ estructura cruda preservada + ⑪ confianza")
    c12 = fa.clasificar(W_403_POLICY, "video", {"ventana_agotada": True})
    e = c12.get("evidencia_estructura") or {}
    check("⑩ capas estructurales parseadas (http/notificaciones/tiles/cfg/"
          "audio) SIN reemplazar lo crudo",
          (e.get("http") or {}).get("status") == 403
          and e.get("bruto", "").startswith("watchdog:")
          and "bruto" in e and "configuracion" in e
          and "audio_silencioso" in e, repr(sorted(e.keys())))
    check("⑩ el texto CRUDO completo sigue presente (la clasificación no lo "
          "sustituye)",
          c12.get("evidencia") == W_403_POLICY[:300], repr(c12.get("evidencia"))[:120])
    check("⑦ fuente de configuración etiquetada flow_generation_settings",
          (e.get("configuracion") or {}).get("source")
          == "flow_generation_settings", repr(e.get("configuracion")))
    confs = {k: fa.clasificar(v, "video", {"ventana_agotada": True}
                              ).get("classification_confidence")
             for k, v in (("http", W_403_POLICY), ("notif", N_AUDIO),
                          ("tile", W_TILE_GENERIC), ("watchdog", W_PURE))}
    check("⑪ HIGH por red/notificación; LOW por watchdog local",
          confs["http"] == "HIGH" and confs["notif"] == "HIGH"
          and confs["watchdog"] == "LOW", repr(confs))

    # ════════════ D. ⑤ JOB vs ATTEMPT sin contaminación (DB tmp) ════════════
    print("── D. JOB vs ATTEMPT: clasificación por job, sin contaminación")
    _job("j_v11_pol", "video", 1, "prompt escena 1", status="dead",
         attempts=2, error="bloqueo de politicas de contenido")
    _job("j_v11_aud", "video", 1, "prompt escena 1 (intento 2)", status="dead",
         attempts=2, error="El video se generó pero el audio falló")
    d1 = fa.procesar_fallo_job("j_v11_pol")
    d2 = fa.procesar_fallo_job("j_v11_aud")
    check("⑤ job 1 (política) → D con reporte; job 2 (audio) → C con "
          "reintento: independiente",
          d1 and d1.get("clase") == "D" and d1.get("reporte")
          == fa.FLOW_ADAPTATION_REQUIRED
          and d2 and d2.get("clase") == "C" and d2.get("reintentar") is True,
          repr((d1 or {}).get("clase")) + repr((d2 or {}).get("clase")))
    check("⑤ job 1 queda dead sin P2 (política jamás adapta); job 2 "
          "reencolado con P1 limpio",
          _fila("j_v11_pol")["status"] == "dead"
          and _fila("j_v11_pol")["prompt_adapted"] is None
          and _fila("j_v11_aud")["status"] == "queued"
          and _fila("j_v11_aud")["prompt_adapted"] is None,
          repr((_fila("j_v11_pol")["status"], _fila("j_v11_aud")["status"])))
    led = [json.loads(l) for l in fa._ledger().read_text(encoding="utf-8")
           .splitlines() if l.strip()]
    reg1 = next((r for r in led if r.get("job_id") == "j_v11_pol"), {})
    reg2 = next((r for r in led if r.get("job_id") == "j_v11_aud"), {})
    check("⑤ ledger: cada intento/job con SU clasificación y evidencia "
          "propias (⑩ cruda+estructura+confianza por fuente)",
          reg1.get("clasificacion") == "D" and reg2.get("clasificacion") == "C"
          and reg1.get("classification_confidence") == "MEDIUM"
          and reg2.get("classification_confidence") == "MEDIUM"
          and reg1.get("fuente_evidencia") == "texto_legado"
          and reg2.get("fuente_evidencia") == "texto_legado"
          and "evidencia_estructura" in reg1 and "evidencia_estructura" in reg2,
          repr((reg1.get("clasificacion"), reg1.get("classification_confidence"),
                reg2.get("clasificacion"), reg2.get("classification_confidence"))))

    print("── D.2 ⑥ reglas de adaptación por clase (con ciclo completo F→S1)")
    db.create_project(id="p_v11", title="V11", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    with db.connect() as con:
        con.execute(
            """INSERT INTO avatars(id, name, description, appearance, voice,
               tts_provider, style, created_at, updated_at)
               VALUES('av_v11','Yara','presentadora','{"piel":"Morena",
               "ojos_color":"Marrones","ropa":"Casual"}',NULL,'edge',
               'graphic-novel','2026-01-01T00:00:00+00:00',
               '2026-01-01T00:00:00+00:00')""")
        con.execute("UPDATE projects SET avatar_id='av_v11' WHERE id='p_v11'")
    _job("j_v11_id", "video", 2,
         "Yara Guayaba mira a cámara y presenta", status="dead", attempts=2,
         error="no podemos generar personas reales o su likeness")
    dec = fa.procesar_fallo_job("j_v11_id")
    f_id = _fila("j_v11_id")
    check("⑥ F identidad → S1 aplicada con datos EXISTENTES (P2 con la "
          "descripción visual del avatar)",
          dec and dec.get("accion") == "reencolar_con_p2"
          and "Morena" in (f_id["prompt_adapted"] or ""), repr(dec.get("accion")))
    check("12. P1 RAW intacto tras el ciclo completo (columna prompt)",
          f_id["prompt"] == "Yara Guayaba mira a cámara y presenta",
          repr(f_id["prompt"]))
    check("12b. P2 solo ejecución: prompt_adapted en columna separada y "
          "one-shot",
          fj.set_adapted_prompt("j_v11_id", "P2 alternativo", motivo="x") is None
          and f_id["prompt_adapted"] != "P2 alternativo")
    r_c = fa.adaptar_prompt("prompt visual", "C", {})
    check("⑥ C audio → sin adaptación del prompt visual",
          r_c["aplicada"] is False, repr(r_c))
    d_pol = fa.decidir_reintento("D", 2, "video")
    d_cop = fa.decidir_reintento("G", 2, "video")
    d_cre = fa.decidir_reintento("E", 2, "video")
    d_unu = fa.decidir_reintento("H", 2, "video")
    check("⑥ D/G → sin reintento + FLOW_ADAPTATION_REQUIRED; E/H → sin "
          "reintento operacional",
          d_pol["reintentar"] is False and d_pol.get("reporte")
          == fa.FLOW_ADAPTATION_REQUIRED
          and d_cop["reintentar"] is False and d_cop.get("reporte")
          == fa.FLOW_ADAPTATION_REQUIRED
          and d_cre["reintentar"] is False and not d_cre.get("reporte")
          and d_unu["reintentar"] is False and not d_unu.get("reporte"),
          repr((d_pol.get("reporte"), d_cop.get("reporte"),
                d_cre.get("reintentar"), d_unu.get("reintentar"))))
    d_a = fa.decidir_reintento("A", 2, "video")
    d_b = fa.decidir_reintento("B", 2, "video")
    check("⑥ A watchdog → sin extra (lease manda, sin asumir causa); B → "
          "reintento limitado sin adaptación inventada",
          d_a["reintentar"] is False and not d_a.get("reporte")
          and d_b["reintentar"] is True and d_b.get("adaptar") is None,
          repr((d_a.get("reintentar"), d_b.get("reintentar"))))

    # ════════════ E. no-invasión (13/14/15) vs ref remoto ══════════════════
    print("── E. byte-identidad del código creativo vs ref remoto (git)")
    ref = None
    for cand in ("ytgh/main", "origin/main", "upstream/main"):
        rc = subprocess.run(["git", "cat-file", "-e", cand + "^{commit}"],
                            capture_output=True)
        if rc.returncode == 0:
            ref = cand
            break
    check("ref remota resoluble para byte-identidad", ref is not None, ref)

    if ref:
        def _delta_solo_contrato(remote_bytes: bytes, local_bytes: bytes):
            """[execution-contract v1] compat: flow_export ganó el transporte
            §15 de references (hook documentado, etiquetado). La aserción
            sigue siendo DURA: solo se acepta un delta PURAMENTE ADITIVO
            cuyas líneas sean (a) etiquetadas [execution-contract v1] o (b)
            el ÚNICO helper _creative_references documentado. Cualquier otro
            cambio (replace/delete o inserción no documentada) → fallo."""
            import difflib
            rem = remote_bytes.decode("utf-8", "replace").splitlines()
            loc = local_bytes.decode("utf-8", "replace").splitlines()
            sm = difflib.SequenceMatcher(None, rem, loc)
            ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
            if not ops:
                return True, "idéntico"
            if any(op[0] != "insert" for op in ops):
                return False, ("delta no aditivo: "
                               + ",".join(sorted({op[0] for op in ops})))
            helpers = 0
            for op in ops:
                bloque = [loc[j] for j in range(op[3], op[4])]
                if all(("[execution-contract v1]" in ln) or not ln.strip()
                       for ln in bloque):
                    continue  # hook documentado (call-site §15)
                primero = next((ln for ln in bloque if ln.strip()), "")
                if primero.lstrip().startswith("def _creative_references("):
                    helpers += 1
                    continue  # ÚNICO helper documentado del transporte §15
                return False, ("inserción no documentada: "
                               + primero.strip()[:70])
            if helpers > 1:
                return False, "más de un helper insertado"
            return True, f"delta aditivo de contrato ({len(ops)} bloque(s))"

        for etiqueta, relpath, gid in (
                ("13. Creative Engine (guion_json.py)",
                 "backend/services/guion_json.py", "13"),
                ("14. Production JSON (production_json.py)",
                 "backend/services/production_json.py", "14"),
                ("15. Flow Export (backend/pipeline/flow_export.py)",
                 "backend/pipeline/flow_export.py", "15")):
            local = REPO / relpath
            remote = subprocess.run(
                ["git", "show", f"{ref}:{relpath}"],
                capture_output=True)
            igual = (remote.returncode == 0 and local.exists()
                     and remote.stdout == local.read_bytes())
            if igual:
                check(f"{etiqueta} byte-idéntico a {ref}", True)
            elif relpath.endswith("flow_export.py") and remote.returncode == 0 \
                    and local.exists():
                ok_delta, detalle = _delta_solo_contrato(remote.stdout,
                                                         local.read_bytes())
                check(f"{etiqueta} byte-idéntico a {ref} (+delta de contrato "
                      f"[execution-contract v1] documentado)", ok_delta,
                      detalle)
            else:
                check(f"{etiqueta} byte-idéntico a {ref}", False,
                      f"local={local.exists()} remote_rc={remote.returncode} "
                      f"bytes={len(remote.stdout)}")

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
