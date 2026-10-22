# CONTEXTO YOUTUBE — INDEX

**Estado:** INTEGRATED IN MAIN / IN_PROGRESS
**Última actualización:** 2026-10-22

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

## Referencias de conocimiento incorporadas

- `09_KNOWLEDGE/K-007_VIDEO_BASE_REFERENCIA_2026-10-17.md` conserva el video que sirvió como origen conceptual del pipeline audiovisual. Se incorpora como **conocimiento de referencia**, no como evidencia técnica ni como especificación de implementación.
- `09_KNOWLEDGE/K-008_CATALOGO_HERRAMIENTAS_IA_REFERENCIA_2026-07.md` conserva un catálogo externo de herramientas IA, versión 5.0 de julio de 2026. Es un mapa de candidatos por categoría, **no una evaluación técnica ni una orden de integración**. Las afirmaciones comerciales y comparativas requieren verificación actualizada.

## Decisión operativa vigente — Constructor / Antigravity

> **REGLA PRINCIPAL: EL CONSTRUCTOR ESTÁ EN LA NUBE Y MANEJA EL CÓDIGO REAL DEL REPOSITORIO GITHUB. ANTIGRAVITY ESTÁ EN EL COMPUTADOR DEL USUARIO Y ES EL AGENTE PARA PRUEBAS, VALIDACIONES, DESPLIEGUES Y COMPROBACIONES LOCALES.**

Esta separación es una regla estable del flujo de trabajo, no una excepción temporal. El Constructor recibe las tareas de auditoría profunda del repositorio, cambios de código, conexiones/integraciones y documentación/versionado. Antigravity recibe las tareas que requieren el entorno local del computador. ChatGPT coordina la arquitectura, asigna cada trabajo al agente adecuado y valida los resultados. Ver D-007 en `01_DECISIONS/DECISION_LOG.md`.

## Hitos vigentes

- Integración unificada en `main`: F5.1 live gate, GoogleFlowMCP bridge y robustez de transporte (buffer outbox, fallbacks de selectores, purga de cerrojos y normalización de prompts).
- La incidencia HARD E2E del render final FFmpeg permanece separada y localizada en INT-012; `backend/pipeline/video.py` y su timeout reportado de 900 s están protegidos para esta migración.
- Migración AGENTE-GENERAL → harness: análisis P0 documentado; siguiente fase propuesta P1 = conexión fría, configuración y smoke test read-only, cero cambios de código. Requiere verificar las revisiones exactas de ambos repos, el nombre real de la variable de API key y los permisos antes de configurar. No conectar ni activar producción por inferencia.
