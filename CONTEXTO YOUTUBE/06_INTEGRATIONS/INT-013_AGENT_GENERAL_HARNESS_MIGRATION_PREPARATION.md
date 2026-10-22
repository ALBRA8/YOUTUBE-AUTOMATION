# INT-013 — PREPARACIÓN DE ARNÉS AGENTE-GENERAL PARA YOUTUBE-AUTOMATION

**Fecha:** 2026-10-22  
**Estado:** PREPARACIÓN / ANÁLISIS ARQUITECTÓNICO — SIN MIGRACIÓN EJECUTADA  
**Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`  
**Branch:** `main`  
**HEAD verificado antes de esta preparación:** `f102b36e8535af0a7bacff00f38af417aa54c04c`

---

## 1. Objetivo

Preparar la futura integración de **AGENTE-GENERAL** como infraestructura central compartida de ALBRA, convirtiendo YOUTUBE-AUTOMATION en un **chaleco/arnés especializado**, sin reemplazar su fábrica audiovisual ni duplicar su arquitectura.

Esta fase no ejecuta la migración. Define el trabajo que debe realizar el constructor: auditar el repositorio real, mapear la frontera agente/arnés, diseñar el `AgentAdapter`, identificar skills y knowledge, analizar VÓRTICE y producir un plan de migración reversible.

---

## 2. Decisión arquitectónica

La integración debe respetar esta frontera:

```text
AGENTE-GENERAL
    ↓
AgentAdapter
    ↓
YOUTUBE-AUTOMATION HARNESS
    ↓
skills / orchestrator / pipeline / tools / QA / publishing
```

Principios:

- **El agente interpreta.**
- **El arnés sabe hacer.**
- **Las skills ejecutan.**
- **El conocimiento audiovisual permanece en YOUTUBE-AUTOMATION.**
- **AGENTE-GENERAL coordina sin absorber el dominio audiovisual.**

No se debe crear un segundo framework/harness paralelo.

---

## 3. Por qué NO se usa el prompt genérico sin adaptación

El prompt genérico de migración recibido para otros proyectos contempla estructuras como Next.js/TypeScript, `src/lib`, `layout.tsx`, `/api/harness/route.ts` y ejemplos específicos como `bootstrapKrea`.

Esas convenciones no deben imponerse mecánicamente sobre YOUTUBE-AUTOMATION.

YOUTUBE-AUTOMATION ya dispone de infraestructura propia de producción en Python, pipeline, orchestrator, Production JSON, jobs, QA, Flow y GoogleFlowMCP.

La regla es adaptar AGENTE-GENERAL al proyecto, no reconstruir el proyecto alrededor de una plantilla genérica.

---

## 4. Fase actual — SOLO preparación

El constructor debe:

1. Auditar el repositorio real.
2. Clasificar componentes como domain knowledge, skills, tools/bridges, harness infrastructure y agent logic.
3. Identificar VÓRTICE y sus responsabilidades.
4. Diseñar el contrato AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION.
5. Diseñar el `AgentAdapter` apropiado para la arquitectura real, previsiblemente Python/bridge compatible, sin asumir TypeScript.
6. Mapear skills reales existentes.
7. Mapear knowledge que debe permanecer dentro del arnés.
8. Ejecutar análisis LIPO: KEEP / MOVE / ADAPT / DELETE LATER.
9. Identificar archivos candidatos y archivos protegidos.
10. Documentar orden de implementación y riesgos.
11. Detenerse después del análisis/documentación.

No debe ejecutarse todavía la migración completa.

---

## 5. Componentes protegidos durante esta fase

No tocar como parte de esta preparación:

- F5/F5.1.
- `extension/injector.js`.
- GoogleFlowMCP.
- `flow_mcp_client`.
- Scene Asset Resolver.
- Start Frame lineage.
- referencias/asset lineage.
- C.0, C.1 y C.2.
- `flow_import`.
- orchestrator de producción.
- Production JSON.
- HANDS V1.0.
- FFmpeg / `burn_subtitles`.
- configuración MCP activa.
- pruebas LIVE.

---

## 6. Contexto HARD E2E vigente

La prueba `_hard_e2e_c2_01` quedó documentada en `INT-012`.

Resultado:

- 4/4 escenas reales Google Flow: PASS.
- Start Frames independientes: PASS.
- referencias independientes: PASS.
- descarga/validación de MP4: PASS.
- `flow_import`: PASS.
- ensamblado/audio: PASS.
- render final: FAIL por timeout rígido de FFmpeg.
- idempotencia Run 2: no ejecutada en esa prueba.

El primer fallo está localizado en:

```text
backend/pipeline/video.py
→ burn_subtitles
→ _run_ffmpeg(... timeout=900)
```

Esta incidencia queda separada de la migración AGENTE-GENERAL y debe resolverse en una intervención técnica posterior.

---

## 7. Resultado esperado del constructor

Debe producir un análisis que contenga como mínimo:

### A. Diagnóstico
Estado real de YOUTUBE-AUTOMATION.

### B. Mapa de integración
Dónde entra AGENTE-GENERAL y dónde termina su responsabilidad.

### C. AgentAdapter
Contrato de entrada, intención, contexto, skill, parámetros, ejecución, resultado, errores, estado, evidencia, permisos, cancelación e idempotencia.

### D. Skills
Solo capacidades reales existentes, con implementación, entrada, salida, dependencias, side effects y nivel de riesgo.

### E. Knowledge
Qué conocimiento audiovisual permanece dentro del arnés.

### F. VÓRTICE
Qué hace hoy, qué debe sobrevivir y qué podría migrarse posteriormente.

### G. LIPO
KEEP / MOVE / ADAPT / DELETE LATER.

### H. Archivos
Archivos candidatos a modificación futura.

### I. Archivos protegidos
Archivos/sistemas que no deben tocarse en la migración.

### J. Plan
Orden de implementación posterior.

### K. Riesgos
Solo riesgos reales encontrados en el código.

### L. Stop point
El constructor debe detenerse después del análisis y documentación.

---

## 8. Criterio de aceptación de esta fase

Esta fase se considera correcta si existe un mapa claro y verificable que permita posteriormente integrar AGENTE-GENERAL sin:

- duplicar el orchestrator;
- crear otro agente audiovisual;
- duplicar QA;
- absorber el conocimiento de dominio en AGENTE-GENERAL;
- romper GoogleFlowMCP/Flow;
- tocar F5/F5.1;
- destruir VÓRTICE antes de tiempo;
- introducir una arquitectura Next.js/TypeScript artificial;
- ejecutar cambios destructivos sin autorización.

La migración posterior debe ser **mínima, reversible, trazable e idempotente**.

---

## 9. Estado Git/contexto

Esta documentación se añade después de verificar que `main` estaba actualizado en GitHub en `f102b36e8535af0a7bacff00f38af417aa54c04c`.

El objetivo de este documento es dejar en CONTEXTO YOUTUBE la decisión tomada: **sí es momento de preparar la inyección de AGENTE-GENERAL, pero todavía no de ejecutar la migración destructiva/definitiva.**

La siguiente etapa técnica será:

1. Constructor: análisis/adaptación y mapa de migración.
2. Antigravity: resolver primero el fallo conocido de `burn_subtitles`/FFmpeg cuando vuelva a estar disponible.
3. Implementación autorizada del adapter/arnés.
4. Validación y pruebas.
5. Integración real del agente.
