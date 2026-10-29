# INT-070 — Auditoría dirigida y adopción quirúrgica de `estudio-video-ia`

- **Fecha:** 2026-10-29.
- **Estado:** IMPLEMENTADO (4 absorciones) / batería 16/16 · suite pytest **208/208** · smokes reales ffmpeg OK · validación con voces/clips reales pendiente (Antigravity).
- **Origen:** zip `estudio-video-ia` aportado por el usuario (pipeline manual Claude Code + Higgsfield/Kling 4.0 para shorts hiperrealistas ≤30 s). Método INT-019: inventario, comparación por áreas con anclas archivo:línea, veredicto y absorción SOLO de lo que aporta valor real verificado.
- **Licencia (nota honesta):** el zip NO trae fichero LICENSE (solo `OFL-Anton.txt` para la fuente, licencia limpia). Se trata como material aportado por el propietario; la adopción es de ALGORITMOS re-implementados con tests propios, no copia literal de ficheros. Si el origen fuera tercero con derechos, revisar antes de cualquier exposición pública del repo.

## 1. Veredicto por área

### 1.1 Subtitulado palabra-a-palabra — ALBRA ya es SUPERSET · ABSORBIDO el realineador (el valor real estaba aquí)
- `subtitulos.py` del origen: karaoke .ass por palabra, grupo ≤3 palabras, acento con `\fscx112`, Anton dimensionada por ancho. **ALBRA ya tiene más** en `services/karaoke_subtitles.py` (INT-045): presets Hormozi/MrBeast/Cyberpunk, pop_scale 115-118 %, chunking 3-5, multi-aspecto, marcas de margen por plataforma.
- El átomo valioso estaba en `transcribir.py::realinear` (transcribir.py:40-77): los timestamps de Whisper se desvían hasta ~0.8 s junto a las pausas y ALBRA los entregaba CRUDOS (`whisper_service.align_scene` → timestamps del modelo sin post-proceso). El realineador ancla cada pausa REAL (ffmpeg `silencedetect -38dB:d=0.12`) al hueco entre palabras más probable, con premio de 0.8 s si cae tras puntuación, y reparte cada tramo por peso de palabra (las cifras pesan ×6).
- **Adoptado:** `services/whisper_realign.py` (NUEVO) + hook en `align_scene` con gate `WHISPER_REALIGN=1` (default) y fail-open total (si algo falla → timestamps crudos de siempre). Compat de claves: acepta `{word,start,end}` (ALBRA) y `{w,ini,fin}` (estudio); salida SIEMPRE ALBRA.

### 1.2 Retimer por anclas — SIN equivalente en ALBRA · ABSORBIDO como herramienta de rescate
- `retimar.py` estira/encoge tramos del video entre anclas `origen=destino` (trim+setpts, `minterpolate` mci/aobmc/vsbmc en cámara lenta, `atempo` encadenado para salir del rango 0.5-2.0) para que los cortes del generador IA caigan en SU palabra — Kling/Flow no respetan los segundos del prompt (desvíos ~4 s).
- Encaje con ALBRA: el contrato de ejecución (§13) hoy RECHAZA el clip con desvío (`CONTRACT_VIOLATION → ASSET_INVALID`, terminal). El retimer es la vía ALTERNATIVA: **rescatar** el clip ajustándolo a la voz en vez de regenerar (créditos + espera).
- **Adoptado:** `services/video_retimer.py` (NUEVO; núcleo puro testeable + runner async fail-closed). Smoke REAL: clip lavfi 4 s con audio → ancla `2.0=3.0` → 4.0→4.0 s con velocidades 0.667/2.0 y minterpolate activo. **Bug de port capturado por el smoke real:** el filtro `concat` consume las entradas SEGMENTO a segmento (`[v0][a0][v1][a1]`), no todo el video primero — corregido con aserción de regresión en la batería.
- **NO cableado al pipeline** (decisión documentada): el rescate automático frente a regeneración es una decisión de producto (coste de créditos vs calidad); candidatos de wiring futuro en R-2.

### 1.3 Mezcla de audio — ABSORBIDO como opt-in (sidechain + loudnorm)
- `montar.py` trae ingeniería real: ducking DINÁMICO (`sidechaincompress` cama ratio 6 threshold 0.03; SFX suave ratio 3), **loudnorm a -14 LUFS / TP=-1 / LRA=11 (estándar de YouTube)**, SFX con fundidos anti-clic, `tpad` si el video queda corto.
- ALBRA (`video_assembler.build_mix_cmd`): ducking ESTÁTICO -20 dB, sin normalización de loudness.
- **Adoptado (opt-in, default OFF → filtergraph golden byte-idéntico):** `RENDER_MUSIC_SIDECAN=1` (ducking dinámico de la cama contra la voz, `asplit` para señal+llave) y `RENDER_LOUDNORM=1` (normalización en cadena tras el amix). Smoke real de parseo+render con ambas activas OK. Fundidos anti-clic del SFX → R-3 (el mix SFX de INT-050 es la superficie).

