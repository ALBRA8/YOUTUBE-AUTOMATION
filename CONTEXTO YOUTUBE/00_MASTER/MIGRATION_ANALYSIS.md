# MIGRATION ANALYSIS — AGENTE-GENERAL → YOUTUBE-AUTOMATION HARNESS

**Fecha de registro:** 2026-10-22  
**Estado:** ANÁLISIS DOCUMENTADO / STOP RESPETADO / MIGRACIÓN NO IMPLEMENTADA  
**Fuente:** resumen de análisis A–L compartido por el usuario. El informe local de 420 líneas y el commit local `a3485a0` no estaban presentes en `main` al momento de registrar esta síntesis; este documento no afirma ser una copia íntegra de ese informe.

## 1. Sincronización y procedencia

- Se reporta `main` local en `f102b36`.
- Se reporta que la rama remota `harness-v1` ya no existe; `8326f43` (F2, extensión 2.6.0) es ancestro de `main`, por lo que el historial relevante no se habría perdido en el merge.
- Se reporta `AGENTE-GENERAL`, rama `feature/youtube-harness`, en `b5b7220` y presente en disco.
- El análisis completo se reportó como `CONTEXTO YOUTUBE/00_MASTER/MIGRATION_ANALYSIS.md`, 420 líneas, commit local `a3485a0`, con una fila añadida a `INDEX.md`.
- El push de ese commit local falló con HTTP 401 por un PAT revocado. No se debe pedir ni almacenar un PAT en este documento. Esta entrada se registra a partir del resumen compartido, no del archivo local original.

## 2. Dictamen ejecutivo

La integración **no parte de cero**. Según el análisis compartido, el harness V1 ya existe en `main`, publicado en `main.py:1809–1810` como `/api/harness/v1`, con 55 checks, 19 operaciones, permisos fail-closed y un libro idempotente. Se reportan 45 baterías como suite canónica.

El adaptador existe en ambos lados y es Python: backend FastAPI y host `albra_seed`, comunicados por HTTP machine-to-machine. No se justifica introducir TypeScript ni crear otro adaptador sin evidencia. La conexión inicial se plantea mediante variables de entorno `YOUTUBE_HARNESS_URL` y `YOUTUBE_HARNESS_API_KEY` (confirmar el nombre exacto de la variable API_KEY en el código antes de configurar) y `install_youtube_harness()`.

### Frontera objetivo

`AGENTE-GENERAL → AgentAdapter del host → /api/harness/v1 → adaptador REST/espejo → motor audiovisual existente`

- AGENTE-GENERAL interpreta y coordina.
- El harness expone operaciones y contratos.
- El motor existente conserva el dominio audiovisual, las reglas de producción y los mecanismos de QA.
- GoogleFlowMCP es un puente/herramienta del motor, no un agente orquestador.

## 3. Hallazgos por área (A–L)

### A. Estado del harness
- Existe `/api/harness/v1` en `main.py:1809–1810`.
- El informe declara 55 checks, 19 operaciones, permisos fail-closed, libro idempotente y 45 baterías canónicas.
- Estas cifras se registran como hallazgos del análisis compartido; deben verificarse contra la revisión exacta antes de una migración operativa.

### B–C. Adaptadores y conexión
- Hay un AgentAdapter en el host y una superficie de operaciones del lado del harness.
- Ambos lados son Python; el transporte es HTTP M2M.
- P1 se plantea como conexión fría mediante configuración e instalación del adaptador existente, sin crear código nuevo.
- No se ha demostrado aún el host conectado en vivo. La existencia de los componentes no equivale a una prueba de integración.

### D. Skills y operaciones
- Se reportan 17 skills internas en `skills.py`, actualmente descriptivas y no ejecutables.
- Se reportan 19 operaciones del harness y 9 skills del host con prefijo `skill.youtube.*`.
- Huecos identificados para P3: nichos, `cleanup_failed`, `retry`, `validate` y `analyze`.
- Riesgo: las tres superficies de capacidades pueden divergir si no hay tests cruzados.

### E. Knowledge y dominio
Permanece en YOUTUBE-AUTOMATION: `knowledge.py`, Production JSON, P1/Start Frame (D-002), reglas de QA y audiovisuales, y `CONTEXTO YOUTUBE/`. La identidad y el conocimiento general del puesto no se migran al dominio audiovisual.

### F. VÓRTICE
- El análisis clasifica `agent.py` (533 líneas), `/api/chat` y el dashboard como legado; `/api/chat` está marcado DO_NOT_TOUCH.
- VÓRTICE no se importa al harness según el análisis.
- Clasificación: UI pura; lógica agéntica absorbible por el host; llamadas de pipeline ya representadas como operaciones.
- La retirada queda para P5, después de validar los pasos anteriores. No borrar ni modificar estos componentes en esta fase.

