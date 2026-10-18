# CONTEXTO YOUTUBE

## Memoria operativa del proyecto YOUTUBE-AUTOMATION

**Estado:** VACÍO / READY TO FILL  
**Tipo:** memoria documental estructurada del proyecto  
**Propósito:** conservar procesos, hallazgos, decisiones, pruebas, problemas, soluciones y conocimiento operativo específico de YOUTUBE-AUTOMATION.

---

## 1. Regla principal

Este espacio nace **completamente limpio**.

No debe llenarse automáticamente con información existente del repositorio solo por crear esta estructura.

La información entra cuando un proceso, auditoría, prueba, investigación, decisión o hallazgo sea considerado útil para la continuidad del proyecto.

**Fuente de verdad:** el código y artefactos técnicos siguen siendo la fuente de verdad de implementación. `CONTEXTO YOUTUBE` funciona como memoria de continuidad, razonamiento y trazabilidad.

---

## 2. Qué debe conservar

- decisiones arquitectónicas;
- decisiones operativas;
- procesos que funcionaron;
- procesos que fallaron;
- hallazgos de auditorías;
- pruebas y sus resultados;
- errores y causas raíz;
- soluciones verificadas;
- experimentos y conclusiones;
- contratos entre componentes;
- integraciones externas;
- cambios importantes de arquitectura;
- conocimiento sobre producción audiovisual;
- conocimiento sobre publicación y distribución;
- conocimiento sobre cuentas/canales/destinos;
- evolución de HANDS;
- relación con EEC;
- relación con AGENTE-GENERAL;
- relación con herramientas externas;
- pendientes y riesgos conocidos;
- evidencia necesaria para declarar algo terminado.

---

## 3. Qué NO debe convertirse en esto

- No es una copia del código.
- No es un backup del repositorio.
- No es un volcado de todos los chats.
- No reemplaza documentación técnica específica.
- No reemplaza issues ni PRs.
- No debe registrar secretos, tokens, cookies, credenciales ni datos sensibles.
- No debe declarar como verificado algo que solo fue propuesto.

---

## 4. Estados documentales

Usar estados explícitos:

- `PROPOSED` — propuesta.
- `PLANNED` — plan aprobado para ejecución.
- `IN_PROGRESS` — trabajo en curso.
- `EXPERIMENTAL` — probado de forma limitada.
- `VERIFIED` — comprobado con evidencia.
- `FAILED` — falló y queda documentado por valor histórico/operativo.
- `BLOCKED` — bloqueado por una dependencia.
- `SUPERSEDED` — reemplazado por una decisión posterior.
- `ARCHIVED` — conservado solo como referencia histórica.

Nunca convertir automáticamente `PROPOSED` en `VERIFIED`.

---

## 5. Principio de memoria útil

Cada entrada debería responder, cuando corresponda:

1. ¿Qué intentábamos conseguir?
2. ¿Qué hicimos?
3. ¿Qué observamos?
4. ¿Qué aprendimos?
5. ¿Qué decisión salió de ello?
6. ¿Qué evidencia existe?
7. ¿Qué queda pendiente?

La memoria debe permitir que otro constructor, agente o sesión pueda retomar el proyecto sin repetir investigaciones ya realizadas.

---

## 6. Estructura

```text
CONTEXTO YOUTUBE/
├── README.md
├── INDEX.md
├── 00_MASTER/
│   ├── PROJECT_STATE.md
│   ├── ARCHITECTURE.md
│   └── GLOSSARY.md
├── 01_DECISIONS/
│   └── DECISION_LOG.md
├── 02_PROCESSES/
│   └── PROCESS_INDEX.md
├── 03_FINDINGS/
│   └── FINDINGS_INDEX.md
├── 04_AUDITS/
│   └── AUDIT_INDEX.md
├── 05_TESTS/
│   └── TEST_INDEX.md
├── 06_INTEGRATIONS/
│   └── INTEGRATION_INDEX.md
├── 07_FAILURES/
│   └── FAILURE_INDEX.md
├── 08_SESSIONS/
│   └── SESSION_INDEX.md
└── 09_KNOWLEDGE/
    └── KNOWLEDGE_INDEX.md
```

Los índices nacen vacíos y se completan conforme aparezca información real.

---

## 7. Relación con otros repositorios

Este contexto pertenece específicamente a `ALBRA8/YOUTUBE-AUTOMATION`.

Cuando una decisión sea transversal a todo ALBRA, debe evaluarse si corresponde también a `ALBRA8/CONTEXT`.

Cuando un hallazgo sea exclusivamente técnico de YOUTUBE-AUTOMATION, su memoria primaria debe quedar aquí.

---

## 8. Regla de actualización

Después de una auditoría, prueba importante, integración o sesión de trabajo significativa:

> Registrar en CONTEXTO YOUTUBE lo aprendido que sea necesario para no perder continuidad.

No registrar ruido.

---

## 9. Regla de trazabilidad

Toda entrada importante debe poder apuntar a su evidencia real cuando exista:

- commit;
- archivo;
- PR;
- issue;
- test;
- log;
- reporte;
- artefacto;
- resultado de ejecución.

---

## 10. Estado inicial

**CONTEXTO YOUTUBE está deliberadamente vacío de conocimiento específico.**

La estructura existe para comenzar a construir la memoria del proyecto desde este punto.
