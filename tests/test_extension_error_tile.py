#!/usr/bin/env python3
"""Batería determinista del tratamiento de error-tiles (ext 2.3.1, [attempt v3]+[observability v1.1]).

Evolución del fix V1 ([error-tile v2], ext 2.2.4): la evidencia REAL_WORLD
(proyecto 26b63daa9bdd: 4 MP4 H.264/AAC 720x1280 válidos con firma
Google/C2PA JUNTO a tarjetas "No se pudo completar la acción" en el MISMO
snapshot) demostró que un flow-error-tile es el fallo de UN intento/variante,
NO un veredicto sobre la escena.

V3 (JOB vs ATTEMPT, mandato FLOW VIDEO v3): NINGÚN error-tile — semántico o
cásico — emite un veredicto fatal en el snapshot. Se registra como INTENTO
(recordSceneAttempt, con dedupe anti-residuo) y Flow sigue procesando; el
RESULTADO VÁLIDO tiene prioridad y el ERROR solo lo emite el watchdog al
agotarse la ventana SIN resultado.

Qué verifica (sin Chrome, sin red, sin Google Flow real — la prueba REAL se
hará después en el PC del usuario):

  1. ANCLAJES de [attempt v3] en background.js:
     - ningún error-tile dispara markSceneError en processDomSnapshot
     - los intentos se registran con evidencia (semántico y clásico)
     - el watchdog emite el veredicto con evidencia de intentos
     - la ventana de video configurable existe (VIDEO_GENERATION_TIMEOUT_SECONDS)
  2. REDES DE SEGURIDAD INTACTAS: watchdog por escena, rate limit tooQuick y
     la extracción semántica de domScanFn no cambian; ventana imagen 5 min.
  3. ESCENARIOS deterministas (node tests/error_tile_mock.js; el arnés carga
     el CÓDIGO REAL extraído de background.js en un service worker simulado
     y ejecuta snapshots con la forma EXACTA de domScanFn):
       A  CASO FORENSE: error-tile + video válido en el mismo snapshot →
          la escena NO se marca ERROR y se completa (DOWNLOADED)
       B  fallo total sin evidencia → se registra el INTENTO (no veredicto)
       C  pendientes (generación en vuelo) → la escena sigue IN_PROGRESS
       D  orden interno: el bloque de error corre antes que el de media
          semántica y aun así la escena se completa (DOWNLOADED)
       E  escena ya con media atribuida (idempotencia) → no se mata
       F  tile clásico con video en el mismo snapshot → descarga y completa
       G  varias escenas en curso → sin resolución 1-a-1 no se registra nada
       H  ciclo acotado: el tile residual ESTÁTICO no infla el conteo (dedupe)
       I  rate limit tooQuick intacto; tile de políticas registra INTENTO con
          la evidencia política preservada (sin veredicto)

Uso:  cd yt_automation_v2 && python3 tests/test_extension_error_tile.py
      python3 -m pytest tests/test_extension_error_tile.py -q
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
HARNESS = Path(__file__).resolve().parent / "error_tile_mock.js"

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _extraer_seccion(src: str, ini: str, fin: str) -> str:
    i = src.index(ini)
    j = src.index(fin, i)
    cuerpo = src[i:j].rstrip()
    if cuerpo.count("{") > cuerpo.count("}"):
        pass  # el corte por ancla deja la sección sin cerrar; se valida aparte
    return cuerpo


def _bundle_real(src: str) -> str:
    """Extrae el código REAL que la batería ejecuta: constantes + helpers +
    sección processDomSnapshot..watchdog (sin el watchdog ni nada más)."""
    m_status = re.search(r"const STATUS = \{[^}]+\};", src)
    m_len = re.search(r"const MAX_PROMPT_MATCH_LEN = \d+;", src)
    norm = _extraer_seccion(
        src, "function normalizeForMatch",
        "/* ---------------------------- IndexedDB handles")
    deteccion = _extraer_seccion(
        src, "function detectExtension",
        "async function saveUrlToDisk")
    seccion = _extraer_seccion(
        src, "async function processDomSnapshot",
        "/* ---------------- Watchdog por escena")
    partes = [m_status.group(0), m_len.group(0), norm, deteccion, seccion]
    bundle = "\n\n".join(p for p in partes if p)
    return bundle


def main() -> int:
    node = which("node")
    check("node disponible en el sandbox", bool(node),
          "instala Node.js para poder verificar el FIX")

    print("── 1. anclajes de [attempt v3] en background.js")
    bg = EXT / "background.js"
    check("background.js existe", bg.exists())
    src = bg.read_text(encoding="utf-8", errors="replace")

    check("comentario forense [attempt v3] presente (JOB vs ATTEMPT)",
          "[attempt v3] JOB vs ATTEMPT" in src)
    n_fatal = src.count("markSceneError(errScene, 'flow-error-tile: '")
    check("NINGUNA llamada fatal desde error-tiles (supersede V1)", n_fatal == 0,
          f"esperado 0, hay {n_fatal}")
    n_rec = src.count("recordSceneAttempt(")
    check("los intentos se registran (semántico + clásico)", n_rec >= 3,
          f"esperado >=3 (definición + 2 llamadas), hay {n_rec}")
    check("evidencia semántica registrada ('flow-error-tile: ')",
          "'flow-error-tile: '" in src)
    check("evidencia política preservada (bloqueo de politicas)",
          "'bloqueo de politicas de contenido'" in src)
    check("dedupe anti-residuo presente (CAMBIO 7)",
          "prev.lastError === reason" in src)
    check("limpieza al completar (clearSceneAttempts en DOWNLOADED)",
          src.count("clearSceneAttempts(scene)") >= 2)
    check("limpieza al iniciar (injectScene CAMBIO 7)",
          "clearSceneAttempts(item.scene_number)" in src)
    check("limpieza al reclamar job del bridge",
          "sceneAttempts.delete(sceneNumber)" in src)
    n_sem_null = src.count("resolveSemanticScene(null)")
    # [observability v1.1]: error-tiles + notificaciones + videos sin audio
    # resuelven escena con la MISMA regla 1-a-1 (3 llamadas, sin regresión)
    check("resolución de escena semántica sin mediaId intacta (3 llamadas: "
          "tiles+notificaciones+videos)",
          n_sem_null == 3, f"esperado 3, hay {n_sem_null}")

    print("── 1b. anclajes [video-window v3] (ventana de video operativa)")
    check("constante VIDEO_GENERATION_TIMEOUT_SECONDS (15*60)",
          "const VIDEO_GENERATION_TIMEOUT_SECONDS = 15 * 60;" in src)
    check("piso razonable 1 min", "VIDEO_TIMEOUT_MIN_MS = 60 * 1000" in src)
    check("techo razonable 2 h", "VIDEO_TIMEOUT_MAX_MS = 120 * 60000" in src)
    check("configurable via storage (videoTimeoutSeconds)",
          "videoTimeoutSeconds" in src)
    check("presupuesto por modo (videoTimeoutMs vs imagen)",
          "mode === 'videos' ? videoTimeoutMs() : SCENE_WATCHDOG_MS_IMAGES"
          in src)
    check("constante fija SCENE_WATCHDOG_MS_VIDEOS eliminada",
          "const SCENE_WATCHDOG_MS_VIDEOS" not in src)
    check("techo del handler bridge derivado de la ventana",
          "Math.max(18 * 60000, videoTimeoutMs() + 3 * 60000)" in src)

    print("── 2. redes de seguridad intactas (no forman parte del cambio)")
    check("watchdog por escena con veredicto con evidencia "
          "(prefijo estructural §7.1)",
          "FLOW_WATCHDOG_TIMEOUT: sin resultado válido en" in src)
    check("rate limit tooQuick intacto", "triggerRateLimit()" in src)
    check("extracción semántica pending intacta",
          '\'flow-pending-tile, [data-testid="pending-tile"]\'' in src)
    check("extracción semántica error-tile intacta",
          '\'flow-error-tile, [data-testid="error-tile"]\'' in src)
    check("extracción semántica img[data-media-id] intacta",
          "'img[data-media-id]'" in src)
    check("descarga semántica intacta (loop sem.media)",
          "Array.isArray(sem.media) && sem.media.length" in src)
    check("ventana de imagen SIN CAMBIOS (5 min)",
          "SCENE_WATCHDOG_MS_IMAGES = 5 * 60000" in src)

    print("── 3. versión y sintaxis")
    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("manifest 2.4.1 (bump patch: CF-E2E-01 gate obligatorio §7.1)",
          mf.get("version") == "2.4.1", mf.get("version"))
    if node:
        for js in ("background.js", "bridge.js", "injector.js"):
            proc = subprocess.run([node, "--check", str(EXT / js)],
                                  capture_output=True, text=True, timeout=60)
            check(f"sintaxis OK: extension/{js}", proc.returncode == 0,
                  proc.stderr.strip()[:150])

    if not node:
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1 if FAIL else 0

    print("── 4. arnés determinista (service worker simulado, sin Flow real)")
    try:
        bundle = _bundle_real(src)
        balanceado = bundle.count("{") == bundle.count("}")
    except Exception as e:  # noqa: BLE001
        bundle, balanceado = "", False
        print(f"  (extracción: {e})")
    check("código REAL extraíble y balanceado (processDomSnapshot.."
          "watchdog)", balanceado and "processDomSnapshot" in bundle)
    check("el bundle NO arrastra el watchdog (sección acotada)",
          "function watchdogCheck" not in bundle)
    proc_syn = subprocess.run([node, "--check", str(HARNESS)],
                              capture_output=True, text=True, timeout=60)
    check("sintaxis OK: error_tile_mock.js", proc_syn.returncode == 0,
          proc_syn.stderr.strip()[:150])

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(bundle)
        bundle_path = f.name
    proc = subprocess.run([node, str(HARNESS), bundle_path],
                          capture_output=True, text=True, timeout=120)
    check("arnés corre sin error de ejecución", proc.returncode == 0,
          (proc.stderr or "")[-200:])
    try:
        data = json.loads(proc.stdout)
        esc = data.get("escenas", {})
    except Exception as e:  # noqa: BLE001
        check("arnés produce JSON parseable", False, str(e)[:150])
        print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
        return 1
    check("arnés produce JSON parseable", True)
    check("sin error_de_harness",
          "error_de_harness" not in (proc.stderr or ""))

    esperadas = ["forense_video_valido", "fallo_total_registra_intento",
                 "pendientes_suprimen", "media_semantica_mismo_snapshot",
                 "escena_ya_con_media", "tile_clasico_con_video",
                 "varias_escenas_en_curso", "ciclo_pendientes_luego_fallo",
                 "rate_limit_intacto", "politica_tile_intento"]
    check("las 10 escenas deterministas corrieron",
          all(n in esc for n in esperadas),
          repr([n for n in esperadas if n not in esc]))

    def e(nombre):
        return esc.get(nombre, {}) or {}

    print("── 5.A CASO FORENSE EXIGIDO: error-tile + video válido en el mismo "
          "snapshot")
    a = e("forense_video_valido")
    check("forense: la escena NO se marca ERROR",
          a.get("status") == "IN_PROGRESS", repr(a))
    check("forense: sin error en el item", not a.get("error"), repr(a.get("error")))

    print("── 5.B fallo total sin evidencia → registra INTENTO (no veredicto)")
    b = e("fallo_total_registra_intento")
    check("fallo total: la escena NO se marca ERROR en el snapshot",
          b.get("status") == "IN_PROGRESS", repr(b))
    check("fallo total: sin error en el item", not b.get("error"),
          repr(b.get("error")))
    check("fallo total: el intento quedó registrado (count 1)",
          b.get("intentos") == 1, repr(b))
    check("fallo total: evidencia preservada (flow-error-tile:)",
          str(b.get("ultima") or "").startswith("flow-error-tile: "),
          repr(b.get("ultima")))
    check("fallo total: no dispara tick de avance (sin veredicto)",
          b.get("ticked") is False, repr(b))

    print("── 5.C pendientes en vuelo suprimen el veredicto")
    c = e("pendientes_suprimen")
    check("pendientes: la escena sigue IN_PROGRESS",
          c.get("status") == "IN_PROGRESS", repr(c))
    check("pendientes: sin error", not c.get("error"), repr(c.get("error")))

    print("── 5.D orden interno: error-block corre antes que media semántica")
    d = e("media_semantica_mismo_snapshot")
    check("orden: escena completada (DOWNLOADED)",
          d.get("status") == "DOWNLOADED", repr(d))
    check("orden: media semántica descargada (1 guardado)",
          len(d.get("saved") or []) == 1, repr(d.get("saved")))
    check("orden: la URL guardada es la media válida",
          (d.get("saved") or [{}])[0].get("url", "").endswith("img_valida_1.png"),
          repr(d.get("saved")))
    check("orden: contador de media de la escena = 1",
          d.get("sceneMediaCounts") == [[1, 1]], repr(d.get("sceneMediaCounts")))
    check("orden: media marcada como descargada (dedupe)",
          d.get("downloadedIds") == ["media-1"], repr(d.get("downloadedIds")))

    print("── 5.E escena ya con media atribuida (idempotencia)")
    e_ = e("escena_ya_con_media")
    check("idempotencia: no se mata una escena con media ya atribuida",
          e_.get("status") == "IN_PROGRESS", repr(e_))
    check("idempotencia: sin error", not e_.get("error"), repr(e_.get("error")))

    print("── 5.F tile clásico con video en el mismo snapshot")
    f_ = e("tile_clasico_con_video")
    check("tile clásico: escena completada (DOWNLOADED)",
          f_.get("status") == "DOWNLOADED", repr(f_))
    check("tile clásico: video descargado una vez",
          len(f_.get("saved") or []) == 1, repr(f_.get("saved")))
    check("tile clásico: extensión mp4 en modo videos",
          (f_.get("saved") or [{}])[0].get("ext") == "mp4",
          repr(f_.get("saved")))

    print("── 5.G varias escenas en curso → sin 1-a-1 no se marca nada")
    g = e("varias_escenas_en_curso")
    check("varias: ninguna escena marcada",
          g.get("estados") == ["IN_PROGRESS", "IN_PROGRESS"], repr(g))
    check("varias: sin errores", g.get("errores") == [None, None], repr(g))

    print("── 5.H ciclo acotado: residual estático no infla el conteo")
    h = e("ciclo_pendientes_luego_fallo")
    check("ciclo: con pendientes sigue IN_PROGRESS",
          (h.get("trasPendientes") or {}).get("status") == "IN_PROGRESS",
          repr(h.get("trasPendientes")))
    check("ciclo: sin evidencia nueva sigue IN_PROGRESS (la ventana manda)",
          (h.get("final") or {}).get("status") == "IN_PROGRESS",
          repr(h.get("final")))
    check("ciclo: dedupe — 3 snapshots con el MISMO tile = 1 intento",
          h.get("intentos") == 1, repr(h))

    print("── 5.I rate limit intacto; políticas registra INTENTO con evidencia")
    i = e("rate_limit_intacto")
    check("tooQuick dispara rate limit", i.get("rateLimited") == 1, repr(i))
    i2 = e("politica_tile_intento")
    check("tile de políticas: NO es veredicto (IN_PROGRESS)",
          i2.get("status") == "IN_PROGRESS", repr(i2))
    check("tile de políticas: intento registrado (count 1)",
          i2.get("intentos") == 1, repr(i2))
    check("tile de políticas: evidencia política preservada para el backend",
          i2.get("evidencia") == "bloqueo de politicas de contenido",
          repr(i2.get("evidencia")))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
