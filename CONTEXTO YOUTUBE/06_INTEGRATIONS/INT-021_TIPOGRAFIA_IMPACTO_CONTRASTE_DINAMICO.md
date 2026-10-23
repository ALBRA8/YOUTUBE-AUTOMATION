# INT-021 — Tipografía de impacto + contraste dinámico de subtítulos (estilo Shorts)

- **Fecha:** 2026-10-23
- **Clasificación:** mejora de producto (orden directa del usuario; integración quirúrgica; no cambia contratos públicos de API, solo AÑADE el estilo `shorts` y lo vuelve default).

## 1. Objetivo y mandato

Elevar la legibilidad de los subtítulos de Shorts a estándar de producto:

- **Tipografía de impacto embarcada:** Montserrat ExtraBold (`backend/data/fonts/`) — sin depender de fuentes instaladas en el sistema.
- **Paleta dinámica con contraste verificado >= 4.5:1 (WCAG AA)** según el brillo real de la escena.
- **Zona segura Shorts:** MarginV >= 280 px (desde abajo), fuera de la UI de Shorts/TikTok.
- **Parámetros ASS fijos:** Bold 1 · BorderStyle 1 · Outline 3-4 (banda) · Shadow 2 · Alignment 2 (bottom-center).

Mandato del usuario para la implementación: *sin arquitecturas paralelas ni dependencias nuevas, `main` única fuente de verdad, pipeline liviano*. Se cumple: un módulo nuevo (`typography.py`, solo stdlib), una fuente embarcada con su licencia, y cierres quirúrgicos en los puntos que ya deciden el estilo de subtítulos. Cero dependencias añadidas.

## 2. Decisión crítica verificada (matching libass)

La orden literal pedía `Fontname 'Montserrat'`. Prueba empírica A/B (ffmpeg 7.1.5 + libass real, lienzo 320x568, MD5 del fotograma decodificado en rawvideo):

| Fontname (con `fontsdir` del repo) | MD5 fotograma | Lectura |
|---|---|---|
| `Montserrat` | `eb35c18849cae7ea5ccf395e2abcc91c` | **Idéntico** al de una fuente inexistente → degradación SILENCIOSA a la fuente por defecto |
| fuente inexistente | `eb35c18849cae7ea5ccf395e2abcc91c` | referencia de degradación |
| `Montserrat ExtraBold` | `40d014158a85e4e98e545be7bc9cebae` | distinto → resuelve la cara real |

**Causa:** libass indexa el directorio (`fontsdir`) por la familia **ID1** de la name table de la TTF — `Montserrat ExtraBold` — y NO resuelve la familia tipográfica **ID16** (`Montserrat`), aunque ambos nombres estén presentes y sean correctos en la TTF (name table verificada: ID1 `Montserrat ExtraBold`, ID16 `Montserrat`, peso 800).

**CONSECUENCIA en el código:** `Fontname` usa `'Montserrat ExtraBold'` cuando existe la TTF embarcada (`find_font()`) y reserva `'Montserrat'` solo para el caso de fuente instalada en sistema (`font_path=None`). Sin esta corrección el estilo habría degradado en silencio a la fuente default en TODOS los renders.

- Desviación del texto literal de la orden **autorizada explícitamente por el usuario** («si yo estoy mal omite las referencias de exactitud»).
- La batería **S8** congela esta evidencia: si un libass futuro empezara a resolver ID16, la batería lo detecta.

## 3. Cambios (archivo → qué)

| Archivo | Cambio |
|---|---|
| `backend/data/fonts/Montserrat-ExtraBold.ttf` | **NUEVO** (455.468 bytes, SIL OFL 1.1, upstream JulietaUla/Montserrat; familia ID1 `Montserrat ExtraBold`, ID16 `Montserrat` — name table verificada) |
| `backend/data/fonts/OFL.txt` | **NUEVO**: licencia SIL OFL 1.1; redistribución conforme a la licencia |
| `backend/pipeline/typography.py` | **NUEVO**: `calculate_luminance` (luminancia relativa WCAG 2.x); `get_contrasting_style` con **contrato doble** — texto vs borde Y max(texto vs escena, borde vs escena), ambos >= 4.5:1 — con bandas dark<0.45 / mid<0.72 / bright, outline 3-4 y alfa de sombra 80/9E/B4; `generate_shorts_sub_style` (71 pt @1920, banda de diseño 68-75, y 142 pt @3840; MarginV 280/560); `estimate_video_brightness` vía `signalstats` YAVG (muestra `-t 45`, escala 64x64, normalización de rango limitado `(Y-16)/219`, timeout 45 s, **fallback 0.5 ante CUALQUIER fallo**, runner inyectable para hermeticidad en baterías) |
| `backend/pipeline/subtitles.py` | `SHORTS_HEADER` (PlayRes con la resolución real del render) + entrada `shorts` en `SUB_STYLES` (size_ratio 0.037, outline 4, shadow 2, chunks 3 para el pop) + `build_ass` con `avg_brightness` opcional; **estilos legacy BYTE-IDÉNTICOS** (contrato protegido por test) |
| `backend/pipeline/video.py` | `burn_subtitles`: default `shorts`; pasada de brillo por `_run_ffmpeg` (misma ruta hermética que el resto de ffmpeg); `fontsdir` en el filtro `ass` SOLO si existe `FONT_DIR` (escaping `:` idéntico al del path del .ass); lógica INT-012 de preset veryfast + timeout 900 + degradación honesta **INTACTA** |
| `backend/main.py` | Allowlist de estilos ampliada (`shorts` primero) y defaults a `shorts` en 3 puntos: rama production_json, herencia de plantilla y creación general |
| `backend/services/agent.py` · `backend/services/youtube_harness/adapter.py` | Defaults de plantilla a `shorts` |
| `backend/static/app.js` | Wizard default `shorts` + nueva opción «Shorts · Montserrat dinámico» en el dropdown, por encima de Hormozi |

