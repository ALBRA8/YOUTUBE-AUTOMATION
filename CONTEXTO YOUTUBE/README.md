# CONTEXTO YOUTUBE

## Memoria documental de continuidad de YOUTUBE-AUTOMATION

**Estado:** POPULATED BASELINE — IN_PROGRESS  
**Última actualización:** 2026-10-18  
**Propósito:** conservar decisiones, auditorías, hallazgos, pruebas, integraciones, fallos, sesiones y conocimiento necesario para continuar sin repetir investigaciones.

## Naturaleza de esta memoria
Esta carpeta está implementada como Markdown versionado e índices. No asumir que es por sí misma una base de datos vectorial ni que tiene embeddings o búsqueda semántica ejecutable. El repositorio declara aparte `services/memorydv.py` (MemoryDV), memoria operativa con almacenamiento JSONL local gitignored y pruebas. No confundir ambos sistemas.

## Regla de fuente de verdad
- Código + tests + evidencia de ejecución son fuente de verdad técnica.
- `ESTADO_REAL.md` es inventario de lo que existe y de los alcances probados.
- CONTEXTO YOUTUBE es memoria de continuidad y razonamiento con trazabilidad.
- No elevar PROPOSED/PLANNED/NOT_DEMONSTRATED a VERIFIED sin evidencia.
- Los conteos de tests se copian como “reportados” hasta ejecutarlos nuevamente.

## Qué se registró en esta inicialización
- Frontera arquitectónica AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION.
- Estado de backend Flow Bridge, extensión, Execution Contract y límites de E2E real.
- Auditoría Start Frame/End Frame y hallazgo de que la captura real actual sigue pendiente.
- Diferencia entre Start Frame de Meta AI y camino de Google Flow.
- Diferencia entre mediaId de resultado y mediaId de input.
- Decisión de no implementar hasta capturar request real.
- Plan de prueba forense y precauciones de sanitización.
- Inventario de tests reportados en `ESTADO_REAL.md`, claramente etiquetados como no reejecutados en esta actualización.

## Estructura
```text
CONTEXTO YOUTUBE/
├── README.md
├── INDEX.md
├── 00_MASTER/ (PROJECT_STATE, ARCHITECTURE, GLOSSARY)
├── 01_DECISIONS/DECISION_LOG.md
├── 02_PROCESSES/PROCESS_INDEX.md
├── 03_FINDINGS/FINDINGS_INDEX.md
├── 04_AUDITS/AUDIT_INDEX.md
├── 05_TESTS/TEST_INDEX.md
├── 06_INTEGRATIONS/INTEGRATION_INDEX.md
├── 07_FAILURES/FAILURE_INDEX.md
├── 08_SESSIONS/SESSION_INDEX.md
└── 09_KNOWLEDGE/KNOWLEDGE_INDEX.md
```

## Cómo mantenerla
Después de cada auditoría, prueba, integración o cambio importante:
1. Actualizar PROJECT_STATE si cambia fase/bloqueadores/próximo hito.
2. Registrar decisiones en DECISION_LOG.
3. Añadir hallazgos en FINDINGS_INDEX y auditorías en AUDIT_INDEX.
4. Registrar pruebas con su alcance real en TEST_INDEX.
5. Actualizar integración/fallos/sesiones/conocimiento según corresponda.
6. Actualizar INDEX para que ningún documento útil quede invisible.
7. Citar commits, archivos y resultados cuando existan.
8. No registrar secretos, cookies, tokens ni credenciales.

## Estado actual resumido
Auditoría estática Start Frame: completada para el código inspeccionado. E2E real Google Flow: NOT_DEMONSTRATED. Siguiente paso: generación única desde ALBRA con imagen conocida, captura de red sanitizada, correlación request/asset/resultado y diagnóstico antes de modificar código.