### 1.4 Medición de acento para casting — SIN equivalente · ABSORBIDO como servicio
- `medir_acento.py`: física elegante — frase emparejada (`Cima, cena… coser. Sima, sena… coser.`) → 10 picos de silbido 4-10 kHz → Δ dB entre mitades z/c y s: ≥6 dB = distinción (España), ≤3 dB = seseo (LatAm). Referencias medidas en origen: Sterling 1.8, Gideon 7.6, Barrett+etiqueta 13.8.
- **Adoptado:** `services/accent_meter.py` (NUEVO): `measure_delta` (port fiel del espectro) + `classify` + `audit_voice` fail-closed. Tests con WAV sintéticos (tonos 5 kHz con envolvente): Δ≈12 dB → España válida; Δ≈0 → seseo válida; audio inservible → error honesto. **R-4:** wire en `voices_catalog`/casting (validar el claim de acento de una voz ANTES de gastarla en un canal).

### 1.5 Perfiles de estilo y marca — ALBRA SUPERSET · semillas de datos registradas
- `perfil.ejemplo.json` (canal: voz, acento_medido_db, palabras_por_segundo…) ← `brand_profiles.py` de ALBRA ya cubre más (DB relacional, multi-canal, UI, autofill del wizard).
- Átomos NO absorbidos hoy, registrados: **R-5a** `palabras_por_segundo` por voz (calibrar `RENDER_EST_CPS`/duraciones por voz real); **R-5b** catálogo de 10 estilos con "biblia" en inglés + kit SFX + color de acento por estilo (semilla para themes/sfx_manager/acento del karaoke). `marca.json` = enlace de afiliado del autor del origen → irrelevante para ALBRA.

### 1.6 Skills de Claude (`.claude/skills/crear-video`) — DESCARTADO con motivo
- Paradigma distinto: guion interactivo para Claude Code con aprobaciones humanas paso a paso ("enséñame el storyboard y espera un vale"). ALBRA es backend automatizado con contrato A2A (`/api/agent/execute`) y skills con validación de registro (`services/skills.py`). Las preocupaciones que cubre el SKILL.md (no gastar sin preflight, verificación de entorno) ya viven en el preflight del orquestador y el Production Doctor.

## 2. Cambios en el repo

| Fichero | Cambio |
|---|---|
| `backend/services/whisper_realign.py` | NUEVO — realineador de timestamps Whisper (port de `realinear`) |
| `backend/services/whisper_service.py` | hook en `align_scene` (gate + fail-open) |
| `backend/services/video_retimer.py` | NUEVO — retimer por anclas (núcleo puro + runner fail-closed) |
| `backend/services/accent_meter.py` | NUEVO — Δ espectral de acento + clasificador de casting |
| `backend/services/video_assembler.py` | `build_mix_cmd`: sidechain + loudnorm opt-in (golden intacto) |
| `backend/config.py` · `.env.example` | `WHISPER_REALIGN=1`, `RENDER_MUSIC_SIDECAN=0`, `RENDER_LOUDNORM=0` documentados |
| `tests/test_int070_estudio_video_ia.py` | NUEVO — 16 checks (S1 realineador · S2 retimer · S3 acento · S4 mezcla) |
| `tests/test_int024_assembler.py` | fix de batería pre-existente: el plan tiene 6 pasos desde INT-050 (paso SFX) — la expectativa de 5 quedó vieja; verificado que fallaba en HEAD limpio |

## 3. Verificación

- Batería INT-070: **16/16**. Suite completa: **208/208** (antes 192). `test_int024_assembler.py`: **90 OK · 0 fallos** (88 + fix de expectativa).
- Smokes REALES ffmpeg: retimer (clip 4 s lavfi → retime con minterpolate) y mix sidechain+loudnorm (parseo + render de grafo completo).
- Hermeticidad: cero red, cero modelos, cero binarios requeridos por los tests (los smokes ffmpeg se ejecutaron fuera de la batería, como en INT-024 S7).

## 4. Límite honesto

Los tres servicios están verificados con tests + smokes sintéticos. La validación con MATERIAL REAL (voz del catálogo leyendo la frase de prueba, clip real de Flow con desvío, mezcla con cama musical en un render 4K) corresponde a la sesión de Antigravity (`05_TESTS/ANTIGRAVITY_VALIDACION_PRODUCCION.md`), que puede ampliar su paso 7 con estos tres humos.
