# ROADMAP
## AHORA (máximo 2)
- Fase 3 · Aceptación: 10 videos seguidos en 2 nichos; cero placeholders; cero
  "listos" con fallos de QA; el dueño revisa una muestra. Meta: 8/10 sin
  intervención manual.
- Start Frame de Flow (sujeto a captura real de red según checklist en PROJECT_STATE).
## SIGUIENTE
- Minidramas NotebookLM+Flow: registro y validador endurecidos (R1-R6 +
  cierre Q1-Q6, ver HECHO). Pendiente del dueño: correr la sonda INT-093
  en su máquina (q1-q7 hoy NOT_DEMONSTRATED), activar
  FLOW_REGISTRO_SYNC solo si la sonda demuestra q7 SOPORTADO, decidir
  diálogo A/B/C y duraciones (spec PENDIENTE DEL DUEÑO) y ejecutar el
  piloto mínimo Gate 0/Gate 3 con Flow real (checklist y observador
  listos).
- Google Flow Multi-Cuenta: balanceador de cuentas en mcp_manager para rotación
  automática de créditos Veo (inspirado en análisis Sloth v0.3.48).
- Hoja de contacto visual (hoja de escenas con safe zones) para QA instantáneo.
## DESPUÉS
- Autopublicación y modo fábrica a escala.
- Fase 2 de modularización de routers en backend (auth, projects, rendering).
## EN RESERVA (no tocar)
- HANDS (control manual del PC): dormido.
## HECHO
- Cierre Q1-Q6 del registro/sonda/validador (2026-11-07): Q1 punto de
  paso común en database.create_project — TODO proyecto de las 13 vías
  reales (API, A2A, clipper, 3 tools MCP, agente general, scheduler,
  arnés) queda con registro.json, idempotente, sin duplicados (cbd4c9e);
  Q2 sonda INT-093 q6 (¿la generación acepta id de proyecto/destino?) y
  q7 (¿new_project cambia el proyecto activo?) SOLO LECTURA con veredictos
  del trío y evidencia de esquema (aefe0c5); Q3 disparo de
  sincronizar_flow_real vía asyncio.to_thread al empezar la fase Flow en
  sus DOS puertas (cola de la extensión y orquestador inline), solo con
  FLOW_REGISTRO_SYNC=1, fire-and-forget, limitación con veredicto literal
  grepeable (9fa5db8 + 00bab1e); Q4 POST/GET /api/registro/nicho con la
  misma auth que /api, un cuaderno por nicho, propaga_notebook deja de
  callar (7834bd0); Q5 aviso HABLA_SIN_COMILLAS_POSIBLE (texto tras «:»
  supera el límite, sea cual sea el verbo) + dialogue documentado como
  fuente de verdad y recomendado obligatorio en el contrato (96b5875 +
  7cd1d35). Todo hermético con dobles; lo que exige Flow real sigue
  NOT_DEMONSTRATED (sonda pendiente de correrse en la máquina del dueño).
- Registro de producciones y su conexión con Flow (R1-R6, 2026-11-07):
  R1 estado falso eliminado (sin id del MCP → ERROR + limitación,
  ccc8c19); R2 production_id validado (escapes ../, absolutas,
  separadores, contención en OUTPUT_DIR, 543ed90); R3 escritura atómica
  + lock por nicho anti-carreras + JSON corrupto con aviso sin reutilizar
  números (255aa48); R4 registro local conectado a la creación de
  proyectos sin duplicar (39b6bf9); R5 adaptador real crear_proyecto
  (flow_mcp_client.new_project) tras gate FLOW_REGISTRO_SYNC con veredicto
  guardado de la sonda INT-093 — sin informe → NOT_DEMONSTRATED, sin
  nombre a Flow (8567229); R6 regla de la raya en el validador Fase E
  (acotación narrativa ≠ diálogo; solo tras verbo de habla, «:» o inicio
  de línea, 4299c6a). Todo hermético con dobles de MCP; Flow real queda
  NOT_DEMONSTRATED hasta la sonda en la máquina del dueño.
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
