# CONTEXTO YOUTUBE — INDEX

**Estado:** INTEGRATED IN MAIN / IN_PROGRESS
**Última actualización:** 2026-10-22 (P1 PASS · P1.5 publicado · P2 PASS · P3-A PASS · P3-B PASS según informe; publicación de código P3-B pendiente)

| Área | Archivo | Estado | Propósito |
|---|---|---|---|
| Master | `00_MASTER/PROJECT_STATE.md` | IN_PROGRESS | estado actual, bloqueo y plan inmediato |
| Master | `00_MASTER/ARCHITECTURE.md` | VERIFIED / IN_PROGRESS | capas, frontera y límites de evidencia; incorpora la referencia conceptual del video base |
| Master | `00_MASTER/GLOSSARY.md` | VERIFIED | términos del proyecto |
| Master | `00_MASTER/MIGRATION_ANALYSIS.md` | ANALYSIS / STOP | análisis de migración AGENTE-GENERAL → harness; fases P0–P5, límites protegidos y riesgos; no implementado |
| Decisions | `01_DECISIONS/DECISION_LOG.md` | POPULATED | decisiones arquitectónicas, Start Frame y frontera operativa Constructor/Antigravity |
| Processes | `02_PROCESSES/PROCESS_INDEX.md` | POPULATED | procedimientos de auditoría y prueba real |
| Findings | `03_FINDINGS/FINDINGS_INDEX.md` | POPULATED | hallazgos y evidencia |
| Audits | `04_AUDITS/AUDIT_INDEX.md` | POPULATED | auditorías realizadas y pendientes |
| Tests | `05_TESTS/TEST_INDEX.md` | POPULATED | inventario de tests reportados y test real pendiente |
| Integrations | `06_INTEGRATIONS/INTEGRATION_INDEX.md` | POPULATED | AGENTE-GENERAL, Bridge, Flow, Meta, HANDS |
| Failures | `07_FAILURES/FAILURE_INDEX.md` | POPULATED | incidente histórico, gaps y riesgos |
| Sessions | `08_SESSIONS/SESSION_INDEX.md` | POPULATED | resumen de continuidad de la sesión |
| Knowledge | `09_KNOWLEDGE/KNOWLEDGE_INDEX.md` | POPULATED | reglas técnicas, jerarquía de evidencia, referencias conceptuales y catálogo de herramientas IA |

## Migración AGENTE-GENERAL ↔ harness

- `00_MASTER/MIGRATION_ANALYSIS.md` registra la síntesis A–L del análisis de migración AGENTE-GENERAL → harness compartido el 2026-10-22. Estado: **P0 COMPLETADO / STOP RESPETADO / MIGRACIÓN NO IMPLEMENTADA**. La síntesis está versionada en `main`; no equivale al informe local original de 420 líneas ni a una reejecución independiente de sus pruebas. El commit local `a3485a0` no se pudo publicar por el HTTP 401 del PAT revocado. No almacenar ni solicitar credenciales en el contexto.
- **P1 — conexión fría: PASS (2026-10-22, VERIFIED).** Conexión real demostrada: AGENTE-GENERAL (cliente/tool/skill reales de `feature/youtube-harness` `b5b7220`) → HTTP Bearer → `/api/harness/v1` @ `main` `3e15beb` → operaciones LOW read-only → HarnessResult válido. 272 checks verdes (baterías del motor + host + smoke). Fail-closed verificado en 6 vectores. Cero modificaciones de código. Variables reales confirmadas: `YOUTUBE_HARNESS_URL` / `YOUTUBE_HARNESS_API_KEY` (host) → `MASTER_API_KEY` (arnés).
- **P1.5 — integración: merge `--no-ff` de `b5b7220` sobre `origin/main` `5f277b3` → commit `9bb3870`, cero conflictos, no-regresión probada (18 fallos pre-existentes idénticos en main puro vs fusionado; +15 tests nuevos en verde). PUBLICADO 2026-10-22: rama `feature/youtube-harness` + rama `integration/youtube-harness` publicadas, PR #67 con CI 5/5, merge `3afa77f` en main vía ruleset *Protección Main - Clean Room* (vía PR, sin bypass).
- **P2 — ciclo operativo sin launch: PASS (2026-10-22, VERIFIED).** 45 checks, 0 fallos con motor real y HTTP TCP real: descubrimiento (manifiesto 19 operaciones), secuencia read controlada (7 operaciones LOW por las tres capas del host, incluida `validate_production` con el ejemplo canónico del motor), 5 límites negativos BLOCKED, idempotencia del libro verificada (replay `metadata.replayed=True`), `projects=0/jobs=0/flow_jobs=0` antes=después. Sin vídeo, sin render, sin launch, sin publicación. Detalle y matriz P3 en `06_INTEGRATIONS/INT-014_AGENTE_GENERAL_HARNESS_P1_P2.md`.
- **P3-A — matriz definitiva + gap analysis + gobernanza: PASS (2026-10-22, VERIFIED).** Matriz con evidencia file:line en `06_INTEGRATIONS/INT-015_P3_CAPABILITY_MATRIX.md`; riesgos 11 LOW/4 MEDIUM/3 HIGH/1 CRITICAL; 9 skills host cubrían 11/19 operaciones; `validate_production` y `system_status` justificadas como skills nuevas; `ANALYZE_FAILURE` DIVERGENT (scope por proyecto); RETRY existente en motor/FUTURE como operación; destructivas sin skill host. Sin cambios funcionales en P3-A.
- **P3-B — PASS según informe de ejecución (2026-10-22).** G-01 corregido: `op_publish` incorpora `external_status` y el envelope reutiliza el estado canónico `PUBLISHED`; fallo auténtico `FAILED`/`PROVIDER_FAILURE`/`recovery` preservado. Añadidas `skill.youtube.validate` y `skill.youtube.system_status` sin endpoints nuevos; `HARNESS_ALLOWED_PERMISSIONS` documentada (PB-04). PB-03/G-02 no implementado porque afecta al contrato v1 y exige autorización explícita; PB-05 fuera de alcance. Validación reportada: YT-AUT 620/620 (17/17 suites), AG-G especialización 22/22; 18 fallos unitarios del host idénticos al baseline. G-13 documentado. Ver `06_INTEGRATIONS/INT-016_P3B_QUIRURGICAS_CIERRE.md`.
- **Publicación P3-B pendiente de verificación:** commits locales reportados `a552b3d` + `56be4b9` en `p3b-g01-publish-envelope` y `8859b4b` en `p3b-skills-host`; informe indicó `BLOCKED BY AUTH`. No afirmar que el código está en `main` hasta verificar/publish los refs remotos.

