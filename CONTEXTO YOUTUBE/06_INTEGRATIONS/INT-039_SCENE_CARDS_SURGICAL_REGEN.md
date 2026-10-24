# INT-039 — Tarjetas de Escenas con Regeneración Quirúrgica (Google Flow)

**Fecha de Implementación:** 24 de Octubre de 2026  
**Tipo:** Feature / Robustez / Browser Automation / UX  
**Origen:** ClonaKit Feature Gap #3 (Inspirada en Anai App `anaiapp.ai`)  
**Estado:** IMPLEMENTADO / VERIFICADO AL 100% (Batería `test_scene_surgical_regen`: 17/17 OK · 0 fallos, `test_pipeline_orchestrator`: 56/56 OK, `test_viral_hooks_generator`: 6/6 OK, `test_int036`: 23/23 OK, `test_mcp_manager`: 38/38 OK).

---

## 1. Problema y Necesidad

Al generar videos automatizados mediante el pipeline de Google Flow y el editor de proyectos:
1. **Regeneración de Escenas Bloqueada:** En el orquestador (`pipeline_orchestrator.py`), el método `retry_scenes` solo permitía reintentar escenas con estado `failed`. Si una escena se completaba exitosamente (`status="done"`) pero al usuario no le gustaba el resultado estético de esa toma específica, intentar re-despacharla disparaba una excepción `NO_FAILED_SCENES`.
2. **Falta de Acción Quirúrgica en el Estudio:** En el editor visual de proyectos (`sceneCard`), el usuario solo contaba con un botón para regenerar la imagen estática mediante Gemini/local, sin un acceso directo y quirúrgico para re-renderizar la toma completa mediante Google Flow MCP.
3. **Costo Innecesario de Re-runs Completos:** Ante una toma imperfecta o indeseada en una escena intermedia (ej. Escena 2 de 5), el usuario se veía obligado a descartar toda la corrida y re-ejecutar las etapas de investigación (NotebookLM) y guion (LLM), desperdiciando tiempo y recursos.

---

## 2. Solución Arquitectónica Implementada

### 2.1 Orquestador con Retry Forzado Quirúrgico (`backend/services/pipeline_orchestrator.py`)
- Se extendió la firma de `retry_scenes(run_id, scene_ids=None, force=False)`:
  - Cuando `force=False` (comportamiento por defecto): Mantiene la guardia estricta que exige escenas fallidas (`NO_FAILED_SCENES`).
  - Cuando `force=True`: Permite especificar cualquier `scene_id` de la corrida (incluso si estaba en `done`).
  - Reajusta atómicamente el estado de la escena a `pending`, decrementa `done_count` y re-ejecuta `_stage3(run, only_scene_ids=targets)` despachando exclusivamente esa toma a Google Flow con el asset de referencia `@personaje` intacto.
  - Al completar la escena, incrementa el contador de intentos (`attempts`) y recalcula el progreso y estado general de la corrida (`ST_DONE`, 100%).

### 2.2 Endpoints REST del Backend (`backend/main.py`)
- **`POST /api/pipeline/retry-scenes`**:
  - Extrae el parámetro `force: bool = False` del cuerpo de la petición y lo transmite al orquestador.
  - Permite regenerar tomas individuales de corridas activas o finalizadas.
- **`POST /api/scenes/{scene_id}/regenerate-flow`**:
  - Endpoint dedicado para el editor de proyectos Studio.
  - Valida el `project_id` contra inyecciones y traversal (`_pid`).
  - Ejecuta la generación visual de la escena vía Google Flow MCP (con degradación controlada a Gemini/local si Flow no está conectado).
  - Actualiza `image_path` en la base de datos SQLite y retorna URL con cache-busting `v={timestamp}`.

### 2.3 Interfaz Web Interactiva (`backend/static/app.js`)
- **En las Tarjetas de Escena (`sceneCard`)**:
  - Se añadió el botón interactivo:
    `<button class="btn small ghost" onclick="regenFlowScene('${sc.id}')" title="Regenerar solo esta toma quirúrgicamente con Google Flow">🔄 Toma Flow</button>`
  - Implementación de la función `regenFlowScene(sid)` con feedback visual inmediato (toasts animados y refresco in-place de la vista del proyecto).
- **En los Chips del Pipeline Runner (`pipeStepsHTML`)**:
  - Cada chip de escena (`s1`, `s2`, `s3`) incluye un botón de acción rápida `🔄` para regenerar solo esa toma individual con Google Flow mediante `pipeRetryScene(runId, sceneId)`.

---

## 3. Archivos Modificados e Impacto

| Archivo | Cambio |
| :--- | :--- |
| `backend/services/pipeline_orchestrator.py` | Soporte de `force=True` en `retry_scenes` para re-despacho quirúrgico de tomas individuales en cualquier estado. |
| `backend/main.py` | Propagación de `force` en `POST /api/pipeline/retry-scenes` y creación de `POST /api/scenes/{scene_id}/regenerate-flow`. |
| `backend/static/app.js` | Botón `🔄 Toma Flow` en `sceneCard`, botón `🔄` en chips del pipeline, funciones `regenFlowScene` y `pipeRetryScene`. |
| `tests/test_scene_surgical_regen.py` | Batería automatizada integral (17/17 tests passing). |
| `CONTEXTO YOUTUBE/06_INTEGRATIONS/INTEGRATION_INDEX.md` | Registro de INT-039 en el índice canónico del proyecto. |

---

## 4. Verificación y Resultados de Tests

Se ejecutó la batería de pruebas automatizada `tests/test_scene_surgical_regen.py`:
- ✓ `retry_scenes` sin `force` sobre escena 'done' lanza error `NO_FAILED_SCENES`.
- ✓ `retry_scenes` con `force=True` completa al 100%.
- ✓ `done_count` permanece consistente.
- ✓ `s2` attempts incrementado a 2.
- ✓ `s1` y `s3` no se re-ejecutan (attempts permanece en 1).
- ✓ Escena inexistente con `force=True` lanza `NO_TARGET_SCENES`.
- ✓ Endpoint `POST /api/pipeline/retry-scenes` con `force=True` responde 200 OK y actualiza la escena.
- ✓ Endpoint `POST /api/scenes/{id}/regenerate-flow` responde 200 OK, actualiza SQLite y devuelve método y URL.
- ✓ Endpoint `POST /api/scenes/{inexistente}/regenerate-flow` responde 404 Not Found.

**Regresión Global:**
- `test_scene_surgical_regen.py`: 17/17 OK (100%)
- `test_pipeline_orchestrator.py`: 56/56 OK (100%)
- `test_viral_hooks_generator.py`: 6/6 OK (100%)
- `test_int036_profile_heal_and_strict_auth.py`: 23/23 OK (100%)
- `test_mcp_manager.py`: 38/38 OK (100%)
