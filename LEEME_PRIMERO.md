# LEEME_PRIMERO
Lee esto ANTES de tocar nada.

## Qué es
YOUTUBE-AUTOMATION: fábrica local de videos con IA. Flujo: guion → imágenes
(Google Flow vía MCP, respaldo Gemini) → voz → render ffmpeg → subtítulos →
música → publicación opcional en YouTube.

## Reglas de oro
1. Nada se declara "terminado" sin un test en este repo que lo respalde.
2. Si no se pudo probar de verdad, escribir NOT_DEMONSTRATED. Nunca adornar.
3. Un cambio por commit, con su test de regresión. Cero refactors oportunistas.
4. No tocar P1 Golden Contract, Creative Engine, Production JSON ni
   leases/heartbeat sin evidencia causal.
5. HANDS está DORMIDO: no se amplía ni se conecta salvo que una herramienta no
   tenga MCP ni API. Sus pruebas siguen corriendo.
6. Nunca guardar secretos (claves, tokens) en el repo ni en las notas.
7. Máximo 2 tareas en AHORA. Lo nuevo entra a SIGUIENTE.
8. Rutas verificadas por el dueño: las rutas `POST /api/mcp/google-sso/launch`
   (con `force_window: true`), `POST /api/mcp/launch-auth-browser`,
   `POST /api/mcp/repair-profile` y `POST /api/mcp/connect` (servicio
   `google-flow`) no se sustituyen ni se cambia su semántica sin evidencia
   de la máquina del dueño (ver CONTEXTO YOUTUBE/00_MASTER/RUTAS_VERIFICADAS_POR_EL_DUENO.md).

## Dónde está cada cosa
- Qué hacer y en qué orden: ROADMAP.md
- Estado real y límites honestos: ESTADO_REAL.md
- Decisiones: CONTEXTO YOUTUBE/01_DECISIONS/DECISION_LOG.md
- Fallos y riesgos: CONTEXTO YOUTUBE/07_FAILURES/FAILURE_INDEX.md

## Al terminar tu sesión (obligatorio)
Actualiza ROADMAP.md (mueve lo hecho, anota lo que falló) y añade una línea
abajo en "Última sesión".

## Última sesión
- Fecha / modelo / qué se hizo / qué quedó pendiente:
- 2026-11-07 · LLM Google Deepmind · robustez «Conectar todo» y salvaguarda de
  rutas verificadas (W1-W4): connect_all_google con relanzamiento forzado y
  sondeo de 30 s (W1, 7ddcbf4), panel con resultado real y guía a Avanzado en
  fallo de Chrome (W2, adc5f93), catálogo RUTAS_VERIFICADAS_POR_EL_DUENO.md,
  regla de oro 8 y guardia estática test_w3 (W3, a8ff771); suite hermética
  limpia, comportamiento con Chrome real NOT_DEMONSTRATED.
- 2026-11-06 · LLM Google Deepmind · remediación P0-P3 completa (SSRF, CI,
  middlewares, DNS rebinding, tests, placeholders, codificación única,
  loudnorm, faststart, routers, lifespan) — detalle: CONTEXTO YOUTUBE/
  08_SESSIONS/SES-2026-11-06-02_AUDITORIA_TECNICA_P0_P3_REMEDIACION_INTEGRAL.md.
- 2026-11-06 · LLM Z.ai/GLM · auditoría de verificación: SyntaxError del
  lanzador corregido (test por compilación + CI), SSRF hermanos cerrados con
  guardia AST, PAT a 'PENDIENTE DE CONFIRMACIÓN', jitter 4K medido y ruta B
  implementada, codificación unificada en video_encode, gate de placeholders
  en flow_render, trinquete de except Exception (283), humo de render,
  OpenAPI limpio y protocolo Fase 3 preparado (sin ejecutar) — detalle:
  CONTEXTO YOUTUBE/08_SESSIONS/SES-2026-11-06-03_VERIFICACION_P0_P3.md.
