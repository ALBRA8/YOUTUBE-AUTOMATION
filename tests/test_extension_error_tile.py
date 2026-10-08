#!/usr/bin/env python3
"""Batería determinista del FIX error-tile ([error-tile v2], ext 2.2.4).

Falso positivo corregido (prueba REAL, proyecto 26b63daa9bdd): Google Flow SÍ
generó correctamente los videos (≥4 MP4 H.264/AAC 720x1280 de 8 s con firma
C2PA/SynthID de Google, con el texto del prompt de la prueba dentro de los
frames), pero la extensión marcó la escena como ERROR porque el snapshot del
DOM contenía un <flow-error-tile> (fallo de UN intento/variante) y el bloque
PLAN B de background.js lo trataba como fallo fatal sin mirar la evidencia de
resultados del mismo snapshot.

Qué verifica (sin Chrome, sin red, sin Google Flow real — la prueba REAL se
hará después en el PC del usuario):

  1. ANCLAJES del FIX en background.js:
     - el error-tile solo es FATAL si NO hay evidencia de resultados:
       sin media/video visible en el snapshot, sin tiles pendientes y sin
       media ya atribuida a la escena candidata
     - comentario forense del FIX presente; una sola llamada fatal
  2. REDES DE SEGURIDAD INTACTAS: watchdog por escena, error de políticas por
     tile clásico (texto infringement/policy), rate limit tooQuick y la
     extracción semántica de domScanFn no cambian.
  3. ESCENARIOS deterministas (node tests/error_tile_mock.js; el arnés carga
     el CÓDIGO REAL extraído de background.js — processDomSnapshot,
     resolveSemanticScene, resolveSceneForTile, markSceneError,
     normalizeForMatch, detectExtension, STATUS — en un service worker
     simulado y ejecuta snapshots con la forma EXACTA de domScanFn):
       A  CASO FORENSE EXIGIDO: error-tile + video válido en el mismo
          snapshot → la escena NO se marca ERROR (antes: falso positivo)
       B  fallo total sin evidencia → sigue siendo FATAL (la cobertura
          original no se pierde)
       C  pendientes (generación en vuelo) → suprimen el veredicto fatal
       D  orden interno: el bloque de error corre antes que el de media
          semántica y aun así la escena se completa (DOWNLOADED)
       E  escena ya con media atribuida (idempotencia) → no se mata
       F  tile clásico con video en el mismo snapshot → descarga y completa
          sin falso positivo
       G  varias escenas en curso → sin resolución 1-a-1 no se marca nada
       H  ciclo acotado: pendientes difieren el veredicto, no lo cancelan
       I  rate limit tooQuick y tile de políticas intactos

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
    sección processDomSnapshot..markSceneError (sin el watchdog ni nada más)."""
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

    print("── 1. anclajes del FIX en background.js")
    bg = EXT / "background.js"
    check("background.js existe", bg.exists())
    src = bg.read_text(encoding="utf-8", errors="replace")

    check("comentario forense del FIX presente ([error-tile v2])",
          "[error-tile v2] FIX falso positivo" in src)
    guard = ("if (errScene != null && !hayMediaVisible && !hayPendientes"
             " && !escenaConMedia) {")
    check("guard de evidencia presente (media visible / pendientes / media "
          "ya atribuida)", guard in src, "ancla no encontrada")
    check("evidencia por tiles clásicos (hayMediaEnTiles)", "hayMediaEnTiles" in src)
    check("evidencia semántica de video (sem.videos)", "sem.videos.length > 0" in src)
    check("evidencia semántica de imagen (sem.media)", "sem.media.length > 0" in src)
    check("pendientes en vuelo (sem.pending)", "(sem.pending || 0) > 0" in src)
    check("media ya atribuida a la escena (sceneMediaCounts)",
          "(sceneMediaCounts.get(errScene) || 0) > 0" in src)
    n_fatal = src.count("markSceneError(errScene, 'flow-error-tile: '")
    check("exactamente UNA llamada fatal flow-error-tile", n_fatal == 1,
          f"esperado 1, hay {n_fatal}")
    n_sem_null = src.count("resolveSemanticScene(null)")
    check("resolución de escena semántica sin mediaId intacta (1 llamada)",
          n_sem_null == 1, f"esperado 1, hay {n_sem_null}")

    print("── 2. redes de seguridad intactas (no forman parte del FIX)")
    check("error de políticas por tile clásico intacto",
          "'bloqueo de politicas de contenido'" in src)
    check("watchdog por escena intacto",
          "watchdog: generación atascada" in src)
    check("rate limit tooQuick intacto", "triggerRateLimit()" in src)
    check("extracción semántica pending intacta",
          '\'flow-pending-tile, [data-testid="pending-tile"]\'' in src)
    check("extracción semántica error-tile intacta",
          '\'flow-error-tile, [data-testid="error-tile"]\'' in src)
    check("extracción semántica img[data-media-id] intacta",
          "'img[data-media-id]'" in src)
    check("descarga semántica intacta (loop sem.media)",
          "Array.isArray(sem.media) && sem.media.length" in src)

    print("── 3. versión y sintaxis")
    mf = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("manifest 2.2.4 (bump de parche, sin salto mayor)",
          mf.get("version") == "2.2.4", mf.get("version"))
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
          "markSceneError)", balanceado and "processDomSnapshot" in bundle)
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

    esperadas = ["forense_video_valido", "fallo_total_fatal",
                 "pendientes_suprimen", "media_semantica_mismo_snapshot",
                 "escena_ya_con_media", "tile_clasico_con_video",
                 "varias_escenas_en_curso", "ciclo_pendientes_luego_fallo",
                 "rate_limit_intacto", "politica_tile_intacta"]
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

    print("── 5.B fallo total sin evidencia → sigue siendo fatal")
    b = e("fallo_total_fatal")
    check("fallo total: status ERROR",
          b.get("status") == "ERROR", repr(b))
    check("fallo total: causa flow-error-tile",
          str(b.get("error", "")).startswith("flow-error-tile: "),
          repr(b.get("error")))
    check("fallo total: avanza la cola (tickSoon)", b.get("ticked") is True)

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

    print("── 5.H ciclo acotado: pendientes difieren, no cancelan")
    h = e("ciclo_pendientes_luego_fallo")
    check("ciclo: con pendientes sigue IN_PROGRESS",
          (h.get("trasPendientes") or {}).get("status") == "IN_PROGRESS",
          repr(h.get("trasPendientes")))
    check("ciclo: al agotarse pendientes y evidencia → ERROR",
          (h.get("final") or {}).get("status") == "ERROR",
          repr(h.get("final")))
    check("ciclo: causa flow-error-tile",
          str((h.get("final") or {}).get("error", "")).startswith(
              "flow-error-tile: "), repr((h.get("final") or {}).get("error")))

    print("── 5.I rate limit y políticas intactos")
    i = e("rate_limit_intacto")
    check("tooQuick dispara rate limit", i.get("rateLimited") == 1, repr(i))
    i2 = e("politica_tile_intacta")
    check("tile de políticas sigue siendo fatal",
          i2.get("status") == "ERROR", repr(i2))
    check("tile de políticas: causa correcta",
          i2.get("error") == "bloqueo de politicas de contenido",
          repr(i2.get("error")))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
