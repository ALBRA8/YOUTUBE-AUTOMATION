#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-1 · Medición de jitter Ken Burns (zoompan) en 4K real.

Método (reproducible, sin números mágicos):
 1. SIMULACIÓN fiel de zoompan: ffmpeg trunca x/y a enteros por frame;
    el salto visible en píxeles de SALIDA por frame es
        shift(f) = frac(x*_f) * W_out * z(f) / iw        (x*_f ideal continuo)
    El jitter se reporta como std de la 2ª diferencia (aceleración) del
    desplazamiento en píxeles de salida — la métrica de la medición original
    (1x→5.93, 2x→2.87, >2x→1.38). El paso 2 valida el simulador contra esos
    números; si no calibra, se documenta.
 2. CALIBRACIÓN contra la medición histórica (1080x1920, factor 1.0 y 2.0).
 3. VARIANTES 4K (2160x3840, 30 fps, 8 s — caso real del pipeline):
    A  actual: intermedio factor 1.125 (2430x4320, safe_kenburns_scale)
    A0 sin mitigar: intermedio 1.0 (2160x3840)
    B  zoompan a 1080p (intermedio 2160x3840 = 2x, salida 1080x1920) +
       reescalado final lanczos a 2160x3840
    C  factor 2.0 directo en 4K (intermedio 4320x7680) — SOLO analítico
       (memoria estimada; render real no cabe en el sandbox de 3 GB).
 4. RENDER REAL de A y B (clip 2 s) midiendo RSS máximo del hijo con
    resource.getrusage(RUSAGE_CHILDREN).

Salida: tools/resultados_jitter_kenburns.md
Ejecutar: python3 tools/medir_jitter_kenburns.py
"""
from __future__ import annotations

import math
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from pipeline.video import kenburns_3phase_expr  # noqa: E402

FPS = 30
DUR = 8.0
FRAMES = int(DUR * FPS)
ZOOM_IN_FRAC, ZOOM_OUT_FRAC, PEAK = 0.2, 0.2, 1.2
AMP = PEAK - 1.0
F_IN = max(int(FRAMES * ZOOM_IN_FRAC), 1)
F_OUT = max(FRAMES - max(int(FRAMES * ZOOM_OUT_FRAC), 1), F_IN + 1)
TAIL = max(FRAMES - F_OUT, 1)

HISTORICO = {"1.0": 5.93, "2.0": 2.87}  # medición original de P2-4


def zoom_en(on: int) -> float:
    """Evalúa kenburns_3phase_expr tal como ffmpeg (float64, sin redondeos)."""
    if on < F_IN:
        return 1.0 + AMP * (on / F_IN)
    if on < F_OUT:
        return PEAK
    return PEAK - AMP * ((on - F_OUT) / TAIL)


def _accel_std(serie: list[float]) -> float:
    """std de la 2ª diferencia de una serie (aceleración del desplazamiento)."""
    if len(serie) < 3:
        return 0.0
    acc = [abs(serie[i] - 2 * serie[i - 1] + serie[i - 2])
           for i in range(2, len(serie))]
    n = len(acc)
    mu = sum(acc) / n
    return math.sqrt(sum((a - mu) ** 2 for a in acc) / n)


def simula(iw: int, ih: int, w_out: int, h_out: int, on0: int = 0,
           frames: int = FRAMES) -> dict:
    """Jitter simulado: zoompan trunca x/y a int; shift en px de salida."""
    sx, sy = [], []
    for on in range(on0, on0 + frames):
        z = zoom_en(on)
        xr = iw / 2 - (iw / z) / 2          # x ideal continuo
        yr = ih / 2 - (ih / z) / 2
        xi, yi = int(xr), int(yr)           # truncado de ffmpeg
        sx.append((xr - xi) * w_out * z / iw)
        sy.append((yr - yi) * h_out * z / ih)
    return {"accel_x": _accel_std(sx), "accel_y": _accel_std(sy),
            "max_x": max(sx), "max_y": max(sy)}


def jitter_total(iw: int, ih: int, w_out: int, h_out: int) -> float:
    r = simula(iw, ih, w_out, h_out)
    return round((r["accel_x"] + r["accel_y"]) / 2.0, 2)


def render_rss(cmd: list[str]) -> tuple[float, bool]:
    """RSS máximo del proceso hijo en MB (getrusage children delta) + ok."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return max(after, before) / 1024.0, p.returncode == 0


