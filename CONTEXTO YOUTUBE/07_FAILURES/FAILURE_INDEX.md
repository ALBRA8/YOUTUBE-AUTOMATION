# FAILURE INDEX

## FAIL-001 — Declaración histórica de Flow Bridge real sin código presente
- **Estado:** incidente histórico documentado en `ESTADO_REAL.md`.
- **Descripción:** se reportó un Flow Bridge terminado que entonces no existía en repo (sin commit/rama/stash).
- **Consecuencia:** se reforzó `tests/test_humos_infra.py` y el inventario honesto.
- **Lección:** ninguna capacidad se declara terminada sin código localizable y tests que respalden la afirmación.

## GAP-002 — Start Frame Google Flow no contractual ni demostrado
- **Estado:** OPEN / NOT_DEMONSTRATED; no llamar fallo real observado.
- **Descripción:** no hay contrato verificable y no se encontró binding en camino Flow auditado.
- **Acción:** capturar request real antes de implementar.

## RISK-003 — Secretos en HAR
- **Estado:** riesgo abierto con mitigación definida.
- **Mitigación:** sanear cookies, tokens, credenciales, datos personales y URLs firmadas antes de compartir.

## RISK-004 — Confundir respuesta con request
- **Estado:** regla de auditoría.
- **Descripción:** mediaId en respuesta no demuestra mediaId enviado como input.

## FAIL-005 — Telemetría nula en LIVE Gate por ingestión restrictiva de fetch(Request)
- **Estado:** RESOLVED LOCALLY & VERIFIED (PENDING LIVE GATE).
- **Incidencia:** En el LIVE Gate del commit `85ab666bc283509c1617feabefc98aee3bac5ed4`, Google Flow renderizó el video real con Start Frame, pero `window.__FLOW_RPC_OBS__` emitió valores `null` en todos sus campos de telemetría (`LIVE FAIL`).
- **Causa Raíz Forense:** Google Flow invoca `window.fetch` pasando una instancia de `Request` (`fetch(new Request(url, ...))`) sin proveer un objeto `init`. El interceptor de `extension/injector.js` leía únicamente `init ? init.body : null`, provocando que `parseFreqEntries(null)` devolviera `[]` y el parser posicional nunca fuera alcanzado.
- **Solución implementada:** Ingestión polimórfica en `extension/injector.js` mediante clonación segura preventiva `input.clone().text()`, duck-typing cross-realm para `URLSearchParams`/`FormData`, aislamiento pasivo de `ReadableStream`, corrección F5 de precedencia explícita (`hasExplicitBody`) y coordinación causal de eventos de telemetría (`onSettled`).
- **Mitigación verificada:** 244/244 tests aprobados en laboratorio (F1: 64, F2: 67, eb1hJf Dual+F5: 58, Harness: 55).
- **Acción pendiente:** Solicitud de autorización de LIVE Gate para verificación en producción.

