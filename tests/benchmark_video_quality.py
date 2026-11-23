"""
Benchmark reproducible de calidad de video: Cadena de Re-codificación vs Codificación Única de Calidad.
Mide:
  1. SSIM (Structural Similarity Index)
  2. PSNR (Peak Signal-to-Noise Ratio en dB)
  3. Tiempo de codificación (s)
  4. Tamaño de archivo final (bytes)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def run_benchmark(tmp_dir: Path | None = None) -> dict:
    cleanup = False
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="bench_video_"))
        cleanup = True

    try:
        ref = tmp_dir / "ref_lossless.mp4"
        # Referencia lossless 1s en 360x640 (rápido y determinista)
        cmd_ref = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=360x640:rate=30",
            "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p", str(ref)
        ]
        subprocess.run(cmd_ref, check=True, capture_output=True)

        # ── CADENA A: Re-codificación en cadena (legacy) ──────────────────────
        # clip (CRF 20) -> xfade (CRF 18) -> subs (CRF 20)
        t0 = time.time()
        a_clip = tmp_dir / "a_clip.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(ref), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", str(a_clip)],
                       check=True, capture_output=True)

        a_xfade = tmp_dir / "a_xfade.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(a_clip), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "18", str(a_xfade)],
                       check=True, capture_output=True)

        a_final = tmp_dir / "a_final.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(a_xfade), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", str(a_final)],
                       check=True, capture_output=True)
        time_a = time.time() - t0
        size_a = a_final.stat().st_size

        # ── CADENA B: Intermedios casi sin pérdida + 1 encode final (rediseño) ─
        # clip (CRF 10 ultrafast) -> xfade (CRF 10 ultrafast) -> subs final (CRF 18 veryfast + faststart)
        t0 = time.time()
        b_clip = tmp_dir / "b_clip.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(ref), "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "10", str(b_clip)],
                       check=True, capture_output=True)

        b_xfade = tmp_dir / "b_xfade.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(b_clip), "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "10", str(b_xfade)],
                       check=True, capture_output=True)

        b_final = tmp_dir / "b_final.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(b_xfade), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "18", "-movflags", "+faststart", str(b_final)],
                       check=True, capture_output=True)
        time_b = time.time() - t0
        size_b = b_final.stat().st_size

        # ── Medición de métricas objetivas (SSIM y PSNR) vs referencia lossless
        res_a = subprocess.run(["ffmpeg", "-i", str(a_final), "-i", str(ref),
                               "-lavfi", "ssim;[0:v][1:v]psnr", "-f", "null", "-"],
                              capture_output=True, text=True)
        res_b = subprocess.run(["ffmpeg", "-i", str(b_final), "-i", str(ref),
                               "-lavfi", "ssim;[0:v][1:v]psnr", "-f", "null", "-"],
                              capture_output=True, text=True)

        def parse_metrics(txt: str) -> tuple[float, float]:
            ssim_m = re.search(r"All:([0-9\.]+)", txt)
            psnr_m = re.search(r"average:([0-9\.]+)", txt)
            s = float(ssim_m.group(1)) if ssim_m else 0.0
            p = float(psnr_m.group(1)) if psnr_m else 0.0
            return s, p

        ssim_a, psnr_a = parse_metrics(res_a.stderr)
        ssim_b, psnr_b = parse_metrics(res_b.stderr)

        return {
            "cadena_a": {
                "desc": "Legacy: CRF 20 -> CRF 18 -> CRF 20 (re-codificación en cadena)",
                "ssim": ssim_a,
                "psnr_db": psnr_a,
                "time_sec": round(time_a, 3),
                "size_bytes": size_a,
            },
            "cadena_b": {
                "desc": "Rediseño: CRF 10 (ultrafast) -> CRF 10 (ultrafast) -> CRF 18 (final única codificación)",
                "ssim": ssim_b,
                "psnr_db": psnr_b,
                "time_sec": round(time_b, 3),
                "size_bytes": size_b,
            },
            "gain": {
                "psnr_delta_db": round(psnr_b - psnr_a, 2),
                "ssim_higher": ssim_b > ssim_a,
                "time_delta_sec": round(time_b - time_a, 3),
            }
        }
    finally:
        if cleanup:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def run_benchmark_flowlike(tmp_dir: Path | None = None) -> dict:
    """P1-4 · Escenario FLOW-LIKE reproducible: clip Ken Burns (gradients +
    zoompan 3 fases) con audio, 1080x1920 @ 4 s — imita una escena real del
    pipeline. Compara Cadena A (re-codificación) vs Cadena B (intermedios
    CRF 10 + única final CRF 18) contra referencia lossless.

    VMAF: si el ffmpeg local tiene libvmaf se añade; si no, se registra
    NOT_DEMONSTRATED (este sandbox solo trae vmafmotion). Clips REALES de
    Flow: NO_DEMONSTRATED en sandbox (requiere generación con Flow vivo);
    el escenario es sintético pero determinista.
    """
    cleanup = False
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="bench_flow_"))
        cleanup = True
    try:
        tiene_vmaf = "libvmaf" in subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True).stdout
        # Escena Flow-like: degradado + zoompan Ken Burns + tono de audio
        cmd_src = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "gradients=s=1080x1920:n=3:d=4:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-vf", ("zoompan=z='min(1+0.2*on/24,1.2)'"
                    ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    ":d=120:s=1080x1920:fps=30"),
            "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le", str(tmp_dir / "ref_flow.mp4")]
        subprocess.run(cmd_src, check=True, capture_output=True)
        ref = tmp_dir / "ref_flow.mp4"

        # Cadena A: crf20 → crf18 → crf20 (legacy, sin faststart)
        a1, a2, a3 = (tmp_dir / "fa1.mp4"), (tmp_dir / "fa2.mp4"), (tmp_dir / "fa3.mp4")
        t0 = time.time()
        subprocess.run(["ffmpeg", "-y", "-i", str(ref), "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", str(a1)],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(a1), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "18", str(a2)],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(a2), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", str(a3)],
                       check=True, capture_output=True)
        t_a = time.time() - t0

        # Cadena B: crf10 ultrafast → crf10 ultrafast → crf18 veryfast final
        b1, b2, b3 = (tmp_dir / "fb1.mp4"), (tmp_dir / "fb2.mp4"), (tmp_dir / "fb3.mp4")
        t0 = time.time()
        subprocess.run(["ffmpeg", "-y", "-i", str(ref), "-an", "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "10", str(b1)],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(b1), "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "10", str(b2)],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(b2), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "18",
                        "-movflags", "+faststart", str(b3)],
                       check=True, capture_output=True)
        t_b = time.time() - t0

        def medir(probe: Path) -> tuple[float, float]:
            r = subprocess.run(
                ["ffmpeg", "-i", str(probe), "-i", str(ref),
                 "-lavfi", "ssim;[0:v][1:v]psnr", "-f", "null", "-"],
                capture_output=True, text=True)
            s = re.search(r"All:([0-9.]+)", r.stderr)
            p = re.search(r"average:([0-9.]+)", r.stderr)
            return (float(s.group(1)) if s else 0.0,
                    float(p.group(1)) if p else 0.0)

        sa, pa = medir(a3)
        sb, pb = medir(b3)
        res = {
            "escenario": "flow_like_1080x1920_4s_kenburns",
            "libvmaf": tiene_vmaf,
            "cadena_a": {"ssim": sa, "psnr_db": pa, "time_sec": round(t_a, 2),
                         "size_mb": round(a3.stat().st_size / 1e6, 2)},
            "cadena_b": {"ssim": sb, "psnr_db": pb, "time_sec": round(t_b, 2),
                         "size_mb": round(b3.stat().st_size / 1e6, 2)},
            "gain": {"psnr_delta_db": round(pb - pa, 2),
                     "ssim_higher": sb > sa},
        }
        texto_vmaf = ("medido" if tiene_vmaf else
                      "NOT_DEMONSTRATED (ffmpeg sin libvmaf; solo vmafmotion)")
        lineas = [
            "# Resultados P1-4 · Benchmark de calidad (escenario Flow-like)", "",
            f"- Escenario: {res['escenario']} (sintético determinista; clips "
            "REALES de Flow: NOT_DEMONSTRATED en sandbox)",
            f"- VMAF completo: {texto_vmaf}",
            "",
            "| cadena | SSIM | PSNR dB | tiempo s | tamaño MB |", "|---|---|---|---|---|",
            f"| A legacy (crf20→18→20) | {sa:.5f} | {pa:.2f} | {t_a:.1f} | {a3.stat().st_size/1e6:.1f} |",
            f"| B única final (crf10→10→18) | {sb:.5f} | {pb:.2f} | {t_b:.1f} | {b3.stat().st_size/1e6:.1f} |",
            "",
            f"**Ganancia B sobre A: +{res['gain']['psnr_delta_db']} dB PSNR, "
            f"SSIM {'mayor' if sb > sa else 'NO mayor'}**",
        ]
        out = Path(__file__).resolve().parents[1] / "tests" / "resultados_benchmark_video.md"
        out.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return res
    finally:
        if cleanup:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    report = run_benchmark()
    report_flow = run_benchmark_flowlike()
    print(f"Flow-like: A {report_flow['cadena_a']['psnr_db']} dB vs B "
          f"{report_flow['cadena_b']['psnr_db']} dB "
          f"(+{report_flow['gain']['psnr_delta_db']} dB)")
    print("=== BENCHMARK DE CALIDAD DE VIDEO (P2-2) ===")
    print(f"Cadena A (legacy):   SSIM={report['cadena_a']['ssim']:.5f} | PSNR={report['cadena_a']['psnr_db']:.2f} dB | Tiempo={report['cadena_a']['time_sec']}s")
    print(f"Cadena B (rediseño): SSIM={report['cadena_b']['ssim']:.5f} | PSNR={report['cadena_b']['psnr_db']:.2f} dB | Tiempo={report['cadena_b']['time_sec']}s")
    print(f"Ganancia en PSNR: +{report['gain']['psnr_delta_db']} dB (Mayor fidelidad visual)")
    print(f"SSIM Superior: {report['gain']['ssim_higher']}")
