"""
YOUTUBE AUTOMATION v2.1.2 — Doctor de salud del stack $0
Patrón probe_command (Agent-Reach): cada check es una sonda REAL ejecutada
en el momento, no una suposición. El doctor se lee desde el dashboard y dice
exactamente qué falta y cómo arreglarlo, sin tocar el código.

GET /api/doctor → {ok, checks:[{id, ok, detail, hint, warn?}], summary}
Filosofía $0: la ausencia de GEMINI_API_KEY o yt-dlp NO es un fallo (el
sistema degrada con gracia); ffmpeg/edge-tts/disco sí son críticos.
"""
import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

import config

log = logging.getLogger("doctor")

# Umbrales de disco (GB libres)
DISK_FAIL_GB = 1.0
DISK_WARN_GB = 5.0


def _probe_version(cmd: list[str]) -> str | None:
    """Ejecuta una sonda real de versión; None si el binario no responde."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if p.returncode == 0:
            first = (p.stdout or "").strip().splitlines()
            return (first[0][:90] if first else "ok")
    except Exception:  # noqa: BLE001
        pass
    return None


def _import_ok(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001
        return False


def _disk_report(d: Path) -> tuple[bool, bool, str]:
    """(writable, warn_or_fail, detalle)"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".doctor_probe"
        probe.write_bytes(b"ok")
        probe.unlink()
        free_gb = shutil.disk_usage(d).free / 1e9
        if free_gb < DISK_FAIL_GB:
            return True, False, f"escritura OK · solo {free_gb:.1f} GB libres (CRÍTICO)"
        if free_gb < DISK_WARN_GB:
            return True, True, f"escritura OK · {free_gb:.1f} GB libres (bajo)"
        return True, True, f"escritura OK · {free_gb:.1f} GB libres"
    except Exception as e:  # noqa: BLE001
        return False, False, str(e)


def _run_checks() -> list[dict]:
    out: list[dict] = []

    def add(cid: str, ok: bool, detail: str, hint: str = "",
            critical: bool = False) -> None:
        item = {"id": cid, "ok": ok, "detail": detail, "hint": hint}
        if not ok and not critical:
            item["warn"] = True  # degradación graceful: no rompe el pipeline
        out.append(item)

    # ── Críticos (sin ellos no hay video) ─────────────────────────────────
    v = _probe_version(["ffmpeg", "-version"])
    add("ffmpeg", bool(v), v or "binario no responde",
        "instala ffmpeg: sudo apt install ffmpeg (Linux) / winget install ffmpeg (Windows)",
        critical=True)

    v = _probe_version(["ffprobe", "-version"])
    add("ffprobe", bool(v), v or "binario no responde (viene con ffmpeg)",
        "reinstala ffmpeg completo", critical=True)

    ok_dir, disk_ok, disk_detail = _disk_report(config.OUTPUT_DIR)
    add("output_dir", ok_dir and disk_ok, disk_detail,
        "libera espacio o cambia OUTPUT_DIR", critical=True)

    # ── TTS ───────────────────────────────────────────────────────────────
    add("edge_tts", _import_ok("edge_tts"),
        "importable" if _import_ok("edge_tts") else "no instalado",
        "pip install edge-tts (voz neuronal 100% gratis)", critical=True)

    key = config.GEMINI_API_KEY
    add("gemini_key", bool(key),
        ("presente (" + key[:4] + "…)" if key else "no configurada"),
        "guárdala en ⚙️ Configuración del dashboard o en .env GEMINI_API_KEY")

    add("google_genai", _import_ok("google.genai"),
        "importable" if _import_ok("google.genai") else "no instalado",
        "pip install google-genai (TTS/imagen/texto premium)")

    prov = (config.TTS_PROVIDER or "edge").strip().lower()
    add("tts_provider", True, f"proveedor activo: {prov}"
        + (" (batched 15 escenas/llamada activo)" if prov == "gemini" else ""))

    # ── Alineación de subtítulos ──────────────────────────────────────────
    wh_ok = _import_ok("faster_whisper")
    add("faster_whisper", wh_ok,
        ("modelo configurado: " + config.WHISPER_MODEL if wh_ok else "no instalado"),
        "pip install faster-whisper (alineación palabra-palabra Hormozi)")

    # ── PyAV: motor interno de faster-whisper ─────────────────────────────
    # v2.15.1 · PyAV 19 eliminó metadata_errors, que faster-whisper 1.2.1
    # aún pasa a av.open() → TypeError «open() got an unexpected keyword
    # argument 'metadata_errors'» que tumbaba el pipeline en el paso TTS.
    if wh_ok:
        av_ok = _import_ok("av")
        av_ver = None
        if av_ok:
            try:
                from importlib.metadata import version as _pkg_version
                av_ver = _pkg_version("av")
            except Exception:  # noqa: BLE001
                av_ver = "?"
        try:
            av_major = int(str(av_ver).split(".")[0])
        except ValueError:
            av_major = 0
        add("pyav", av_ok and 0 < av_major < 19,
            f"av {av_ver}" if av_ok else "no instalado (faster-whisper no puede decodificar audio)",
            'pip install "av>=11,<19"' if (not av_ok or av_major >= 19)
            else "compatible con faster-whisper 1.2.1")

    # ── Investigación de tendencias ($0, sin API key) ─────────────────────
    ytdlp_ok = _import_ok("yt_dlp")
    if not ytdlp_ok:
        from services.url_mode import ytdlp_cmd  # resolvedor robusto (venv/PATH)
        v = _probe_version([*ytdlp_cmd(), "--version"])
        ytdlp_ok = bool(v)
    add("yt_dlp", ytdlp_ok,
        "disponible" if ytdlp_ok else "no instalado",
        "pip install yt-dlp (investigación de tendencias sin API key)")

    # ── Placeholder de imágenes ───────────────────────────────────────────
    add("pillow", _import_ok("PIL"),
        "importable" if _import_ok("PIL") else "no instalado",
        "pip install pillow (placeholders elegantes sin Gemini)")

    # ── YouTube autopublish ───────────────────────────────────────────────
    cs = Path(config.YT_CLIENT_SECRET)
    tok = Path(config.YT_TOKEN_FILE)
    add("youtube_oauth", tok.exists(),
        "token.json presente" if tok.exists()
        else (f"client_secret {'sí' if cs.exists() else 'no'} · falta autorizar"),
        "dashboard → Publicar → Conectar YouTube")

    return out


