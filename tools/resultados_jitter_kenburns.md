# Resultados P1-1 · Jitter Ken Burns 4K (zoompan)

Fecha: sandbox Linux · 240 frames @ 30 fps · métrica: std(accel) en px de SALIDA (media x/y)

## 2. Calibración del simulador vs medición histórica (1080x1920)

| factor | histórico | simulado |
|---|---|---|
| 1.0x | 5.93 | 0.39 |
| 2.0x | 2.87 | 0.22 |

**Calibración ⚠️ NOTA HONESTA**: la escala ABSOLUTA histórica (5.93/2.87) no se reproduce con ninguna semántica de truncado probada (trunc/floor/round, on 0/1-based, escalas out/intermedio): su metodología original NO está documentada en el repo. El simulador reproduce la RELACIÓN relativa (2x ≈ la mitad de jitter que 1x), que es lo que exige la decisión. Métrica propia documentada: std(accel) del desplazamiento sub-píxel en px de salida derivado del truncado entero de x/y de zoompan.

## 3. Jitter simulado en 4K (2160x3840)

| variante | std(accel) px | memoria/frame intermedio (RGBA) |
|---|---|---|
| A actual (1.125x → 2430x4320) | 0.42 | 42 MB |
| A0 sin mitigar (1.0x → 2160x3840) | 0.44 | 33 MB |
| B zoompan 1080p 2x + upscale lanczos | 0.22 | 33 MB |
| C 2.0x directo 4K (4320x7680) | 0.23 | 133 MB |
## 4. Render real 2 s (RSS máximo del hijo ffmpeg)

| variante | RSS máx MB | exit | tiempo |
|---|---|---|---|
| A actual | 734 | True | 2.2s |
| B 1080p+upscale | 1354 | True | 5.3s |
## 5. Decisión

- B reduce el jitter de 0.42 (A, actual) a 0.22 px — **~48% menos** —
  con memoria de render acotada (intermedio 2160x3840, salida 1080p + upscale).
- **ELEGIDA: B** — zoompan trabaja a 1080p con factor 2x real (mitigación
  históricamente medida), el reescalado final lanczos a 4K no añade jitter
  (es un mapeo fijo, sin cuantización por frame).
- Coste medido del render real (clip 2 s): B tarda 5.3 s vs 2.2 s de A y
  pico de RSS 1354 MB vs 734 MB (upscale lanczos) — aceptable y muy por
  debajo de C (intermedio 4320x7680 = 133 MB/frame, riesgo OOM en máquinas
  de 8 GB; render real de C NO_DEMONSTRATED en sandbox de 3 GB).
- IMPLEMENTADO en pipeline/video.py scene_clip_cmd: ruta B automática
  cuando safe_kenburns_scale dejaría el factor < 2.0 (4K); <2160-class
  mantiene el camino directo con factor 2.25-2.5.
