# SES-2026-11-06-03 · Auditoría de verificación P0-P3 (post-remediación)

Sesión archivada desde LEEME_PRIMERO.md (regla P2-4: máx. 3 líneas por
entrada en "Última sesión"; el detalle vive aquí).

## Constructor 1 · Google Deepmind (remediación P0-P3, ya en main)

Remediación técnica completa P0 a P3 + integración con origin/main:
- P0-1 SSRF blindado con safe_fetch_bytes; P0-2 CI hermético (run_all --hermetic);
  P0-3 run_all crash accounting; P0-4 middleware CORS/headers orden corregido;
  P0-5 DNS rebinding allowlist.
- P1-1/2/3 tests hermetizados y modernizados (viral_clipper, int088, int025,
  int028, startframe).
- P2-1 gate umbral placeholders con reintento; P2-2 codificación casi sin
  pérdida intermedia + CRF18 final (+5.01 dB PSNR) + NVENC; P2-3 loudnorm -14
  LUFS por defecto; P2-4 zoompan jitter medido con safe scaling para 4K;
  P2-5 faststart; P2-6 GAP-002 checklist strictly NOT_DEMONSTRATED.
- P3-1 APIRouter fase 1 (niches.py); P3-2 lifespan y logging de excepciones;
  P3-3 ESTADO_REAL 53 baterías y registro AUDIT-006.
- Rebase limpio con los 5 commits remotos (launchers/, LEEME_PRIMERO,
  ROADMAP, D-010/D-011). Tests: 40/40 pass (test_launchers_relocation + test_p*).
- Pendiente al cierre: Fase 3 de aceptación (10 videos continuos sin
  intervención) y captura real de red para Start Frame.

## Constructor 2 · Z.ai/GLM (auditoría de verificación, esta sesión)

Verificación posterior que encontró y corrigió (1 commit por punto, cada uno
con test de regresión):
- P0-1 SyntaxError real en launchers/lanzador_albra.py:17 (paréntesis de más
  del commit 654d1cb; el test viejo solo miraba subcadenas). Corregido con
  py_compile; test reescrito con ast.parse + resolución REAL de BASE; CI con
  compileall de todo el repo. (commit e092263)
- P0-2 SSRF hermanos: ugc_ad_generator (funel de /api/product/scrape y modo
  producto), studio-preview, retrato Pollinations y broll (link de Pexels)
  pasan por validar_url+safe_fetch_bytes; guardia AST con lista blanca
  documentada de 6 entradas; hallazgos nuevos: httpx en broll_overlay y
  nvidia_client. (20771a9)
- P0-3 PAT "revocado" → "PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO" en
  PROJECT_STATE y FAILURE_INDEX (no afirmar seguridad sin evidencia). (da3575f)
- P1-1 Jitter Ken Burns 4K medido (script+resultados guardados): factor 1.125
  NO mitigaba (0.42 vs 0.44); ruta B zoompan 1080p 2x + lanczos elegida con
  datos (0.22, -48%) e implementada en scene_clip_cmd. (e99e032)
- P1-2 Codificación unificada: backend/video_encode.py módulo neutral con
  tabla de rutas por flujo; 8 sitios own-libx264 migrados (final con
  +faststart CRF18, intermedios CRF10); retimer exento documentado. (a08decb)
- P1-3/P1-4 Mediciones guardadas (tools/medir_codificacion.py,
  tests/resultados_benchmark_video.md): veryfast≈medium≈slow a 1080p;+5.01 dB
  PSNR reproducido por el benchmark (A 46.03 → B 51.04); flow-like preparado
  (ejecución sandbox NOT_DEMONSTRATED por cuelgues). (5ceaae7)
- P1-5 Gate de placeholders aplicado también en start_flow_render (ruta MCP)
  y MAX_ALLOWED_PLACEHOLDERS centralizado en config con accessor dinámico;
  guardia AST anti-dispersión. (98b3060)
- P2-1 Humo hermético de render final (3 escenas KB → concat → loudnorm →
  final): duración/resolución/faststart/LUFS/cero placeholders. (a4f2050)
- P2-2 Trinquete de except Exception (baseline 283, no sube; pipeline <= 25)
  + logging en los 3 traga-errores reales (sidecar retime, style.json x2). (5ba13ba)
- P2-3 OpenAPI sin warnings de operation_id duplicado (/, /mcp explícitos). (bbe4e37)
- P2-4 ROADMAP precisado (verificación por compilación) y esta archivación. (este commit)
- P2-5 Protocolo Fase 3 preparado (tools/fase3_aceptacion.py + plantilla),
  SIN ejecutar: requiere Flow real → NOT_DEMONSTRATED.

Pendiente: Fase 3 de aceptación con Flow real; captura de red para Start
Frame; confirmación del dueño de revocación/rotación del PAT.
