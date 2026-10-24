# INT-041 — Presets Visuales de Subtítulos de Alta Retención (Shorts Style Switcher)

**Fecha de Implementación:** 24 de Octubre de 2026  
**Tipo:** Feature / Typography & Subtitles / UX / Video Rendering  
**Origen:** ClonaKit Feature Gap #4 (Inspirada en Anai App `anaiapp.ai`)  
**Estado:** IMPLEMENTADO / VERIFICADO AL 100% (Batería `test_subtitle_presets`: 30/30 OK · 0 fallos, `test_voice_gallery`: 25/25 OK, `test_scene_surgical_regen`: 17/17 OK, `test_pipeline_orchestrator`: 56/56 OK, `test_viral_hooks_generator`: 6/6 OK, `test_int036`: 23/23 OK, `test_mcp_manager`: 38/38 OK).

---

## 1. Problema y Necesidad

1. **Subtítulos Rígidos sin Previsualización:** En YouTube Shorts y TikTok, el estilo visual de los subtítulos es determinante para retener la atención (especialmente cuando los usuarios navegan sin auriculares). Anteriormente, el sistema solo ofrecía opciones fijas sin previsualizador ni variedad estética.
2. **Falta de Estilos Populares de Creadores:** Faltaban presets inspirados en las tendencias más virales de la industria (MrBeast, Hormozi Gold, Neon Cyberpunk, Boxed UGC de anuncios y Cinema Minimal).
3. **Imposibilidad de Previsualizar Antes de Renderizar:** El usuario no podía ver cómo luciría el texto con su fuente, color de resalto, borde o caja antes de iniciar el costoso ensamblado FFmpeg.

---

## 2. Solución Arquitectónica Implementada

### 2.1 Catálogo y Motor de Generación ASS Extendido (`backend/pipeline/subtitles.py`)
- Se ampliaron los presets disponibles en `SUB_STYLES` y `SUBTITLE_PRESETS_CATALOG` a 8 estilos de alto impacto:
  - 📱 **Shorts Dinámico (Default):** Tipografía Montserrat ExtraBold con paleta de contraste adaptativo inteligente WCAG >= 4.5:1.
  - ⚡ **Hormozi Gold:** Tipografía Impact en amarillo dorado (`&H0000FFFF&`), borde negro ultra-grueso y sombra pronunciada.
  - 🔴 **MrBeast Bold:** Tipografía masiva con mayúsculas forzadas, pop de escala intensificado (+25%), outline negro pesado y contraste visual extremo.
  - 🟢 **Neon Cyberpunk:** Verde esmeralda y cian eléctrico con resplandor glow (`&H0000FF7F&`), diseñado para tecnología, gaming y misterio.
  - 💬 **TikTok Fast:** 1 palabra por bloque en blanco puro sobre fondo de alto contraste, para ritmos rápidos y locuciones aceleradas.
  - 📦 **Boxed UGC:** Caja rectangular oscura detrás del texto (`BorderStyle=3`, `&HAA000000&`) con tipografía blanca nítida, ideal para reviews y anuncios estilo Anai.
  - 🎬 **Cinema Minimal:** Tipografía limpia y moderna (Montserrat), centrado inferior (`Alignment=2`), borde suave y espaciado de cine para documentales.
  - 🎤 **Karaoke Pop:** Verde lima vibrante con cambio de color y sincronización exacta palabra a palabra.
- **Protección de Contratos Legacy:** Se preservó el contrato byte-idéntico de `Hormozi` (`tests/test_typography.py`) y la cabecera `Shorts`, garantizando 0 regresiones.

### 2.2 Endpoints REST del Backend (`backend/main.py`)
- **`GET /api/subtitles/presets`**:
  Devuelve el catálogo de presets con metadatos descriptivos, estilos CSS listos para renderizado en el navegador y frases de muestra.
