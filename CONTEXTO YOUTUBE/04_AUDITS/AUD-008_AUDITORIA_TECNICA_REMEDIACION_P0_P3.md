# AUD-008 — Auditoría Técnica y Remediación Integral (P0, P1, P2, P3)

- **Fecha:** 2026-11-06
- **Estado:** CLOSED / PASS (P0 a P3-3 implementados con regresión hermética; GAP-002 mantenido NOT_DEMONSTRATED)
- **Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`
- **Rama:** `main`
- **Batería de Pruebas Agregadas:** 15 archivos nuevos de test en `tests/test_p*`, 40/40 checks PASS.

---

## 1. Prioridad 0: Seguridad y CI

### P0-1. SSRF en Modo Producto (`backend/pipeline/images.py`)
- **Problema:** Se usaba `urllib.request.urlopen(img_url)` directo sin saneamiento.
- **Remediación:** Reemplazado por `security.safe_fetch_bytes` (tope de tamaño, redirecciones inspeccionadas, bloqueo estricto de esquemas `file://`, loopback, IPs privadas y metadata AWS/GCP `169.254.x`).
- **Verificación:** `tests/test_p0_1_product_ssrf.py` (48 checks PASS).

### P0-2. CI Workflow (`.github/workflows/ci.yml`)
- **Problema:** 23 baterías quedaban fuera de `pytest tests/ -q` en CI por exclusión deliberada en `tests/conftest.py`.
- **Remediación:** Añadido paso `Baterías standalone herméticas (P0-2 y D-010 HANDS)` ejecutando `python tests/run_all.py --hermetic`.
- **Documentación de exclusiones:** Exclusiones de Linux documentadas en el workflow (`test_live_boot.py`, `test_live_execution*.py` dependientes de Windows y sesión de Chrome).

### P0-3. Honest Failure Accounting (`tests/run_all.py`)
- **Problema:** Baterías con crashes ("SIN RESUMEN") o exit code != 0 no se contabilizaban en el total de fallos del runner.
- **Remediación:** Conteo estricto de crashes y códigos de salida no nulos sumados al total `resumen["fallos"]`.
- **Verificación:** `tests/test_run_all_accounting.py`.

### P0-4. Orden de Middlewares Starlette (`backend/main.py`)
- **Problema:** El orden inverso de middlewares en Starlette provocaba que `auth_guard` interceptara preflights `OPTIONS` devolviendo 401 sin cabeceras CORS. Respuestas 401/403 carecían de `X-Content-Type-Options`.
- **Remediación:** Declaración corregida para que `SecurityHeadersMiddleware` y `CORSMiddleware` sean los más externos. `auth_guard` exime explícitamente `OPTIONS`.
- **Verificación:** `tests/test_p0_4_middleware_order.py`.

### P0-5. Mitigación de DNS Rebinding (`backend/security.py`)
- **Problema:** `origin_allowed` aceptaba `Origin == Host` sin validar si el `Host` era confiable.
- **Remediación:** Función `is_trusted_host` que valida que el Host pertenezca a la allowlist (`localhost`, `127.0.0.1`, `[::1]`, o `ALLOWED_HOSTS`).
- **Verificación:** `tests/test_p0_5_dns_rebinding.py`.

---

## 2. Prioridad 1: Tests Rotos

### P1-1. Hermeticidad en Viral Clipper (`tests/test_int048..053`)
- **Problema:** Pruebas hacían DNS real contra dominios externos (`getaddrinfo`).
- **Remediación:** Patch hermético de resolución DNS en `tests/conftest.py` para suites de integración.

### P1-2. Robustez de Símbolos (`tests/test_int088_app_modular_split.py`)
- **Problema:** Conteo mágico `N_FUNCS = 183` vs 189 funciones reales.
- **Remediación:** Validación robusta: 189 funciones únicas, cero colisiones de nombres entre módulos de frontend y presencia de símbolos críticos.

### P1-3. Modernización de Pruebas (`test_int025`, `test_int028`, `test_flow_startframe_fase2`)
- **Problema:** Pruebas buscando código en `app.js` (ahora modular) y dependencia externa de binario `rg`.
- **Remediación:** Adaptadas a la SPA modular y reemplazo de `rg` por `rglob` en Python estándar.

---

