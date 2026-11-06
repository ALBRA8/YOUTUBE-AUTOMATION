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


if __name__ == "__main__":
    report = run_benchmark()
    print("=== BENCHMARK DE CALIDAD DE VIDEO (P2-2) ===")
    print(f"Cadena A (legacy):   SSIM={report['cadena_a']['ssim']:.5f} | PSNR={report['cadena_a']['psnr_db']:.2f} dB | Tiempo={report['cadena_a']['time_sec']}s")
    print(f"Cadena B (rediseño): SSIM={report['cadena_b']['ssim']:.5f} | PSNR={report['cadena_b']['psnr_db']:.2f} dB | Tiempo={report['cadena_b']['time_sec']}s")
    print(f"Ganancia en PSNR: +{report['gain']['psnr_delta_db']} dB (Mayor fidelidad visual)")
    print(f"SSIM Superior: {report['gain']['ssim_higher']}")
