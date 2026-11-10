# ROADMAP
## AHORA (máximo 2)
- Fase 3 · Aceptación: 10 videos seguidos en 2 nichos; cero placeholders; cero
  "listos" con fallos de QA; el dueño revisa una muestra. Meta: 8/10 sin
  intervención manual.
- Start Frame de Flow (sujeto a captura real de red según checklist en PROJECT_STATE).
## SIGUIENTE
- Validación del dueño con Chrome real (X2/X4): en su PC, «Conectar todo» con
  Chrome ya abierto y visible NO debe cerrarlo ni relanzarlo; caído o zombi
  debe purgar y reabrir con ventana forzada; el detalle del error («Chrome no
  abrió (…)») debe verse en el panel. En sandbox: NOT_DEMONSTRATED.
- «Conectar todo» y rutas verificadas (W1-W4): connect_all_google robusto
  con relanzamiento forzado, timeout 30s configurable y reporte de
  chrome_up honesto (W1-W2); catálogo de rutas críticas comprobadas por el
  dueño (W3). La verificación con Chrome y servidores MCP reales en la PC
  del dueño queda como NOT_DEMONSTRATED (sandbox sin Chrome de escritorio).
- Panel MCP (U1-U7): verificación VISUAL en navegador real por el dueño
  (semáforos, Avanzado, selector nicho/cuaderno, gate del Run) — en el
  sandbox no hay Chrome de escritorio: NOT_DEMONSTRATED. Decisión sobre
  el default de contexto del NotebookLM (chat_ask → notebook_query) y
  migración de las tools legacy de nlm_studio al catálogo real de
  notebooklm-mcp-server v0.1.15 (ver INT-093).
- Minidramas NotebookLM+Flow: registro y validador endurecidos (R1-R6 +
  cierre Q1-Q6, ver HECHO). Pendiente del dueño: correr la sonda INT-093
  en su máquina (q1-q7 hoy NOT_DEMONSTRATED), activar
  FLOW_REGISTRO_SYNC solo si la sonda demuestra q7 SOPORTADO, decidir
  diálogo A/B/C y duraciones (spec PENDIENTE DEL DUEÑO) y ejecutar el
  piloto mínimo Gate 0/Gate 3 con Flow real (checklist y observador
  listos). La sonda INT-093 ahora lee por HTTP del backend en marcha
  (Y2): correrla es `python tools/sonda_capacidades_nombres.py --salida
  sonda_nombres.json` con el panel conectado (q1-q10 hoy
  NOT_DEMONSTRATED).
- Google Flow Multi-Cuenta: balanceador de cuentas en mcp_manager para rotación
  automática de créditos Veo (inspirado en análisis Sloth v0.3.48).
- Hoja de contacto visual (hoja de escenas con safe zones) para QA instantáneo.
## DESPUÉS
- Autopublicación y modo fábrica a escala.
- Fase 2 de modularización de routers en backend (auth, projects, rendering).
## EN RESERVA (no tocar)
- HANDS (control manual del PC): dormido.
## HECHO
- Remediación estática y linting CI (Z1-Z4, 2026-11-10):
  Z1 import subprocess a nivel de módulo en main.py para evitar NameError en
  lipsync-musetalk (f13a2b5; test AST y de atributo en test_z1_main_subprocess.py).
  Z2 test hermético del endpoint POST /api/avatars/{avatar_id}/lipsync-musetalk
  con dobles (edge_tts, ffmpeg/subprocess.run y render_avatar_animation),
  verificando camino exitoso 200 y fallo claro ante error de ffmpeg (9fef4f9;
  test_z2_lipsync_musetalk.py).
  Z3 eliminación de _probe_nvenc duplicada y referencia huérfana a ENABLE_NVENC
  en pipeline/video.py, re-exportando la versión canónica de video_encode (8b7c8a1;
  test_z3_video_probe_nvenc.py).
  Z4 paso ruff en CI (.github/workflows/ci.yml) verificando reglas críticas
  F821, E9, F63, F7 y F82 sobre backend y tools con 0 hallazgos; corrección de
  F821 en qa_forensics_checker.py (import Any) y redefiniciones redundantes
  de sys en mcp_manager.py (97163cf; test_z4_ruff_ci.py).
- Catálogo por HTTP y sonda sin procesos duplicados (Y1-Y3, 2026-11-10):
  Y1 `GET /api/mcp/catalogo/{service}` devuelve {service, server_info,
  tools:[{name, description COMPLETA, inputSchema}]} LEYENDO la conexión
  ya activa del backend (`tools_catalog(auto_connect=False)`); NO conecta,
  NO lanza procesos y NUNCA ejecuta tools — sin conexión → 409 «conecta
  primero desde el panel», desconocido → 404 (434b3f1; dobles conectado/
  no conectado/desconocido). Y2 la sonda INT-093 usa ese endpoint por
  DEFAULT (127.0.0.1:PORT de backend/.env, X-API-Key si hay
  MASTER_API_KEY, timeout 10 s, mensaje claro si el backend no responde);
  la vía antigua queda SOLO detrás de --modo-local con aviso de procesos
  duplicados; --crear-prueba intacta; el informe guarda description
  completa + inputSchema íntegro; q5 corregida por capacidad y esquema
  (notebook_add_text con title opcional = SOPORTADO; source_add legacy
  sigue valiendo) y 3 preguntas nuevas de Flow con veredicto por esquema
  (q8 nombre solo-esquema, q9 qué devuelve id/URL/nada, q10 id de
  proyecto en generate/upload) (40a802d). Y3 .gitattributes con
  eol=crlf para .bat/.cmd/.vbs (repo normalizado, checkout CRLF;
  contenido de lanzadores verificado byte a byte) y test X3 extendido
  (CRLF simple permitido, \r\r\n prohibido) (6181b1e). Veredictos reales
  de Flow/NotebookLM: NOT_DEMONSTRATED hasta que el dueño corra la sonda
  con el backend en marcha.