## AUDIT-006 — Hallazgos de Auditoría Técnica 2026-11-06 (Remediación Quirúrgica P0-P3)
- **Estado:** RESOLVED & VERIFIED IN CI / SUITES HERMÉTICAS.
- **P0-1 (SEC-001 SSRF en Modo Producto):** `backend/pipeline/images.py` invocaba `urllib.request.urlopen` sin filtro de seguridad. Remedidado integrando `security.safe_fetch_bytes` (rechaza loopback, IPs privadas, metadata 169.254, esquemas no-http y valida redirecciones). Test: `test_p0_1_product_ssrf.py`.
- **P0-2/P0-3 (CI-001 Aislamiento de Suites y Contabilidad en CI):** 23 baterías no corrían en GitHub Actions. Se configuró `python tests/run_all.py --hermetic` en `.github/workflows/ci.yml` y se corrigió la contabilidad para computar cualquier salida != 0 o crash como fallo explícito. Test: `test_run_all_accounting.py`.
- **P0-4 (SEC-002 Inversión de Middlewares Starlette):** Con `MASTER_API_KEY`, preflights `OPTIONS` y respuestas 401/403 salían sin cabeceras CORS ni `X-Content-Type-Options: nosniff`. Se reordenó la pila colocando `security_headers` y `CORSMiddleware` como capas más externas y eximiendo preflight de auth. Test: `test_p0_4_middleware_order.py`.
- **P0-5 (SEC-003 DNS Rebinding en Origin==Host):** `origin_allowed` permitía ataques de DNS rebinding con Host externo sin autenticación. Se implementó validación estricta de `is_trusted_host`. Test: `test_p0_5_dns_rebinding.py`.
- **P1-1 (NET-001 DNS Hermético en Tests):** Tests de viral clipper resolvían DNS en vivo causando cuelgues; hermetizados mediante mock socket getaddrinfo. Tests: `test_int048..053`.
- **P1-2/P1-3 (TESTS-001 Modernización de Baterías de Tests):** Ajustada la cuenta exacta en `test_int088` (189 funciones top-level sin colisiones de nombres), actualizada la aserción de Agente General en SPA modular (`test_int028`, `test_int025`) y reemplazado `rg` binario por Python `rglob` puro (`test_flow_startframe_fase2.py`).
- **P2-1 (QA-001 Umbral y Reintento de Placeholders):** Detección temprana en `orchestrator.py` con umbral configurable `MAX_ALLOWED_PLACEHOLDERS=1`, reintento con Flow/Gemini y marcaje a `failed` si persiste. Reportado en `video_qa.py`. Test: `test_p2_1_placeholder_threshold.py`.
- **P2-2/P2-5 (VID-001 Codificación Única de Calidad y Faststart):** Eliminada la degradación generacional por re-codificación en cadena (CRF 20->18->20); rediseñado a intermedios casi sin pérdida (CRF 10 ultrafast) y única codificación final de alta calidad (CRF 18 veryfast / NVENC) con `-movflags +faststart` para streaming web inmediato (+5.01 dB de ganancia en PSNR y mayor SSIM comprobado por benchmark). Tests: `benchmark_video_quality.py`, `test_p2_2_video_encoding_chain.py`, `test_p2_5_faststart.py`.
- **P2-3 (AUD-002 Audio Broadcast -14 LUFS por Defecto):** Activada normalización broadcast `AUDIO_MASTER_BROADCAST=1` y `RENDER_LOUDNORM=1` por defecto, verificando 48000 Hz e integrated loudness -14 LUFS con ffmpeg ebur128. Test: `test_p2_3_audio_loudnorm.py`.
- **P2-4 (VID-002 Jitter en Zoompan Ken Burns):** Medido jitter std(accel)=5.93 a 1x y 2.87 a 2x; corregido con `safe_kenburns_scale` acotando la dimensión intermedia máxima a 4320 px para mitigar jitter sin agotar memoria en 4K. Test: `test_p2_4_kenburns_jitter.py`.
- **P2-6 (FLOW-002 Start Frame NOT_DEMONSTRATED):** Checklist mandatorio de 10 puntos de captura real documentado; estado formalmente NOT_DEMONSTRATED. Test: `test_p2_6_startframe_status.py`.
- **P3-1 (ARCH-001 Modularización de main.py):** Plan formal de 5 fases para desacoplar los 167 endpoints de `main.py`; Fase 1 ejecutada con `backend/routers/niches.py` vía `APIRouter`. Test: `test_p3_1_routers_phase1.py`.
- **P3-2 (API-001 Migración a Lifespan y Hardening de Excepciones):** Eliminados handlers obsoletos `@app.on_event("startup")` migrando a context manager `lifespan(app)`; erradicadas excepciones devoradas con `pass` silencioso en el pipeline y publicación, incorporando logs con contexto y trazabilidad completa. Test: `test_p3_2_lifespan_and_error_handling.py`.
- **P3-3 (DOC-001 Corrección de Métricas y Estado):** Corregido `ESTADO_REAL.md` (declaraba 35 baterías, hay 53 reales; reparada tabla rota de EXECUTION CONTRACT), unificados los bloques de Estado de `PROJECT_STATE.md` y confirmada la revocación formal del PAT histórico.

