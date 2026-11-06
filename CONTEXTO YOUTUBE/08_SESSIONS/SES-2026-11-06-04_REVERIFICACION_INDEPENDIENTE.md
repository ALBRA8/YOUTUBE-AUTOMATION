# SES-2026-11-06-04 · Re-verificación independiente de la auditoría de 12 puntos (P0-1 a P2-5)

Fecha: 2026-11-06 · Modelo: Z.ai/GLM · Repo: ALBRA8/YOUTUBE-AUTOMATION (base de verificación: bd5db7f)

## Contexto

La auditoría de verificación (12 puntos) fue implementada en los commits
e092263…3a703e9 por el constructor anterior. Esta sesión la RE-VERIFICÓ de
forma independiente, punto por punto, con comandos reales, y encontró UN
defecto real (P2-3) que corrigió con su propio commit (1a72157).

## Verificación por punto (evidencia real, sandbox Linux)

| Punto | Veredicto | Evidencia ejecutada en esta sesión |
|---|---|---|
| P0-1 | PASS | `python -m py_compile launchers/lanzador_albra.py` OK; BASE con 2 paréntesis (`ast.unparse`); test 8/8 (`py_compile.compile(doraise=True)` + `ast.parse` + eval real de BASE); CI paso "Sintaxis de todo el repo (compileall, P0-1)"; lanzador ejecutado: exit 0 |
| P0-2a | PASS | `services/ugc_ad_generator.py:85` usa `security.safe_fetch_bytes` (validar_url + tope tamaño + redirects revalidados) |
| P0-2b | PASS | `main.py:3259` studio usa `safe_fetch_bytes` (comentario P0-2 en 3257-3258); `main.py:1197` validar_url en modo producto |
| P0-2c | PASS | `tests/test_p0_2_ssrf_guard.py` 2/2: guardia AST sobre backend/**.py, whitelist documentada (security.py, mcp_manager CDP 127.0.0.1, hands/flow_operator transporte inyectable, _dev_wait_open) |
| P0-2d | PASS | `tests/test_p0_2_ssrf_siblings.py` 7/7; `test_p0_1_product_ssrf.py` 1/1 (file://, 127.0.0.1, 169.254.169.254, 192.168.1.1, redirect interno — rechazados en cada endpoint; este test genera imágenes reales vía Pollinations como fallback: lento pero funcional) |
| P0-3 | PASS | `PROJECT_STATE.md:39` y `FAILURE_INDEX.md:45`: "PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO"; cero restos de "revocado formalmente" en los docs |
| P1-1 | PASS | `tools/medir_jitter_kenburns.py` + `resultados_jitter_kenburns.md` (A 0.42 → B 0.22 px, ~48% menos; RSS real 1354 MB vs 734 MB; C NOT_DEMONSTRATED en sandbox 3 GB, honesto); ruta B implementada en `pipeline/video.py:188-196` (factor < 2.0 → zoompan 1080p 2x + upscale lanczos) |
| P1-2 | PASS | `backend/video_encode.py` módulo neutral (política final CRF 18 + faststart / intermedio CRF 10 ultrafast); 6/7 services con refs al helper; `video_retimer` documentado como INTERMEDIO en la tabla de rutas del propio video_encode.py (crf/preset parametrizados, sin faststart requerido por política) |
| P1-3 | PASS | `tools/medir_codificacion.py` + `resultados_codificacion.md`: (a) veryfast≈medium≈slow SSIM a 1080p; (b) intermedio CRF10 4K = 117 MB/min + limpieza `cleanup_intermediates()`; (c) rotate +162% tiempo, SSIM 0.99464, decisión documentada |
| P1-4 | PASS (VMAF parcial) | `tests/benchmark_video_quality.py` (110 líneas, reproducible) + `resultados_benchmark_video.md`: A 46.03 → B 51.04 dB PSNR (+5.01 dB ahora REPRODUCIDO por script), SSIM 0.998686 > 0.997187. VMAF completo NOT_DEMONSTRATED (ffmpeg del sandbox sin libvmaf; solo vmafmotion) — honesto |
| P1-5 | PASS | `config.py:170` lectura centralizada (cero `os.getenv("MAX_ALLOWED_PLACEHOLDERS")` fuera de config.py); gate `_gate_imagenes_reales` invocado en `orchestrator.py:343` (start_flow_render — "el orquestador MCP entra por aquí") y :740; `test_p1_5_placeholder_gate.py` 4/4 |
| P2-1 | PASS | `test_p2_1_smoke_render.py`: 3 escenas sintéticas Ken Burns → concat → voz+loudnorm −14 LUFS → encoder final; verifica duración, resolución, moov ANTES de mdat (faststart) y cero placeholders con el MISMO detector de producción |
| P2-2 | PASS | `test_p2_2_except_ratchet.py` BASELINE=283 (no sube); visibilidad en los 3 traga-errores del render |
| P2-3 | **DEFECTO ENCONTRADO → CORREGIDO (commit 1a72157)** | El fix anterior dejaba duplicados REALES: `api_route` multi-método con `operation_id` explícito asigna EL MISMO id a cada método (GET+HEAD / → dashboard_index x2; GET+POST /mcp → mcp_proxy_sin_barra x2; reproducido con `app.openapi()` + Counter). Y su test pasaba EN FALSO: buscaba subcadena "operation_id" (guion bajo) pero el warning dice "Operation ID" (espacio). Corregido: `/` → @app.get(dashboard_index) + @app.head(dashboard_index_head, include_in_schema=False); `/mcp` → @app.get(..._get) + @app.post(..._post); test reescrito con 2 vías independientes (regex `operation[ _-]?id` + conteo REAL de operationId repetidos en el esquema). Evidencia: test+p3_1 → 5 passed; `app.openapi()` → 0 warnings; smoke TestClient HEAD / 200, GET /mcp 200, POST /mcp 400 (esperado) |
| P2-4 | PASS | LEEME "Última sesión" entradas ≤3 líneas con puntero a archivo; ROADMAP línea 19: "verificadas por test de COMPILACIÓN ast/py_compile + compileall (P0-1 cerrado)"; archivo 08_SESSIONS/SES-2026-11-06-03 existe |
| P2-5 | PASS (preparado, NO ejecutado) | `tools/fase3_aceptacion.py`: criterios codificados en `evalua_protocolo()`, uso documentado, cabecera "PREPARADO, NO EJECUTADO (NOT_DEMONSTRATED)"; sin multi-cuenta ni hoja de contacto añadidas |

## Suites completas (números honestos)

- **Antes** (estado 6ccddef, sesión anterior de emparejamiento): pytest 507/0.
- **Después** (esta sesión, bd5db7f + fix 1a72157):
  - `python -m pytest tests/ -q`: **534 passed en 0:03:06, 0 warnings**
    (la primera pasada a bd5db7f daba 534 passed PERO 2 warnings de
    "Duplicate Operation ID" — de ahí el defecto P2-3).
  - `python tests/run_all.py` (53 baterías, ejecutadas una a una con el
    patrón de subshell desacoplado, timeout individual 100-110 s, resumen
    "N OK · M fallos" por batería): **2627 OK · 0 fallos en 53/53 baterías**,
    incluidas las 3 históricamente problemáticas en sandbox:
    - 20 test_int025_google_session: 77 OK · 0
    - 24 test_security_hardening: 47 OK · 0
    - 51 test_int028_general_agent: 65 OK · 0
    (Los "colgados" previos eran el patrón de sesión del sandbox —nietos de
    proceso reteniendo la sesión—, no defectos del código: al desacoplar la
    batería en subshell propio, las tres pasan limpias.)

## Commits de esta sesión

- `1a72157` fix(P2-3): operation_id POR MÉTODO en / y /mcp — OpenAPI a 0
  warnings de verdad (main.py + test reescrito).
- Cierre de sesión: LEEME_PRIMERO (entrada ≤3 líneas), ROADMAP (HECHO) y
  este archivo de detalle.

## Pendiente / notas para el dueño

- P1-4: VMAF completo requiere ffmpeg con libvmaf (máquina del dueño);
  el script `tests/benchmark_video_quality.py` ya lo detecta dinámicamente.
- Fase 3 (P2-5): ejecutar en máquina del dueño con Flow real
  (`python tools/fase3_aceptacion.py --nichos "A,B" --objetivo 10`).
- PAT: sigue PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO (revocar/rotar el
  token que circuló por el chat).
