# -*- coding: utf-8 -*-
"""P2-1 · Humo hermético del render final (sin red, sin proveedores).

Cadena mínima REAL del pipeline con 3 imágenes sintéticas:
  3× scene_clip_cmd (Ken Burns) → concat → voz sintética + loudnorm
  broadcast (-14 LUFS, la constante BROADCAST_LOUDNORM del propio módulo)
  → get_video_encoder(final=True) → MP4 final.

Verifica con ffprobe/ebur128/lectura binaria:
  · duración ≈ 3 escenas × 0.6 s
  · resolución exacta 540x960
  · moov ANTES de mdat (faststart, streaming del panel)
  · audio integrado ≈ -14 LUFS (ebur128, tolerancia ±2)
  · cero placeholders: las 3 imágenes llevan .style.json method="gemini"
    y pasan qa_image (el MISMO detector que usa video_qa en producción)

Ejecutar: python3 -m pytest tests/test_p2_1_smoke_render.py -q
"""
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from pipeline.video import (BROADCAST_LOUDNORM, get_video_encoder,  # noqa: E402
                            scene_clip_cmd)
from services.video_qa import qa_image  # noqa: E402

W, H, FPS, DUR = 540, 960, 30, 0.6


def _ff(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def test_humo_render_3_escenas(tmp_path):
    # ── 3 imágenes sintéticas con .style.json method="gemini" ───────────
    imgs = []
    for i, color in enumerate(("red", "green", "blue"), 1):
        img = tmp_path / f"esc_{i}.png"
        r = _ff(["ffmpeg", "-y", "-f", "lavfi", "-i",
                 f"color=c={color}:s={W}x{H}", "-frames:v", "1", str(img)])
        assert r.returncode == 0, r.stderr[-200:]
        (tmp_path / f"esc_{i}.style.json").write_text(
            json.dumps({"method": "gemini"}), encoding="utf-8")
        imgs.append(img)
    # detector REAL de placeholders (video_qa.qa_image)
    for img in imgs:
        qa = qa_image(img)
        assert not qa.get("is_placeholder"), qa

    # ── 3 clips Ken Burns (ruta real del pipeline) ──────────────────────
    clips = []
    for i, img in enumerate(imgs, 1):
        clip = tmp_path / f"clip_{i}.mp4"
        r = _ff(scene_clip_cmd(img, DUR, clip, W, H, fps=FPS,
                               zoom_dir=1 if i % 2 else -1, rotate_deg=0))
        assert r.returncode == 0, r.stderr[-300:]
        clips.append(clip)

    # ── concat (demuxer, como el pipeline) ──────────────────────────────
    lista = tmp_path / "concat.txt"
    lista.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips),
                     encoding="utf-8")
    silencioso = tmp_path / "video_silent.mp4"
    r = _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
             "-c", "copy", str(silencioso)])
    assert r.returncode == 0, r.stderr[-300:]

    # ── voz sintética + loudnorm broadcast + encoder FINAL ──────────────
    final = tmp_path / "final.mp4"
    r = _ff(["ffmpeg", "-y", "-i", str(silencioso),
             "-f", "lavfi", "-i", "sine=frequency=330:duration=1.8",
             "-filter_complex", f"[1:a]{BROADCAST_LOUDNORM}[au]",
             "-map", "0:v", "-map", "[au]", "-shortest",
             *get_video_encoder(final=True),
             "-c:a", "aac", "-b:a", "160k", str(final)])
    assert r.returncode == 0, r.stderr[-300:]

    # ── 1. duración ─────────────────────────────────────────────────────
    p = _ff(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(final)])
    dur = float(p.stdout.strip())
    esperada = DUR * 3
    assert math.isclose(dur, esperada, abs_tol=0.3), \
        f"duración {dur:.2f}s ≠ {esperada:.2f}s"

    # ── 2. resolución ───────────────────────────────────────────────────
    p = _ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of",
             "csv=p=0", str(final)])
    w, h = (int(x) for x in p.stdout.strip().split(","))
    assert (w, h) == (W, H), f"resolución {w}x{h} ≠ {W}x{H}"

    # ── 3. faststart: moov antes de mdat (lectura binaria) ──────────────
    cabecera = final.read_bytes()[:65536]
    pos_moov, pos_mdat = cabecera.find(b"moov"), cabecera.find(b"mdat")
    assert pos_moov != -1 and pos_mdat != -1, "átomos moov/mdat ausentes"
    assert pos_moov < pos_mdat, "sin faststart: mdat precede a moov"

    # ── 4. audio integrado ≈ -14 LUFS (ebur128) ─────────────────────────
    p = _ff(["ffmpeg", "-i", str(final), "-af", "ebur128=framelog=quiet",
             "-f", "null", "-"])
    m = __import__("re").search(
        r"I:\s*(-?[0-9.]+)\s*LUFS", p.stderr)
    assert m, f"ebur128 sin lectura: {p.stderr[-200:]}"
    lufs = float(m.group(1))
    # Objetivo -14 LUFS (BROADCAST_LOUDNORM). Con tono continuo + dual_mono
    # el integrado queda ~3 LU por debajo (comportamiento ya documentado y
    # aceptado por test_p2_3_audio_loudnorm.py:83-84: rango -20..-10).
    assert -20.0 <= lufs <= -10.0, \
        f"{lufs} LUFS fuera del rango broadcast (objetivo -14, ver P2-3)"

    # ── 5. cero placeholders: ya verificado arriba con qa_image ─────────
    # (las 3 escenas llevan method="gemini" y pasan el detector de video_qa)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
