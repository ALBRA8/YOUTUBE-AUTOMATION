# CONTEXTO YOUTUBE — INDEX

**Estado:** CLOSED F5 / READY FOR LIVE GATE AUTHORIZATION  
**Última actualización:** 2026-10-20

| Área | Archivo | Estado | Propósito |
|---|---|---|---|
| Master | `00_MASTER/PROJECT_STATE.md` | IN_PROGRESS | estado actual, bloqueo y plan inmediato |
| Master | `00_MASTER/ARCHITECTURE.md` | VERIFIED / IN_PROGRESS | capas, frontera y límites de evidencia |
| Master | `00_MASTER/GLOSSARY.md` | VERIFIED | términos del proyecto |
| Decisions | `01_DECISIONS/DECISION_LOG.md` | POPULATED | decisiones arquitectónicas y Start Frame |
| Processes | `02_PROCESSES/PROCESS_INDEX.md` | POPULATED | procedimientos de auditoría y prueba real |
| Findings | `03_FINDINGS/FINDINGS_INDEX.md` | POPULATED | hallazgos y evidencia |
| Audits | `04_AUDITS/AUDIT_INDEX.md` | POPULATED | auditorías realizadas y pendientes |
| Tests | `05_TESTS/TEST_INDEX.md` | POPULATED | inventario de tests reportados y test real pendiente |
| Integrations | `06_INTEGRATIONS/INTEGRATION_INDEX.md` | POPULATED | AGENTE-GENERAL, Bridge, Flow, Meta, HANDS |
| Failures | `07_FAILURES/FAILURE_INDEX.md` | POPULATED | incidente histórico, gaps y riesgos |
| Sessions | `08_SESSIONS/SESSION_INDEX.md` | POPULATED | resumen de continuidad de la sesión |
| Knowledge | `09_KNOWLEDGE/KNOWLEDGE_INDEX.md` | POPULATED | reglas técnicas y jerarquía de evidencia |

## Hito vigente
Cierre integral F5 del Flow Script Processor 2.6.0. Se corrigió la precedencia estricta de `init.body` ('body' in init) y se garantizó el orden causal determinista de telemetría mediante encadenamiento `onSettled`. Batería consolidada: 244/244 PASS (F1: 64, F2: 67, eb1hJf Dual+F5: 58, Harness: 55). Puertas vigentes: NO COMMIT, NO LIVE, NO MERGE, NO CONSTRUCTOR hasta autorización explícita.