## 4. Comportamiento dinámico

Bandas por brillo medio de escena (0..1; `avg_brightness` medido del raw):

| Banda | Brillo | Texto | Borde (px) | Sombra (alfa BackColour) |
|---|---|---|---|---|
| Oscura | <0.45 | blanco `FFFFFF` | `080808` (3) | alfa `80` |
| Mixta | 0.45-0.71 | amarillo `FFFF00` | `080808` (4) | alfa `9E` |
| Clara | >=0.72 | blanco `FFFFFF` | `101010` (4) | alfa `B4` |

Contrastes medidos (ejemplo @0.5, banda mixta, auditables en el dict que devuelve `get_contrasting_style`): texto-borde **18.65:1**; mínimo del contrato **10.49:1** (borde vs escena; el texto amarillo solo da 1.78:1 contra la escena gris media — precisamente por eso el contrato exige la separación vía borde o la sostención directa del texto, nunca solo texto vs fondo). `meets_wcag: True`.

La medición de brillo es una **muestra de los primeros 45 s** (64x64, `signalstats` YAVG, luma BT.601 en rango limitado). Es best-effort: cualquier fallo (timeout, rc!=0, ffmpeg ausente, sin muestras) cae en 0.5 (banda neutra) — **jamás bloquea ni degrada el burn**.

## 5. Pruebas

Batería nueva `tests/test_typography.py`, secciones:

- **S1** — Fuente embarcada: archivo presente, name table (ID1 `Montserrat ExtraBold` / ID16 `Montserrat`), peso 800, `OFL.txt` presente.
- **S2** — Luminancia WCAG 2.x (valores de referencia conocidos).
- **S3** — Contraste WCAG del contrato doble (texto-borde y separación-escena >= 4.5:1).
- **S4** — Barrido de brillo 0..1: ninguna entrada del dominio por debajo de 4.5:1.
- **S5** — Línea `Style:` ASS: fontname, tamaño (71/142), MarginV (280/560), Bold, BorderStyle, Outline por banda, Shadow, Alignment.
- **S6** — `build_ass` integración `shorts` + **contrato legacy byte-idéntico** (hormozi/tiktok/karaoke emiten exactamente la salida anterior).
- **S7** — Brillo real con MP4 sintéticos (claro/oscuro/mixto) + fallback 0.5 ante fallo.
- **S8** — Réplica del A/B de matching libass (§2 congelado como regresión).

**Resultados reales de esta sesión (verificación canónica, pre-commit):**

- **Batería nueva `test_typography.py`: 59 OK · 0 fallos** (ejecución repetida: determinista). `test_burn_subtitles_resilience.py` re-verificada en verde: **16 OK · 0 fallos** (contrato INT-012 intacto).
- **Suite canónica (`tests/run_all.py`, 47 baterías) ejecutada por lotes con `run_chunk.py`: 46/47 baterías, 2.181 checks, 0 fallos funcionales.** Los únicos 5 ✗ son los **guards de higiene de worktree** de la era F2 (`L2/L3` en `test_flow_batchexecute`, `N4/N5/S2` en `test_flow_startframe_fase2`), que exigen árbol LIMPIO y por diseño fallan durante una sesión de implementación (precedente exacto: INT-020 §4 — "los guards de worktree sucio pasan en árbol limpio por diseño"). Se re-ejecutan post-commit como cierre de esta integración.
- **Salvedad honesta:** `test_10_escenas` no completó su resumen dentro de la ventana del sandbox (misma lentitud ambiental ya documentada en INT-020 §4; batería que mockea el render y no ejercita el código cambiado; baseline 44/44 OK en `c724231`).
- La línea literal `pytest tests/ -v -k "subtitle or video or live"` fue intentada para el expediente y reproduce el `INTERNALERROR` conocido (las baterías de este repo son scripts canónicos, no colección pytest).
- La batería queda registrada en `tests/run_all.py` tras `test_burn_subtitles_resilience`.

**Verificación post-commit (árbol limpio, commit `e995563`):** los 2 baterías con guards de higiene pasan íntegras — `test_flow_batchexecute` **64/0** (62+2 guards), `test_flow_startframe_fase2` **67/0** (64+3 guards) — y se re-verifican `test_typography` **59/0** y `test_burn_subtitles_resilience` **16/0**. **Total de la sesión: 47/47 baterías ejecutadas, 2.186 checks, 0 fallos.** (Salvedad `test_10_escenas` arriba; baseline 44/44.)

## 6. Pendiente (honesto)

- **Validación visual HARD E2E en Windows real (Antigravity):** el matching de fuentes y el render deben confirmarse en la máquina del usuario, con el build de ffmpeg que él use (el A/B de §2 se ejecutó con ffmpeg 7.1.5 del sandbox). Ver el video final y confirmar que la Montserrat ExtraBold se ve y que la paleta responde a escenas claras/oscuras reales.
- **Push pendiente de canal seguro** (sin token disponible en esta sesión).

## 7. Estado

- **COMMIT EN `main`: `e995563`** (14 archivos, +852/−20, sobre `c724231`; árbol limpio verificado; `main` = `e995563`, `origin/main` queda 1 commit atrás hasta el push).
- Clasificación: **IMPLEMENTADA — VALIDACIÓN VISUAL REAL PENDIENTE** (§6).