async def run_doctor() -> dict:
    """Ejecuta todas las sondas (en un hilo: subprocess bloqueante) y
    devuelve el informe estructurado para el dashboard."""
    checks = await asyncio.to_thread(_run_checks)
    fails = sum(1 for c in checks if not c["ok"] and "warn" not in c)
    warns = sum(1 for c in checks if not c["ok"] and "warn" in c)
    return {
        "ok": fails == 0,
        "checks": checks,
        "summary": {"total": len(checks), "ok": len(checks) - fails - warns,
                    "warn": warns, "fail": fails},
    }


# ── INT-082 · preflight ligero del botón Crear (mejora 3 del informe en vivo) ──
# El caso real verificado en producción: «El imperio romano» murió en el paso
# de locución porque el proveedor TTS no estaba disponible; el preflight de
# producto actuó bien PERO avisó DESPUÉS de gastar guion e imágenes. Este
# guarda ligero responde en milisegundos (sin subprocess ni red) y se consulta
# desde el panel ANTES de crear/lanzar un proyecto. Filosofía coherente con el
# doctor: solo bloquea lo que MATA un proyecto ya iniciado (TTS, ffmpeg);
# lo que degrada con gracia (placeholders, subtítulos) es warn.

def run_preflight_creacion() -> dict:
    """Preflight de creación: {ok, blockers[], warns[], summary, tts_provider}.
    - blockers: producir HOY dejaría un proyecto mudo o sin render.
    - warns: el sistema degrada con gracia; avisar sin bloquear."""
    blockers: list[dict] = []
    warns: list[dict] = []

    def block(cid: str, detail: str, hint: str = "") -> None:
        blockers.append({"id": cid, "detail": detail, "hint": hint})

    def soft(cid: str, detail: str, hint: str = "") -> None:
        warns.append({"id": cid, "detail": detail, "hint": hint})

    # ── TTS: la voz ES el caso raíz del informe — un proyecto sin locución
    #    no puede pasar el preflight de producto y muere con recursos gastados.
    prov = (config.TTS_PROVIDER or "edge").strip().lower()
    if prov == "gemini":
        if not config.GEMINI_API_KEY:
            block("tts", "locución configurada con Gemini pero GEMINI_API_KEY "
                         "no está presente",
                  "guárdala en ⚙️ Ajustes del panel o en .env GEMINI_API_KEY")
        elif not _import_ok("google.genai"):
            block("tts", "clave Gemini presente pero google-genai no está "
                         "instalable",
                  "pip install google-genai")
    elif not _import_ok("edge_tts"):
        block("tts", "proveedor de voz edge-tts no está instalado: el proyecto "
                     "quedaría MUDO y moriría en el paso de locución",
              "pip install edge-tts (voz neuronal 100% gratis)")

    # ── Render final: sin ffmpeg no hay video aunque todo lo demás funcione
    if not shutil.which("ffmpeg"):
        block("ffmpeg", "ffmpeg no está disponible: el pipeline nunca podría "
                        "renderizar el MP4 final",
              "sudo apt install ffmpeg (Linux) / winget install ffmpeg (Windows)")
    if not shutil.which("ffprobe"):
        block("ffprobe", "ffprobe no está disponible (viene con ffmpeg)",
              "reinstala ffmpeg completo")

    # ── Degradaciones elegantes → warn (nunca bloquean la creación)
    if not config.GEMINI_API_KEY:
        if _import_ok("PIL"):
            soft("imagen", "sin GEMINI_API_KEY: las escenas usarán placeholders "
                           "locales en vez de imágenes IA",
                 "opcional: guarda tu clave Gemini en ⚙️ Ajustes para imágenes "
                 "reales")
        else:
            soft("imagen", "sin GEMINI_API_KEY ni pillow: las escenas quedarían "
                           "sin imagen",
                 "pip install pillow y/o guarda tu clave Gemini")
    if not _import_ok("faster_whisper"):
        soft("subtitulos", "faster-whisper no instalado: subtítulos sin "
                           "alineación palabra a palabra",
             "pip install faster-whisper (opcional, estilo Hormozi)")

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warns": warns,
        "summary": {"blockers": len(blockers), "warns": len(warns)},
        "tts_provider": prov,
    }
