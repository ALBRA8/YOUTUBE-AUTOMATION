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
