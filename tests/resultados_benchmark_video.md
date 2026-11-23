# Resultados P1-4 · Benchmark de calidad de video (reproducible)

- Script: `tests/benchmark_video_quality.py` (`run_benchmark`, escenario determinista 360x640@1s testsrc)
- Comando: `python3 tests/benchmark_video_quality.py` (o vía `test_p2_2_video_encoding_chain.py`, 3/3 verde)
- Ejecución real 2026-11-06 (sandbox Linux, ffmpeg estándar):

| cadena | SSIM | PSNR dB | tiempo s | tamaño B |
|---|---|---|---|---|
| A legacy (crf20→18→20, re-codificación) | 0.997187 | 46.03 | 0.37 | 10 945 |
| B única final (crf10→10→18 +faststart) | 0.998686 | 51.04 | 0.30 | 12 514 |

**Ganancia B sobre A: +5.01 dB PSNR, SSIM mayor (0.998686 > 0.997187), y 0.07 s más rápido.**

- `run_benchmark_flowlike()` (mismo script): escenario Flow-like 1080x1920@4s Ken Burns
  con audio — preparado y comprometido; su ejecución en este sandbox quedó
  NOT_DEMONSTRATED (cuelgues repetidos del sandbox en renders 1080p encadenados).
  Ejecutar en la máquina del dueño para el número del escenario real.
- VMAF completo: NOT_DEMONSTRATED (este ffmpeg no trae libvmaf; solo vmafmotion).
  El script lo detecta dinámicamente y añadirá VMAF cuando exista.
- Clips REALES de Flow: NOT_DEMONSTRATED en sandbox (requiere Flow vivo).