## 3. Prioridad 2: Calidad Real de Video

### P2-1. Umbral y Reintento de Placeholders (`backend/pipeline/orchestrator.py` & `video_qa.py`)
- **Problema:** 5/7 escenas podían ser tarjetas planas sin detener el pipeline.
- **Remediación:** Umbral configurable `MAX_ALLOWED_PLACEHOLDERS = 1`. Reintento automático de escenas placeholder primero en Flow (timeout 300 s) y luego en Gemini. Si el umbral se supera, el proyecto se marca `REVIEW_REQUIRED` / `FAILED`, jamás `ready`. `video_qa` reporta `ERROR` explícito.
- **Verificación:** `tests/test_p2_1_placeholder_threshold.py`.

### P2-2. Rediseño de la Cadena de Codificación (`backend/pipeline/video.py`)
- **Problema:** Clips comprimidos reiteradamente (CRF 20 $\rightarrow$ 18 $\rightarrow$ 20).
- **Remediación:** Intermedios casi sin pérdida con CRF 10 `ultrafast`. Un único pase final de alta calidad a CRF 18 `veryfast` con evaluación dinámica de aceleración hardware NVENC (`h264_nvenc`).
- **Medición empírica:** Ganancia de **+5.01 dB de PSNR** comprobada con `tests/benchmark_video_quality.py`.
- **Verificación:** `tests/test_p2_2_video_encoding_chain.py`.

### P2-3. Audio Broadcast Loudnorm (-14 LUFS)
- **Problema:** Normalización de audio apagada o inconsistente.
- **Remediación:** Activada por defecto (`AUDIO_MASTER_BROADCAST = 1`, `RENDER_LOUDNORM = 1`).
- **Verificación:** `tests/test_p2_3_audio_loudnorm.py` usando filtro `ebur128` de FFmpeg validando -14 LUFS (±1.5) y 48 kHz.

### P2-4. Ken Burns Zoompan Jitter y Factor Seguro 4K
- **Problema:** Posible temblor o desbordamiento de memoria en 4K.
- **Remediación:** Medición empírica demostró que zoompan a 1x produce temblor (std=5.93 px), mientras que $\ge 2\times$ lo elimina (std=1.38 px). Función `safe_kenburns_scale` acota la dimensión intermedia a un máximo de 4320 px para prevenir OOM en 4K.
- **Verificación:** `tests/test_p2_4_kenburns_jitter.py`.

### P2-5. Streaming Rápido Web (`-movflags +faststart`)
- **Problema:** Videos no iniciaban reproducción inmediata en el navegador.
- **Remediación:** Inclusión obligatoria de `-movflags +faststart` en el multiplexado final.
- **Verificación:** `tests/test_p2_5_faststart.py` inspecciona los primeros 4096 bytes del archivo MP4 y certifica que el átomo `moov` precede físicamente a `mdat`.

### P2-6. GAP-002 Flow Start Frame
- **Estado:** **NOT_DEMONSTRATED**. Se redactó el checklist obligatorio de 10 puntos en `PROJECT_STATE.md`. Cero simulación ni mocks declarados como E2E.

---

## 4. Prioridad 3: Mantenibilidad

### P3-1. Modularización de Routers
- **Remediación:** `backend/routers/niches.py` (`APIRouter`) implementado y probado en Fase 1. Plan completo documentado en `backend/routers/README.md`.
- **Verificación:** `tests/test_p3_1_routers_phase1.py`.

### P3-2. Lifespan y Control de Excepciones
- **Remediación:** Migración de `@app.on_event("startup")` a `@asynccontextmanager lifespan(app)` en `backend/main.py`. Reemplazo de bloques `except Exception: pass` por logging estructurado con trazabilidad causal en `images.py`, `orchestrator.py` y `main.py`.
- **Verificación:** `tests/test_p3_2_lifespan_and_error_handling.py`.

### P3-3. Integridad de Documentación
- **Remediación:** Conteo unificado de 53 baterías y tabla corregida en `ESTADO_REAL.md`. Estado unificado en `PROJECT_STATE.md`. Confirmación de revocación de PAT y registro de `AUDIT-006` en `07_FAILURES/FAILURE_INDEX.md`.
- **Verificación:** `tests/test_p3_3_docs_integrity.py`.