## Referencias de conocimiento incorporadas

- `09_KNOWLEDGE/K-007_VIDEO_BASE_REFERENCIA_2026-10-17.md` conserva el video que sirvió como origen conceptual del pipeline audiovisual. Se incorpora como **conocimiento de referencia**, no como evidencia técnica ni como especificación de implementación.
- `09_KNOWLEDGE/K-008_CATALOGO_HERRAMIENTAS_IA_REFERENCIA_2026-07.md` conserva un catálogo externo de herramientas IA, versión 5.0 de julio de 2026. Es un mapa de candidatos por categoría, **no una evaluación técnica ni una orden de integración**. Las afirmaciones comerciales y comparativas requieren verificación actualizada.

## Decisión operativa vigente — Constructor / Antigravity

> **REGLA PRINCIPAL: EL CONSTRUCTOR ESTÁ EN LA NUBE Y MANEJA EL CÓDIGO REAL DEL REPOSITORIO GITHUB. ANTIGRAVITY ESTÁ EN EL COMPUTADOR DEL USUARIO Y ES EL AGENTE PARA PRUEBAS, VALIDACIONES, DESPLIEGUES Y COMPROBACIONES LOCALES.**

Esta separación es una regla estable del flujo de trabajo, no una excepción temporal. El Constructor recibe las tareas de auditoría profunda del repositorio, cambios de código, conexiones/integraciones y documentación/versionado. Antigravity recibe las tareas que requieren el entorno local del computador. ChatGPT coordina la arquitectura, asigna cada trabajo al agente adecuado y valida los resultados. Ver D-007 en `01_DECISIONS/DECISION_LOG.md`.

## Hitos vigentes

- Integración unificada en `main`: F5.1 live gate, GoogleFlowMCP bridge y robustez de transporte (buffer outbox, fallbacks de selectores, purga de cerrojos y normalización de prompts).
- La incidencia HARD E2E del render final FFmpeg permanece separada y localizada en INT-012; `backend/pipeline/video.py` y su timeout reportado de 900 s están protegidos para esta migración.
- Migración AGENTE-GENERAL → harness: P0 documentado (INT-013); **P1 PASS**, **P1.5 publicado** (PR #67 → `3afa77f`), **P2 PASS** (INT-014), **P3-A PASS** (INT-015) y **P3-B PASS según informe** (INT-016). La publicación de los commits de código P3-B sigue pendiente de verificación por bloqueo de credenciales reportado. PB-03/G-02 requiere autorización explícita; no iniciar P4 ni producción automáticamente.
