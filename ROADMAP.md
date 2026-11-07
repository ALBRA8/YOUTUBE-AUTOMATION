# ROADMAP
## AHORA (máximo 2)
- Fase 3 · Aceptación: 10 videos seguidos en 2 nichos; cero placeholders; cero
  "listos" con fallos de QA; el dueño revisa una muestra. Meta: 8/10 sin
  intervención manual.
- Start Frame de Flow (sujeto a captura real de red según checklist en PROJECT_STATE).
## SIGUIENTE
- Minidramas NotebookLM+Flow: piloto mínimo de UN episodio corto —
  ejecutar Gate 0/Gate 3 con Flow real (máquina del dueño; checklist y
  observador listos) y resolver las decisiones marcadas PENDIENTE DEL
  DUEÑO en la spec (fuente del diálogo A/B/C; duraciones reales de Flow
  vía sonda). El validador Fase E ya está implementado y probado.
- Google Flow Multi-Cuenta: balanceador de cuentas en mcp_manager para rotación
  automática de créditos Veo (inspirado en análisis Sloth v0.3.48).
- Hoja de contacto visual (hoja de escenas con safe zones) para QA instantáneo.
## DESPUÉS
- Autopublicación y modo fábrica a escala.
- Fase 2 de modularización de routers en backend (auth, projects, rendering).
## EN RESERVA (no tocar)
- HANDS (control manual del PC): dormido.
## HECHO
- Validador editorial Fase E de minidramas (Python puro, sin red/Flow):
  campos del Production JSON, párrafo único, MAYÚSCULAS, conteo
  determinista de palabras habladas con texto excedente, duración
  configurable — 33 tests herméticos (800a80e). Observador solo-lectura
  del piloto mínimo Gate 0/Gate 3 con veredicto PASS/FAIL/
  NOT_DEMONSTRATED — 12 tests herméticos (ae99dbe). Siete enmiendas a la
  spec minidramas (diálogo A/B/C, sonda Flow, Start Frame GAP-002,
  máquinas de estado clip/episodio, conteo de palabras, políticas
  YouTube, fuentes originales) y regresión de higiene (prefijo de PAT
  redactado de SES-05, 4df9036) (2026-11-07).
- Hermeticidad total (H1-H3): guardia de red en pytest (conftest) y en
  baterías run_all (sitecustomize); test de producto con doble de prueba y
  broll sin DNS real; higiene de secretos (prefijo PAT redactado + guardia
  test_h2). Evidencia: pytest 536/0 (58.5 s, cero red) y run_all 2627 OK ·
  0 fallos en 53/53 con internet disponible y bloqueado (2026-11-06).
- Re-verificación independiente de la auditoría de 12 puntos (P0-1 a P2-5):
  11 confirmados con evidencia; P2-3 tenía duplicados reales de operation id
  y test en falso → corregidos (OpenAPI a 0 warnings, 1a72157). Suites
  completas verdes: pytest 534/0 (0 warnings) y run_all 2627 OK · 0 fallos en
  53/53 baterías (2026-11-06).
- INT-091 selector de carpetas; INT-092 timeout Flow 300 s y render 4K (2026-11-06).
- Memoria del repo: LEEME_PRIMERO.md + ROADMAP.md; lanzadores → launchers/
  (rutas verificadas por test de COMPILACIÓN ast/py_compile + compileall
  en CI — P0-1 cerrado 2026-11-06); estado unificado (ESTADO_REAL 53 baterías,
  tabla CONTRACT reparada, PROJECT_STATE un solo Estado, D-010/D-011) y
  baterías HANDS en CI (2026-11-06).
- Auditoría Técnica Fase 1 (P0-1 a P0-5, P1-1 a P1-3): SSRF safe_fetch_bytes,
  CI run_all --hermetic, run_all honest accounting, orden middlewares CORS/auth,
  DNS rebinding mitigado con allowlist de host, tests de viral clipper hermetizados,
  test_int088 robusto, test_int025/028 modernizados (2026-11-06).
- Auditoría Técnica Fase 2 (P2-1 a P2-6): umbral de placeholders (máx 1) con reintento
  Flow/Gemini, codificación de video en cadena optimizada (intermedios CRF 10 ultrafast,
  final CRF 18 con evaluación NVENC y benchmark +5.01 dB PSNR), loudnorm -14 LUFS
  por defecto, zoompan jitter medido empíricamente y factor de escala acotado para 4K,
  -movflags +faststart en MP4 final, GAP-002 checklist formal NOT_DEMONSTRATED (2026-11-06).
- Auditoría Técnica Fase 3 (P3-1 a P3-3): router niches.py APIRouter (Fase 1),
  migración a lifespan y logging estructurado de excepciones, corrección ESTADO_REAL 53
  baterías y registro AUDIT-006 en FAILURE_INDEX (2026-11-06).