- Higiene CI, Chrome sano y detalle visible (X1-X4, 2026-11-10): X1
  ESTADO_REAL.md declara las 59 baterías reales de run_all — CI en rojo por
  «58» obsoleto (09c277f); X2 connect_all_google chequea salud ANTES de
  purgar: Chrome sano (CDP arriba + ventana visible) NUNCA se mata ni se
  relanza; solo caído o zombi se purga con kill_profile_processes + heal y
  relanza con force_window=True con sondeo de 30 s (c9eb0b9; dobles en
  test_x2_connect_all_no_mata_sano.py; INT-043 recalibrado al contrato
  nuevo); X3 app-mcp.js a LF puro (874 líneas CRCRLF) + .gitattributes
  (eol=lf en .py/.js/.html/.css/.md/.json/.txt/.yml/.sh, binarios marcados,
  .bat/.vbs excluidos a propósito) + test en modo binario anti \r\r\n, sin
  grep línea a línea (544e166; ancla U3 recalibrada: el CRCRLF simulaba una
  línea en blanco bajo read_text); X4 el panel «Conectar todo» muestra el
  detalle del error en el TEXTO visible («Chrome no abrió (…): pulsa «Abrir
  ventana de Chrome» en Avanzado») y si la llamada misma falla el detalle
  también queda visible (104e1ee). Con Chrome real en la PC del dueño:
  NOT_DEMONSTRATED (pendiente de su validación).
- Robustez «Conectar todo» y salvaguarda de rutas verificadas (W1-W4, 2026-11-07):
  W1 `connect_all_google` relanza con `force_window=True` cuando el puerto CDP
  no responde o detecta un zombi sin ventana visible, sondea cada 0.5s hasta
  timeout configurable (default 30s) y devuelve `chrome_up` y `chrome_error`
  explícitos sin falsear con `ok` (7ddcbf4); W2 panel `gsessConnectAll` muestra
  el resultado real de la respuesta, guiando al usuario hacia «Abrir ventana
  de Chrome» en Avanzado si `chrome_up` es false (adc5f93); W3 catálogo de
  rutas verificadas por el dueño en `CONTEXTO YOUTUBE/00_MASTER/RUTAS_VERIFICADAS_POR_EL_DUENO.md`,
  regla de oro 8 en `LEEME_PRIMERO.md` y guardia estática `test_w3_rutas_verificadas.py`
  que impide retirar o desvincular del panel o backend las rutas críticas comprobadas
  en la máquina del dueño (a8ff771); W4 cierre y verificación (tests herméticos con
  dobles; comportamiento con Chrome real en NOT_DEMONSTRATED).
- Panel MCP honesto (U1-U7, 2026-11-07): U1 agregador SOLO LECTURA
  GET /api/mcp/resumen (semáforo por pieza chrome CDP/flow/notebooklm/
  cuaderno + listo_para_pipeline + siguiente_paso en español; todo_
  conectado SOLO con las 4 piezas ok, 7922428); U2 tarjeta única
  «Ecosistema Google» con 3 filas de semáforo REAL de U1, badge verde
  solo si todo_conectado y «Conectar todo» → connect-all-google con
  aviso de login en la ventana (4b5787b); U3 bloque plegado «Avanzado»
  (tarjetas por servicio, Test Pipeline, reparar, consola) con volcado
  de stderr SOLO ahí y aviso humano de FastMCP («no afecta»)
  (ca1594f); U4 selector nicho+cuaderno en la tarjeta principal,
  auto-relleno al conectar y memoria POR NICHO en el registro Q4,
  vacíos que dicen qué hacer (d2bb932); U5 Run Full Pipeline
  deshabilitado con motivo exacto mientras listo_para_pipeline=false
  y guardia ANTES del POST (97ba839); U6 paquete real notebooklm-mcp-
  server v0.1.15 vs server_info 2.14.5=FastMCP corregido en panel/
  docstring/INT-093 + trinquete de catálogo (683d766). Baterías nuevas
  (58 en run_all): test_u1_mcp_resumen (11) + test_u_panel_ecosistema
  (20) + test_u6_catalogo_contrato (7). Lo visual en navegador real:
  NOT_DEMONSTRATED (sandbox sin Chrome de escritorio) — pendiente del
  dueño. La lógica de conexión (mcp_manager/GoogleFlowMCP) intacta.
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