- 2026-11-06 · LLM Z.ai/GLM · re-verificación independiente de los 12 puntos:
  P2-3 tenía duplicados REALES (dashboard_index y mcp_proxy_sin_barra x2 por
  método en api_route multi-método) y su test pasaba en falso (buscaba
  'operation_id' con guion bajo); corregido id por método + test por conteo
  real del esquema. Evidencia: pytest 534/0 (0:03:06, 0 warnings) y run_all
  2627 OK · 0 fallos en 53/53 baterías (incl. 20/24/51, colgadas solo por el
  patrón de sesión del sandbox, no por código) — detalle: CONTEXTO YOUTUBE/
  08_SESSIONS/SES-2026-11-06-04_REVERIFICACION_INDEPENDIENTE.md.
- 2026-11-06 · LLM Z.ai/GLM · hermeticidad total (H1-H3): pytest 536/0 en
  58.5 s con guardia de red en conftest (cero DNS/internet, antes 3:06 con
  red) y run_all 2627 OK · 0 fallos en 53/53 baterías bajo guardia
  sitecustomize (internet DISPONIBLE y bloqueado, verificado con curl).
  H2: prefijo de PAT redactado de las notas + guardia test_h2; push por el
  dueño — detalle: CONTEXTO YOUTUBE/08_SESSIONS/SES-2026-11-06-05_HERMETICIDAD.md.
- 2026-11-07 · LLM Z.ai/GLM · SES-05 había vuelto a copiar el prefijo del
  PAT → redactado (regresión de higiene 2/2). 7 enmiendas a la spec
  minidramas (diálogo A/B/C, sonda Flow, Start Frame, estados
  clip/episodio con FAILED/BLOCKED/UNVERIFIABLE, conteo de palabras,
  políticas YouTube, fuentes). Validador Fase E (Python puro, 33 tests) y
  observador del piloto mínimo Gate 0/Gate 3 (12 tests) — todo lo que
  exige Flow real queda NOT_DEMONSTRATED; minidramas en SIGUIENTE —
  detalle: CONTEXTO YOUTUBE/08_SESSIONS/SES-2026-11-06-06_VALIDADOR_FASE_E_PILOTO_MINIMO.md.
