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
- 2026-11-06 · constructor LLM (Z.ai/GLM) · orden del repo y memoria: LEEME_PRIMERO.md + ROADMAP.md creados, lanzadores movidos a launchers/ (rutas re-ancladas, test_launchers_relocation 7/7), estado unificado (ESTADO_REAL 53 baterías + tabla CONTRACT reparada, PROJECT_STATE un solo Estado + Historial, D-010 HANDS en reserva + D-011 memoria), baterías HANDS añadidas al CI · pytest 478 pass / 1 fallo conocido (test_int088, magic number — Fase 1); run_all 2548 OK / 2 fallos en 3 baterías preexistentes (int025 crash, security_hardening, int028 — Fase 1) · pendiente: Fase 1 completa y confirmación del dueño de que el PAT mencionado en PROJECT_STATE.md fue revocado (NOT_DEMONSTRATED).
