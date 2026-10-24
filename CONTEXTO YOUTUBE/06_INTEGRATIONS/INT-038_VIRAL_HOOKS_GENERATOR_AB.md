# INT-038 · Generador A/B de Hooks Virales (3 Segundos de Impacto)

**Fecha:** 2026-10-24  
**Origen:** Feature Gap #1 identificada en Anai App (`anaiapp.ai`) mediante ClonaKit  
**Estado:** ✅ IMPLEMENTADO Y VERIFICADO AL 100% (Batería `test_viral_hooks_generator.py`: 6/6 OK)  
**Módulos afectados:** `backend/pipeline/script_gen.py`, `backend/services/gemini_client.py`, `backend/main.py`, `backend/static/app.js`

---

## 1. Motivación y Objetivo

El 70% de la audiencia en YouTube Shorts, TikTok e Instagram Reels abandona el video si los primeros 3 segundos no logran romper el patrón de scroll.
A diferencia del flujo anterior (que generaba un único gancho pasivo dentro del guion), se implementó un **Generador A/B/C de Hooks Virales** con 3 ángulos psicológicos de retención probada:

1. **Variante A (Curiosidad):** Abre un bucle de misterio o pregunta provocativa que el cerebro necesita resolver.
2. **Variante B (Contradicción):** Desafía una creencia popular o señala un error masivo que la mayoría comete.
3. **Variante C (Dato Chocante):** Inicia con una cifra extrema, un hecho alarmante o una consecuencia inmediata.

---

## 2. Componentes Implementados

### A. Motor de Generación (`backend/pipeline/script_gen.py`)
- `HOOK_CATEGORIES`: Catálogo de arquetipos psicológicos (Curiosidad, Contradicción, Dato Chocante) con plantillas dinámicas y sugerencias visuales (`visual_cues`).
- `generate_viral_hooks(topic, niche, count=3, custom_prompt)`: Función asíncrona que:
  - Invoca a Gemini 2.5 con prompt especializado y esquema estructurado `schema_viral_hooks()`.
  - En caso de indisponibilidad de API o modo local (\$0), aplica `_local_fallback_hooks` determinista sin coste ni dependencias externas.
- `build_result`: Garantiza que todo guion generado incluya `hook_variants` (3 opciones) y `selected_hook_id` (por defecto "A").

### B. Esquemas JSON Estructurados (`backend/services/gemini_client.py`)
- `schema_scenes`: Actualizado para soportar opcionalmente el array de `hook_variants`.
- `schema_viral_hooks`: Esquema JSON estricto para la generación directa de hooks (`id`, `type`, `label`, `hook`, `visual_cue`, `estimated_retention`).

### C. Endpoints REST (`backend/main.py`)
- `POST /api/pipeline/generate-hooks`: Genera 3 ganchos A/B a demanda a partir de un tema (`topic`), nicho opcional y prompt personalizado.
- `POST /api/projects/{pid}/select-hook`: Aplica el gancho elegido al proyecto: actualiza `project.hook`, guarda la selección en `meta.selected_hook_id` y sincroniza automáticamente la narración de la **Escena 1 (`scenes[0].narration`)**.

### D. Interfaz de Usuario Interactiva (`backend/static/app.js`)
- En la vista de proyecto (`renderProject`):
  - Nuevo panel interactivo **"🎯 Ganchos Virales A/B (Primeros 3 segundos)"** con 3 tarjetas visuales destacadas:
    - 🟣 **Variante A · Curiosidad**
    - 🟠 **Variante B · Contradicción**
    - 🔴 **Variante C · Dato Chocante**
  - Muestra el texto exacto, la sugerencia de toma visual (`visual_cue`) y la estimación de retención (`⚡ 96%`).
  - Al hacer clic en cualquier tarjeta, se envía la actualización al backend y se resalta como **`✓ ACTIVO EN ESCENA 1`**.
  - Botón **`⚡ Probar otros 3 Hooks`** para solicitar variantes alternativas instantáneas con IA.

---

## 3. Verificación y Baterías de Pruebas

Se creó la suite automatizada [`tests/test_viral_hooks_generator.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/tests/test_viral_hooks_generator.py):
- `test_local_fallback_hooks_structure`: **PASS**
- `test_generate_viral_hooks_async`: **PASS**
- `test_build_result_includes_hook_variants`: **PASS**
- `test_api_generate_hooks_success`: **PASS**
- `test_api_generate_hooks_validation_error`: **PASS**
- `test_api_select_hook_updates_project_and_scenes`: **PASS**

### Regresión del Sistema Completo:
- `test_int036_profile_heal_and_strict_auth.py`: **23/23 OK**
- `test_pipeline_orchestrator.py`: **56/56 OK**
- `test_mcp_manager.py`: **38/38 OK**
- Live API (`http://127.0.0.1:8000/api/pipeline/generate-hooks`): **HTTP 200 OK**
