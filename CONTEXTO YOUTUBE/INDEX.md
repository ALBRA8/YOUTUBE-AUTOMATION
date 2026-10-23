# CONTEXTO YOUTUBE — INDEX

**Estado:** INTEGRATED IN MAIN / IN_PROGRESS
**Última actualización:** 2026-10-23 (P1 PASS · P1.5 publicado · P2 PASS · P3-A PASS · P3-B PASS y PUBLICADO: PR #68 → `69c79da` AG-G · `1c384b1` YT-AUT)

| Área | Archivo | Estado | Propósito |
|---|---|---|---|
| Master | `00_MASTER/PROJECT_STATE.md` | IN_PROGRESS | estado actual, bloqueo y plan inmediato |
| Master | `00_MASTER/ARCHITECTURE.md` | VERIFIED / IN_PROGRESS | capas, frontera y límites de evidencia; incorpora la referencia conceptual del video base |
| Master | `00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md` | DESIGN v1.0 / NOT IMPLEMENTED | Production Framework común, registry y Blueprints Microdrama, Short, Short-Form y UGC; distingue diseño documental de implementación verificada |
| Master | `00_MASTER/GLOSSARY.md` | VERIFIED | términos del proyecto |
| Master | `00_MASTER/MIGRATION_ANALYSIS.md` | ANALYSIS / STOP | análisis de migración AGENTE-GENERAL → harness; fases P0–P5, límites protegidos y riesgos; no implementado |
| Decisions | `01_DECISIONS/DECISION_LOG.md` | POPULATED | decisiones arquitectónicas, Start Frame y frontera operativa Constructor/Antigravity |
| Processes | `02_PROCESSES/PROCESS_INDEX.md` | POPULATED | procedimientos de auditoría y prueba real |
| Findings | `03_FINDINGS/FINDINGS_INDEX.md` | POPULATED | hallazgos y evidencia |
| Audits | `04_AUDITS/AUDIT_INDEX.md` | POPULATED | auditorías realizadas y pendientes |
| Tests | `05_TESTS/TEST_INDEX.md` | POPULATED | inventario de tests reportados y test real pendiente |
| Integrations | `06_INTEGRATIONS/INTEGRATION_INDEX.md` | POPULATED | AGENTE-GENERAL, Bridge, Flow, Meta, HANDS, evaluación externa Agnes (INT-017) |
| Failures | `07_FAILURES/FAILURE_INDEX.md` | POPULATED | incidente histórico, gaps y riesgos |
| Sessions | `08_SESSIONS/SESSION_INDEX.md` | POPULATED | resumen de continuidad de la sesión |
| Knowledge | `09_KNOWLEDGE/KNOWLEDGE_INDEX.md` | POPULATED | reglas técnicas, jerarquía de evidencia, referencias conceptuales y catálogo de herramientas IA |

## Migración AGENTE-GENERAL ↔ harness

- `00_MASTER/MIGRATION_ANALYSIS.md` registra la síntesis A–L del análisis de migración AGENTE-GENERAL → harness compartido el 2026-10-22. Estado: **P0 COMPLETADO / STOP RESPETADO / MIGRACIÓN NO IMPLEMENTADA**. La síntesis está versionada en `main`; no equivale al informe local original de 420 líneas ni a una reejecución independiente de sus pruebas. El commit local `a3485a0` no se pudo publicar por el HTTP 401 del PAT revocado. No almacenar ni solicitar credenciales en el contexto.
- **P1 — conexión fría: PASS (2026-10-22, VERIFIED).** Conexión real demostrada: AGENTE-GENERAL (cliente/tool/skill reales de `feature/youtube-harness` `b5b7220`) → HTTP Bearer → `/api/harness/v1` @ `main` `3e15beb` → operaciones LOW read-only → HarnessResult válido. 272 checks verdes (baterías del motor + host + smoke). Fail-closed verificado en 6 vectores. Cero modificaciones de código. Variables reales confirmadas: `YOUTUBE_HARNESS_URL` / `YOUTUBE_HARNESS_API_KEY` (host) → `MASTER_API_KEY` (arnés).
- **P1.5 — integración: merge `--no-ff` de `b5b7220` sobre `origin/main` `5f277b3` → commit `9bb3870`, cero conflictos, no-regresión probada (18 fallos pre-existentes idénticos en main puro vs fusionado; +15 tests nuevos en verde). PUBLICADO 2026-10-22: rama `feature/youtube-harness` + rama `integration/youtube-harness` publicadas, PR #67 con CI 5/5, merge `3afa77f` en main vía ruleset *Protección Main - Clean Room* (vía PR, sin bypass).
- **P2 — ciclo operativo sin launch: PASS (2026-10-22, VERIFIED).** 45 checks, 0 fallos con motor real y HTTP TCP real: descubrimiento (manifiesto 19 operaciones), secuencia read controlada (7 operaciones LOW por las tres capas del host, incluida `validate_production` con el ejemplo canónico del motor), 5 límites negativos BLOCKED, idempotencia del libro verificada (replay `metadata.replayed=True`), `projects=0/jobs=0/flow_jobs=0` antes=después. Sin vídeo, sin render, sin launch, sin publicación. Detalle y matriz P3 en `06_INTEGRATIONS/INT-014_AGENTE_GENERAL_HARNESS_P1_P2.md`.
- **P3-A — matriz definitiva + gap analysis + gobernanza: PASS (2026-10-22, VERIFIED).** Matriz con evidencia file:line en `06_INTEGRATIONS/INT-015_P3_CAPABILITY_MATRIX.md`; riesgos 11 LOW/4 MEDIUM/3 HIGH/1 CRITICAL; 9 skills host cubrían 11/19 operaciones; `validate_production` y `system_status` justificadas como skills nuevas; `ANALYZE_FAILURE` DIVERGENT (scope por proyecto); RETRY existente en motor/FUTURE como operación; destructivas sin skill host. Sin cambios funcionales en P3-A.
- **P3-B — correcciones quirúrgicas: PASS (2026-10-23, VERIFIED).** Autorizada por misión P3-B. Ejecutado: **PB-01** (G-01 corregido: publish exitoso ahora reporta envelope `PUBLISHED`, estado canónico ya existente; fallo auténtico sigue `FAILED`+`errors[]`; 10 checks de regresión sin producción), **PB-02** (skills host read-only `skill.youtube.validate` y `skill.youtube.system_status`, LOW/`youtube.read`, con políticas y grants; especialización 22 passed), **PB-04** (`HARNESS_ALLOWED_PERMISSIONS` documentada en `.env.example`). Definido y NO implementado: PB-03 (G-02, toca contrato compartido v1 → pendiente de autorización explícita). Hallazgo nuevo G-13 (metadata de skills no persistida por el seed; verificación funcional añadida; seed intacto). Tests: YT-AUT 620/620 (17/17 suites), AG-G sin fallos nuevos (diff de FAILED vacío vs `main` de control). Superficies protegidas intactas. Detalle técnico: `06_INTEGRATIONS/INT-017_P3B_EJECUCION_QUIRURGICA.md` (cierre resumido: `INT-016_P3B_QUIRURGICAS_CIERRE.md`).
- **Publicación P3-B — COMPLETADA (2026-10-23):** AG-G rama `p3b-skills-host` (`8859b4b`) → **PR #68** CI 5/5 SUCCESS → merge `69c79da` en `main` (ruleset, sin bypass). YT-AUT rama `p3b-g01-publish-envelope` rebaseada sobre `4394f3b` → `5e31cb3` (fix G-01 + tests) + `1c384b1` (docs INT-017) → **push directo a `main`** (`4394f3b..1c384b1`). SHAs locales históricos (`a552b3d`/`56be4b9`) preservados en rama de respaldo `p3b-backup-local-report`. Tests re-verificados en la sesión de publicación (YT-AUT 620/620; AG-G especialización 22/22, unit sin fallos nuevos). Credencial usada solo transitoriamente en memoria; PAT expuesto sigue pendiente de rotación por el propietario.

## Referencias de conocimiento incorporadas

- `09_KNOWLEDGE/K-007_VIDEO_BASE_REFERENCIA_2026-10-17.md` conserva el video que sirvió como origen conceptual del pipeline audiovisual. Se incorpora como **conocimiento de referencia**, no como evidencia técnica ni como especificación de implementación.
- `09_KNOWLEDGE/K-008_CATALOGO_HERRAMIENTAS_IA_REFERENCIA_2026-07.md` conserva un catálogo externo de herramientas IA, versión 5.0 de julio de 2026. Es un mapa de candidatos por categoría, **no una evaluación técnica ni una orden de integración**. Las afirmaciones comerciales y comparativas requieren verificación actualizada.

## Decisión operativa vigente — Constructor / Antigravity

> **REGLA PRINCIPAL: EL CONSTRUCTOR ESTÁ EN LA NUBE Y MANEJA EL CÓDIGO REAL DEL REPOSITORIO GITHUB. ANTIGRAVITY ESTÁ EN EL COMPUTADOR DEL USUARIO Y ES EL AGENTE PARA PRUEBAS, VALIDACIONES, DESPLIEGUES Y COMPROBACIONES LOCALES.**

Esta separación es una regla estable del flujo de trabajo, no una excepción temporal. El Constructor recibe las tareas de auditoría profunda del repositorio, cambios de código, conexiones/integraciones y documentación/versionado. Antigravity recibe las tareas que requieren el entorno local del computador. ChatGPT coordina la arquitectura, asigna cada trabajo al agente adecuado y valida los resultados. Ver D-007 en `01_DECISIONS/DECISION_LOG.md`.

## Hitos vigentes

- Integración unificada en `main`: F5.1 live gate, GoogleFlowMCP bridge y robustez de transporte (buffer outbox, fallbacks de selectores, purga de cerrojos y normalización de prompts).
- La incidencia HARD E2E del render final FFmpeg (INT-012) quedó **corregida y PUBLICADA** en el cierre técnico 2026-10-23 (`06_INTEGRATIONS/INT-020_RENDER_BURN_TIMEOUT_FIX.md`): `burn_subtitles` usa `-preset veryfast` y el timeout se degrada honestamente vía `subs_status.json` (QA warn); batería nueva 16/16 y suite canónica en verde; push `30535f2..f176103` → `origin/main` verificado. El re-run real en 4K y la idempotencia Run 2 permanecen como validación de Antigravity (Chrome + sesión del usuario).
- Mejora de producto INT-021 (2026-10-23): nuevo estilo de subtítulos `shorts` y **nuevo default** — Montserrat ExtraBold embarcada (SIL OFL 1.1) + paleta de contraste dinámico WCAG >= 4.5:1 por bandas de brillo de escena + zona segura Shorts (`06_INTEGRATIONS/INT-021_TIPOGRAFIA_IMPACTO_CONTRASTE_DINAMICO.md`). Matching libass verificado por A/B de MD5 (familia ID1; pedir `Montserrat` con fontsdir degrada en silencio). En working tree a la espera del commit del integrador; validación visual real (Antigravity) pendiente.
- Migración AGENTE-GENERAL → harness: P0 documentado (INT-013); **P1 PASS**, **P1.5 publicado** (PR #67 → `3afa77f`), **P2 PASS** (INT-014), **P3-A PASS** (INT-015) y **P3-B PASS y PUBLICADO** (cierre INT-016 + ejecución técnica INT-017: G-01 corregido + skills `validate`/`system_status` + docs env; PB-03/G-02 pendiente de autorización explícita). Publicación: AG-G PR #68 → merge `69c79da`; YT-AUT push directo `4394f3b..1c384b1`. No activar producción ni implementar PB-03/PB-05 sin nueva autorización.


## Evaluación externa — Agnes Video Generator (2026-10-22 / 2026-10-23)
- Revisión documental y selectiva registrada en `06_INTEGRATIONS/INT-018_AGNES_VIDEO_GENERATOR_EVALUATION.md` (renumerado desde INT-017; número ocupado por el informe P3-B).
- **Comparación dirigida basada en código real (2026-10-23):** `06_INTEGRATIONS/INT-019_AGNES_COMPARACION_DIRIGIDA.md` — 6 áreas con anclas archivo:línea de ambos repos; veredicto: capacidades clave YA EXISTEN aquí; 3 ideas adaptables (R1/R2/R3) y 7 descartes con motivo; decisión D-008 en `01_DECISIONS/DECISION_LOG.md`.
- No integrar directamente, no sustituir componentes ALBRA ni crear otro agente audiovisual. Licencia MIT verificada en el clon; cero código copiado; el repo externo no se ejecutó.
- **INT-022** · MCP Connection Manager: panel ↔ GoogleFlowMCP/notebooklm-mcp (badges, toggles, notebookId dinámico, Test Pipeline, preflight AUTH_REQUIRED). [Ver integración](06_INTEGRATIONS/INT-022_MCP_CONNECTION_MANAGER.md)


## Producción creativa multi-línea — 2026-10-23

- Diseño documentado en `00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md`.
- Framework común + Blueprints especializados: Microdrama, Short, Short-Form y UGC.
- No confundir este diseño conceptual con schemas, selector o runtime ya implementados.