- 2026-11-07 · LLM Google Deepmind · sincronización y análisis de 25 commits remotos: emparejamiento con origin/main, corrección quirúrgica de escaneo AST en .venv/data (test_p0_2 y test_p2_2) y hermetización de diálogo en test_int091 (0 cuelgues Windows) — suites herméticas limpias.
- 2026-11-07 · LLM Z.ai/GLM · minidramas: validador Fase E ampliado (diálogo estructurado {personaje,texto} + heurística rayas/verbo de habla con aviso DIALOGO_SIN_COMILLAS, 43 tests) y 2 baterías nuevas en run_all (total 55); sonda de capacidades MCP solo-lectura INT-093 (15 tests con dobles; veredictos NOT_DEMONSTRATED sin la máquina del dueño); registro local de producciones y nichos (ID estable, un cuaderno por nicho, nombres «FRUTINOVELAS · S003 · Título», GET /api/registro) y gate FLOW_REGISTRO_SYNC apagado por defecto (28 tests con dobles, nunca Flow real).
- 2026-11-07 · LLM Google Deepmind · R1-R4 del registro endurecidos: sin estado falso (R1), production_id validado (R2), escritura atómica + lock por nicho + JSON corrupto (R3), conexión local en la creación de proyectos (R4).
- 2026-11-07 · LLM Z.ai/GLM · R5-R7: adaptador real crear_proyecto (flow_mcp_client.new_project) tras gate FLOW_REGISTRO_SYNC con veredicto guardado de la sonda INT-093 — sin informe → NOT_DEMONSTRATED, sin nombre a Flow, idempotente, fallo del MCP → ERROR + limitación (10 tests con doble); regla de la raya en el validador (acotación narrativa ≠ diálogo; solo tras verbo de habla/«:»/inicio de línea, 5 tests nuevos + 3 reformulados, 48 en verde); ROADMAP a SIGUIENTE.
- 2026-11-07 · LLM Z.ai/GLM · cierre Q1-Q6: punto de paso común del registro en database.create_project (13 vías reales, sin duplicados), sonda q6/q7 solo lectura, disparo de sync en las DOS puertas de fase Flow (FLOW_REGISTRO_SYNC, asyncio.to_thread, veredicto literal grepeable), cuaderno del nicho (POST/GET /api/registro/nicho + propaga_notebook deja de callar) y aviso HABLA_SIN_COMILLAS_POSIBLE (dialogue = fuente de verdad en la spec). Lo que exige Flow real sigue NOT_DEMONSTRATED (sonda pendiente del dueño).
- 2026-11-07 · LLM Z.ai/GLM · panel MCP honesto U1-U7: /api/mcp/resumen solo lectura (todo_conectado SOLO con las 4 piezas ok), tarjeta única con semáforo real + Conectar todo, Avanzado plegado con aviso humano de FastMCP, cuaderno por nicho (Q4) con vacíos útiles y Run Full Pipeline gated con motivo exacto; paquete real notebooklm-mcp-server v0.1.15 (2.14.5 era FastMCP) con trinquete de catálogo en INT-093. Baterías 55→58 (resumen 11, panel 20, contrato 7); lo visual en navegador real NOT_DEMONSTRATED (pendiente del dueño); conexión mcp_manager intacta.
- 2026-11-10 · LLM Z.ai/GLM · higiene X1-X4: ESTADO_REAL a las 59 baterías reales (CI verde); connect_all_google ya NO mata Chrome sano — chequea salud primero y solo purga+sanea si está caído o zombi, relanzando con force_window=True (dobles en test_x2); app-mcp.js a LF puro + .gitattributes (eol=lf, binarios) + guardia binaria anti \r\r\n; el panel «Conectar todo» muestra el detalle del error en texto visible, no solo en el toast.
- 2026-11-10 · Cierre X5: verificación completa (pytest + run_all) DESPUÉS del último commit; con Chrome real en la PC del dueño TODO queda NOT_DEMONSTRATED hasta su validación (X2/X4 en SIGUIENTE).
- 2026-11-10 · LLM Z.ai/GLM · Y1-Y3: catálogo COMPLETO de tools por HTTP — GET /api/mcp/catalogo/{service} lee la conexión YA activa del backend (solo lectura: nunca conecta, nunca lanza procesos, nunca ejecuta tools; 409 «conecta primero»); la sonda INT-093 usa ese endpoint por defecto (--modo-local solo con aviso de duplicados), informe con inputSchema íntegro, q5 corregida (notebook_add_text con title opcional = SOPORTADO) y q8-q10 sobre Flow; .gitattributes con eol=crlf para .bat/.cmd/.vbs (contenido de lanzadores intacto).
- 2026-11-10 · Cierre Y4: pytest + run_all completos DESPUÉS del último commit; los veredictos reales de Flow/NotebookLM siguen NOT_DEMONSTRATED hasta que el dueño corra la sonda con el backend en marcha.
- 2026-11-10 · Google Deepmind · Z1-Z4: subprocess a nivel de módulo en main.py (Z1), test hermético lipsync-musetalk con dobles y fallo ffmpeg (Z2), eliminación de _probe_nvenc duplicada con ENABLE_NVENC sin definir en video.py (Z3), paso ruff F821,E9,F63,F7,F82 en CI con corrección de Any en qa_forensics y redefiniciones de sys en mcp_manager (Z4).
- 2026-11-10 · Cierre Z5: ROADMAP y LEEME_PRIMERO actualizados; corridas completas de pytest y run_all.py ejecutadas tras el último commit.
- 2026-11-11 · Google Deepmind (EGM) · Optimización Pipeline Render: soporte NVENC p1 para renders intermedios en video_encode.py (7b6ae47) y unificación de pasadas de posproducción en pipeline/video.py (burn_subtitles con subtítulos ASS + badge E-commerce + avatar PiP encadenados en un único filter_complex de FFmpeg, 3347179) — suites herméticas limpias con ruff en verde.
