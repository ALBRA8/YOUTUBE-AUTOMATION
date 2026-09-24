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