### G–H. LIPO y alcance de cambios futuro
- **KEEP:** motor audiovisual, contrato del harness, espejos REST, A2A.
- **MOVE:** componentes reportados como ya movidos; verificar antes de declarar completada esa categoría.
- **ADAPT:** conexión del host, resolución título→ID, limpieza compuesta, nichos v1.1, puente risk→L y A2A→`submit_production`.
- **DELETE LATER:** `agent.py`, `/api/chat`, `/api/cerebros`, vista de chat y `legacy.py`; solo en P5 y tras validación.
- Archivos candidatos para futura implementación: `capabilities/adapter/contracts`, cambios acotados en `main.py` (estimados en ~15 líneas) y `test_harness.py`; del lado AGENTE-GENERAL: variables de entorno, `install_youtube_harness`, match título→ID y `policies.py`. No se ha autorizado ni realizado esta implementación.

### I. Superficie protegida
No tocar como parte de esta migración:
- `production_json`, `guion_json`, `execution_contract`, `flow_jobs`, orquestador.
- `backend/pipeline/video.py` en el punto del timeout de FFmpeg (intervención separada).
- `flow_export/import`, `asset_resolver`, `flow_mcp_client`, `tools/GoogleFlowMCP`.
- Extensión F5/F5.1 y F2; HANDS; memorydv; seguridad y base de datos.
- `agent.py` y `/api/chat`, ambos congelados/DO_NOT_TOUCH durante esta fase.

### J. Plan por fases
1. **P0 — análisis:** reportado como completado.
2. **P1 — conexión fría:** configuración y smoke test de solo lectura, cero cambios de código.
3. **P2 — ciclo sin launch:** comprobar el ciclo de trabajo sin lanzar producción.
4. **P3 — huecos v1.1:** cerrar operaciones ausentes y añadir tests cruzados.
5. **P4 — A2A alineado:** formalizar delegación y alineación de contratos.
6. **P5 — retirada VÓRTICE:** solo tras superar las fases anteriores y revisar dependencias.

### K. Riesgos registrados
1. Divergencia entre espejos de operaciones y REST.
2. Tres fuentes de capacidades sin pruebas cruzadas.
3. Gobernanza de autonomía L0–L5 sin conexión demostrada con permisos fail-closed del harness.
4. Riesgo en la secuencia create+launch.
5. Resolución fuzzy M9.
6. Timeout del render FFmpeg.
7. Host no verificado en vivo.
8. Clave maestra compartida.
9. Operaciones faltantes entre skills y harness (nichos, cleanup_failed, retry/validate/analyze).
10. Posible retirada prematura del legado antes de probar el reemplazo.

Los riesgos se conservan como hallazgos del análisis compartido, no como una auditoría independiente reejecutada durante esta actualización.

## 4. Tabla de estado reportado

| Área | Estado reportado | Destino / siguiente acción |
|---|---|---|
| AGENTE-GENERAL | `b5b7220`, especialización lista, no conectado | P1: conexión por entorno |
| AgentAdapter | Existe en host y harness | Reutilizar; cerrar huecos en P3 |
| VÓRTICE | Legado, congelado, no importado por el harness | Retirar solo en P5 |
| Orquestador | Seis pasos + C.2 + QA gate | Motor protegido; no modificar |
| Production JSON | Adaptador y A2A formal reportados | Mantener como núcleo de dominio |
| Skills | 17 internas ↔ 19 operaciones ↔ 9 host | Test cruzado en P3 |
| Knowledge | `knowledge.py` + `CONTEXTO YOUTUBE/` | Permanece en el proyecto |
| GoogleFlowMCP | Vendorizado; video vía C.1 reportado | Mantener como herramienta del motor |
| Flow | Extensión 2.6.0 y cola con consent gate reportados | Zona protegida |
| HANDS | V1.0 aislada, no conectada | Misión separada |
| QA | QA forense y gate final reportados | Mantener en el motor |
| Publishing | Máquina de estados, 409 y QA gate reportados | Operación HIGH + HITL |

## 5. Decisión y STOP

**No se implementó la migración.** Esta documentación no conecta el agente, no cambia configuración, no refactoriza, no elimina VÓRTICE, no activa producción y no modifica el timeout FFmpeg.

Siguiente acción aprobada para retomar el trabajo: **P1 de conexión fría**, exclusivamente configuración y smoke test read-only, sin código. La reparación de FFmpeg es una intervención separada y debe mantenerse localizada en el timeout reportado. Antes de P1, verificar la revisión exacta de ambos repositorios, el nombre real de la variable de API key, los permisos y la disponibilidad del host. No incluir secretos ni PAT en Git, documentación ni logs.

## 6. Calidad de evidencia

Este documento es una **síntesis de continuidad basada en el informe A–L proporcionado en la conversación**. No equivale al informe local de 420 líneas, ni a una nueva ejecución de tests, ni a una prueba live. Los números de checks/operaciones, SHAs y ubicaciones de código deben tratarse como reportados hasta verificarlos en las revisiones correspondientes.