- **`POST /api/subtitles/apply`**:
  Aplica el estilo seleccionado a un proyecto específico (`db.update_project(pid, meta={"subtitle_style": ...})`) o como configuración predeterminada global del sistema (`config.DEFAULT_SUBTITLE_STYLE`).
- **Validación Dinámica:** Se actualizó la creación de proyectos para aceptar cualquier estilo válido del catálogo `SUB_STYLES` sin listas blancas rígidas.

### 2.3 Interfaz Web Interactiva (`backend/static/app.js` y `style.css`)
- **Modal de Selector de Subtítulos (`openSubtitleSwitcher`):**
  - **Escenario de Previsualización en Vivo (`ss-preview-stage`):** Renderiza en tiempo real el texto de muestra con las propiedades CSS exactas (fuente, borde, sombras, caja, mayúsculas).
  - **Entrada de Texto Personalizado:** Permite al usuario escribir cualquier frase personalizada para comprobar cómo se verá antes de aplicar el estilo.
  - **Grid de Presets:** Muestra tarjetas con muestras visuales en miniatura y badges de estado (`✓ ACTIVO`).
- **Puntos de Integración en el Panel:**
  - En el **Editor de Proyectos Studio (`renderProject`)**: Botón interactivo `🎨 Subtítulos: [ESTILO]` para cambiar de preset en cualquier proyecto con un clic.
  - En el **Wizard de Creación (Paso 4)**: Dropdown enriquecido con los 8 estilos + botón `🎨 Presets` que abre el switcher visual.

---

## 3. Archivos Modificados e Impacto

| Archivo | Cambio |
| :--- | :--- |
| `backend/pipeline/subtitles.py` | Definición de 8 presets en `SUB_STYLES` y `SUBTITLE_PRESETS_CATALOG`, soporte de `border_style=3`, `alignment`, `uppercase` y `pop_scale`. |
| `backend/main.py` | Endpoints `GET /api/subtitles/presets` y `POST /api/subtitles/apply`, soporte dinámico de presets en creación de proyectos. |
| `backend/static/app.js` | Módulo `SS_STATE`, `openSubtitleSwitcher`, stage reactivo y botones en Studio y Wizard. |
| `backend/static/style.css` | Clases `.subs-switcher-overlay`, `.ss-preview-stage`, `.ss-card`, etc. |
| `tests/test_subtitle_presets.py` | NUEVO: Suite de pruebas unitarias y de integración (30/30 OK · 0 fallos). |
| `CONTEXTO YOUTUBE/06_INTEGRATIONS/INTEGRATION_INDEX.md` | Registro de INT-041 en el índice canónico. |

---

## 4. Verificación y Resultados de Tests

Se ejecutó la batería de pruebas automatizada `tests/test_subtitle_presets.py`:
- ✓ `GET /api/subtitles/presets` responde 200 con al menos 8 presets completos.
- ✓ Todos los estilos esperados (`shorts`, `hormozi`, `mrbeast`, `neon`, `tiktok`, `boxed`, `minimal`, `karaoke`) están presentes con CSS y textos de muestra.
- ✓ Contrato legacy de Hormozi e INT-021 de Shorts 100% preservados.
- ✓ Generación ASS especializada para MrBeast (mayúsculas + pop 125%), Boxed (BorderStyle=3), Minimal (Alignment=2) y Neon (verde neón).
- ✓ `POST /api/subtitles/apply` aplica estilo global y por proyecto en SQLite.
- ✓ Validaciones de error (400 en estilo inválido, 404 en proyecto no encontrado).

**Regresión Global:**
- `test_subtitle_presets.py`: 30/30 OK (100%)
- `test_voice_gallery.py`: 25/25 OK (100%)
- `test_scene_surgical_regen.py`: 17/17 OK (100%)
- `test_pipeline_orchestrator.py`: 56/56 OK (100%)
- `test_viral_hooks_generator.py`: 6/6 OK (100%)
- `test_int036_profile_heal_and_strict_auth.py`: 23/23 OK (100%)
- `test_mcp_manager.py`: 38/38 OK (100%)