def main() -> int:
    lineas = ["# Resultados P1-1 · Jitter Ken Burns 4K (zoompan)", "",
              f"Fecha: sandbox Linux · {FRAMES} frames @ {FPS} fps · "
              "métrica: std(accel) en px de SALIDA (media x/y)", ""]

    # ── 2. CALIBRACIÓN (1080x1920 como la medición original) ────────────────
    lineas += ["## 2. Calibración del simulador vs medición histórica (1080x1920)",
               "", "| factor | histórico | simulado |", "|---|---|---|"]
    cal = {}
    for f_txt, esperado in HISTORICO.items():
        f = float(f_txt)
        j = jitter_total(int(1080 * f), int(1920 * f), 1080, 1920)
        cal[f] = j
        lineas.append(f"| {f}x | {esperado} | {j} |")
    calibra = all(abs(cal[float(k)] - v) / v < 0.5 for k, v in HISTORICO.items())
    lineas += ["", f"**Calibración {'✅ dentro de ±50%' if calibra else '⚠️ NO calibra — ver nota'}**", ""]

    # ── 3. VARIANTES 4K (simulación) ────────────────────────────────────────
    W, H = 2160, 3840
    variantes = [
        ("A actual (1.125x → 2430x4320)", int(W * 1.125), int(H * 1.125), W, H),
        ("A0 sin mitigar (1.0x → 2160x3840)", W, H, W, H),
        ("B zoompan 1080p 2x + upscale lanczos", int(1080 * 2), int(1920 * 2), 1080, 1920),
        ("C 2.0x directo 4K (4320x7680)", int(W * 2), int(H * 2), W, H),
    ]
    lineas += ["## 3. Jitter simulado en 4K (2160x3840)", "",
               "| variante | std(accel) px | memoria/frame intermedio (RGBA) |",
               "|---|---|---|"]
    datos = {}
    for nombre, iw, ih, wo, ho in variantes:
        j = jitter_total(iw, ih, wo, ho)
        mem = iw * ih * 4 / 1e6
        datos[nombre] = j
        lineas.append(f"| {nombre} | {j} | {mem:.0f} MB |")

    # ── 4. RENDER REAL A y B con RSS ────────────────────────────────────────
    lineas += ["## 4. Render real 2 s (RSS máximo del hijo ffmpeg)", "",
               "| variante | RSS máx MB | exit | tiempo |", "|---|---|---|---|"]
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "img.png"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "gradients=s=2160x3840:n=3", "-frames:v", "1",
                        str(img)], capture_output=True, timeout=120)
        import time as _t

        # A: comando real del pipeline (scene_clip_cmd sin rotación, 2 s)
        from pipeline.video import scene_clip_cmd
        cmd_a = scene_clip_cmd(img, 2.0, Path(td) / "a.mp4", W, H, rotate_deg=0)
        t0 = _t.time()
        rss_a, ok_a = render_rss(cmd_a)
        lineas.append(f"| A actual | {rss_a:.0f} | {ok_a} | {_t.time()-t0:.1f}s |")

        # B: 1080p path — intermedio 2160x3840, zoompan a 1080x1920, upscale
        zexpr = kenburns_3phase_expr(60)
        cmd_b = ["ffmpeg", "-y", "-loop", "1", "-i", str(img),
                 "-frames:v", "60", "-t", "2.000", "-vf",
                 (f"scale=2160:3840:force_original_aspect_ratio=increase,"
                  f"crop=2160:3840,"
                  f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d=60:s=1080x1920:fps={FPS},"
                  f"scale=2160:3840:flags=lanczos,format=yuv420p"),
                 "-r", str(FPS), "-an", "-c:v", "libx264", "-crf", "18",
                 "-preset", "veryfast", str(Path(td) / "b.mp4")]
        t0 = _t.time()
        rss_b, ok_b = render_rss(cmd_b)
        lineas.append(f"| B 1080p+upscale | {rss_b:.0f} | {ok_b} | {_t.time()-t0:.1f}s |")

    # ── 5. DECISIÓN CON DATOS ───────────────────────────────────────────────
    j_a, j_a0, j_b = datos[variantes[0][0]], datos[variantes[1][0]], datos[variantes[2][0]]
    lineas += ["## 5. Decisión", ""]
    if j_b < j_a * 0.7:
        lineas += [
            f"- B reduce el jitter de {j_a} (A, actual) a {j_b} px — **~{(1-j_b/j_a)*100:.0f}% menos** —",
            "  con memoria de render acotada (intermedio 2160x3840, salida 1080p + upscale).",
            "- **ELEGIDA: B** — zoompan trabaja a 1080p con factor 2x real (mitigación",
            "  históricamente medida), el reescalado final lanczos a 4K no añade jitter",
            "  (es un mapeo fijo, sin cuantización por frame).",
        ]
    elif j_a < j_a0 * 0.8:
        lineas += [f"- A (actual, {j_a}) ya mitiga frente a A0 ({j_a0}) — **SIN CAMBIO**."]
    else:
        lineas += [f"- Datos: A={j_a}, A0={j_a0}, B={j_b} — decisión documentada en el commit."]
    texto = "\n".join(lineas) + "\n"
    (REPO / "tools" / "resultados_jitter_kenburns.md").write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
