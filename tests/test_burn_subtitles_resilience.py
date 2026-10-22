#!/usr/bin/env python3
"""BATERÍA — burn_subtitles resiliente (INT-012).

Verifica el punto exacto del incidente HARD E2E `_hard_e2e_c2_01`
(INT-012): el quemado de subtítulos con libass+libx264 sobre 4K superó
los 900 s y el TimeoutExpired — no capturado — tumbó el pipeline completo
aunque el render previo era válido.

Cobertura (hermética, sin ffmpeg real — _run_ffmpeg simulado):
  1. El comando de quemado usa -preset veryfast (coherente con el resto
     del módulo) y mantiene timeout=900.
  2. Éxito (rc=0) → subs_status.json burned=true.
  3. Fallo ffmpeg (rc!=0) → degradación honesta burned=false (guard).
  4. TimeoutExpired → MISMA degradación honesta (copia raw + burned=false
     con razón timeout), sin excepción al orquestador.
  5. words.json vacío → copia sin subtítulos (guard).
  6. La degradación por timeout sobreescribe un MP4 final parcial dejado
     por el proceso muerto (el archivo final siempre queda válido).

Nada de este archivo toca producción real, Google Flow ni red.
"""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="burn_subs_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import pipeline.video as video  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


WORDS = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.45}
         for i, w in enumerate(["esto", "es", "una", "prueba", "de", "quemado"])]


def _project(pid="burn_t", fmt="short"):
    return {"id": pid, "format": fmt, "meta": {}}


def _setup(pid):
    proj_dir = _cfg.OUTPUT_DIR / pid
    proj_dir.mkdir(parents=True, exist_ok=True)
    raw = proj_dir / "video_raw.mp4"
    raw.write_bytes(b"FAKE_MP4_BYTES")  # solo se copia; no se codifica
    words_path = proj_dir / "words_timeline.json"
    words_path.write_text(json.dumps(WORDS), encoding="utf8")
    return raw, words_path


def _subs_status(pid):
    return json.loads((_cfg.OUTPUT_DIR / pid / "subs_status.json").read_text())


# ── 1. preset veryfast + timeout 900 ────────────────────────────────────
captured = {}


def _capture_run(cmd, timeout=900):
    captured["cmd"] = list(cmd)
    captured["timeout"] = timeout
    return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")


_orig_run = video._run_ffmpeg
video._run_ffmpeg = _capture_run
raw, words = _setup("burn_preset")
final = asyncio.run(video.burn_subtitles(_project("burn_preset"), raw, words))
cmd = captured["cmd"]
check("comando incluye -preset veryfast",
      "-preset" in cmd and cmd[cmd.index("-preset") + 1] == "veryfast", str(cmd))
check("timeout se mantiene en 900 s", captured["timeout"] == 900,
      str(captured.get("timeout")))
check("éxito registra burned=true", _subs_status("burn_preset")["burned"] is True)
check("filtro ass aplicado", any(a.startswith("ass=") for a in cmd), str(cmd))
check("audio se copia sin recodificar",
      cmd[cmd.index("-c:a") + 1] == "copy", str(cmd))

# ── 2. fallo ffmpeg rc!=0 → degradación honesta (guard de comportamiento) ──
def _fail_run(cmd, timeout=900):
    return subprocess.CompletedProcess(cmd, returncode=1, stdout="",
                                       stderr="libass no disponible")


video._run_ffmpeg = _fail_run
raw, words = _setup("burn_rc1")
final = asyncio.run(video.burn_subtitles(_project("burn_rc1"), raw, words))
st = _subs_status("burn_rc1")
check("rc!=0 NO lanza excepción y devuelve final",
      final == _cfg.OUTPUT_DIR / "burn_rc1" / "burn_rc1_final.mp4")
check("rc!=0 registra burned=false", st["burned"] is False)
check("rc!=0 registra razón con rc", "rc=1" in st["reason"], st["reason"])
check("rc!=0 deja copia del raw como final",
      final.read_bytes() == b"FAKE_MP4_BYTES")

# ── 3. TimeoutExpired → misma degradación honesta (el fix INT-012) ──────
def _timeout_run(cmd, timeout=900):
    raise subprocess.TimeoutExpired(cmd, timeout)


video._run_ffmpeg = _timeout_run
raw, words = _setup("burn_timeout")
# simula el MP4 parcial que el proceso muerto pudo dejar a medias:
(_cfg.OUTPUT_DIR / "burn_timeout" / "burn_timeout_final.mp4").write_bytes(
    b"PARTIAL_CORRUPT_MP4")
final = asyncio.run(video.burn_subtitles(_project("burn_timeout"), raw, words))
st = _subs_status("burn_timeout")
check("timeout NO lanza excepción al orquestador", True)  # llegó hasta aquí
check("timeout devuelve ruta final válida",
      final == _cfg.OUTPUT_DIR / "burn_timeout" / "burn_timeout_final.mp4")
check("timeout registra burned=false", st["burned"] is False)
check("timeout registra razón 'timeout'", "timeout" in st["reason"].lower(),
      st["reason"])
check("timeout sobreescribe el MP4 parcial corrupto del proceso muerto",
      final.read_bytes() == b"FAKE_MP4_BYTES",
      final.read_bytes()[:20].decode("utf8", "replace"))

# ── 4. words.json vacío → copia sin quemar (guard) ──────────────────────
video._run_ffmpeg = _orig_run
raw, words = _setup("burn_empty")
words.write_text("[]", encoding="utf8")
final = asyncio.run(video.burn_subtitles(_project("burn_empty"), raw, words))
st = _subs_status("burn_empty")
check("words vacío no llama a ffmpeg (ni lanza)", st["burned"] is False)
check("words vacío registra razón explícita",
      "vacío" in st["reason"], st["reason"])

video._run_ffmpeg = _orig_run
print(f"\n{'=' * 60}")
print(f"RESULTADO: {OK} OK · {FAIL} fallos")
sys.exit(1 if FAIL else 0)
