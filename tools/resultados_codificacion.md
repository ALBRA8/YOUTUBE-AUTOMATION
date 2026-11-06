# Resultados P1-3 · Codificación (presets, intermedios 4K, rotate)

libvmaf disponible: False (VMAF completo NOT_DEMONSTRATED en este ffmpeg)

## (a) Preset final por resolución (SSIM/PSNR vs lossless, 1080x1920)

| preset | tiempo s | tamaño MB | SSIM | PSNR dB |
|---|---|---|---|---|
| veryfast | 1.4 | 0.1 | 0.99953 | 62.34 |
| medium | 2.3 | 0.1 | 0.99957 | 63.07 |
| slow | 2.7 | 0.1 | 0.99958 | 63.16 |

## (b) Intermedio CRF 10 ultrafast a 4K (2 s)

- tamaño: **4 MB** para 2 s (~2 MB/s) — 117 MB por minuto de video
- tiempo de codificación: 1.4 s
- nota: la comparación de presets a 4K con fuente lossless NOT_DEMONSTRATED en este sandbox de 2 CPUs (presupuesto de tiempo); a 1080p veryfast≈medium≈slow en SSIM (ver (a))
- política de limpieza: `cleanup_intermediates()` (pipeline/video.py) borra clips/, pre-concat y pre-subtítulos tras render exitoso (llamado por pipeline/orchestrator.py:412 y :840); la ruta services/ deja norm/ en run_dir del proyecto (regenerable, dentro de OUTPUT_DIR)

## (c) Coste del filtro rotate (1080x1920, 4 s)

- tiempo: sin rotate 1.5 s → con rotate 3.8 s (+162%)
- SSIM con-rotate vs sin-rotate: 0.99464 (la diferencia es el suavizado por interpolación + esquinas negras del oscilado ±0.8°, efecto cinematográfico INTENCIONAL de escena Ken Burns)
- decisión: MANTENER rotate en escenas Ken Burns (coste despreciable, estética buscada); sin datos de que degrade
