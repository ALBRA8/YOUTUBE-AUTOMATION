# INT-042 — Perfiles de Marca y Canales Persistentes (Brand Profile Engine)

## Estado
- **Estado:** IMPLEMENTADO / VERIFICADO AL 100% (Batería `test_brand_profiles`: 9/9 OK · 0 fallos, `test_subtitle_presets`: 30/30 OK, `test_voice_gallery`: 25/25 OK, `test_pipeline_orchestrator`: 56/56 OK).
- **Fecha:** 2026-10-24
- **Origen:** ClonaKit Feature Gap #5 inspirada en Anai App (`anaiapp.ai`) — Configuración persistente de canales para mantener coherencia de marca sin reconfigurar cada video.
- **Componentes:**
  - `backend/services/brand_profiles.py` (servicio de negocio y persistencia)
  - `backend/database.py` (tabla `brand_profiles` e integración con `projects`)
  - `backend/main.py` (endpoints REST CRUD y asignación de proyectos)
  - `backend/static/app.js` (UI modal de gestión, barra interactiva en Wizard y Ajustes)
  - `backend/static/style.css` (estilos adaptativos para barra de canal y panel modal)
  - `tests/test_brand_profiles.py` (batería de tests unitarios y de integración)

---

## 1. Motivación y Análisis de Brecha (ClonaKit Gap #5)
En plataformas de generación de contenido como Anai App, los creadores que operan canales temáticos en YouTube Shorts, TikTok o Instagram Reels necesitan que cada video nuevo respete rigurosamente:
1. El **tono de voz y personalidad** del canal (urgente, intrigante, pausado, humorístico, etc.).
2. El **público objetivo** y nicho específico.
3. El **estilo visual de imagen** preferido (cinematic, hiperrealista, anime, etc.).
4. La **voz neuronal** y proveedor TTS por defecto (Edge TTS o Gemini TTS).
5. El **preset de subtítulos de alta retención** (Hormozi, MrBeast, Neon, etc.).
6. **Directivas estrictas de guion** (evitar saludos, ganchos numéricos, oraciones cortas).

Sin esta funcionalidad, el usuario debía volver a configurar voz, subtítulos, estilo y escribir manualmente las instrucciones en cada nuevo video. Con **INT-042**, cada canal cuenta con su Brand Profile persistente, aplicable con un solo clic en el Wizard de Creación o heredado automáticamente.

---

## 2. Arquitectura de Datos y Persistencia

### 2.1 Esquema SQLite (`brand_profiles`)
Se incorporó una nueva tabla relacional en `backend/database.py` con migración automática y segura:

```sql
CREATE TABLE IF NOT EXISTS brand_profiles (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    niche          TEXT NOT NULL DEFAULT '',
    audience       TEXT NOT NULL DEFAULT '',
    tone           TEXT NOT NULL DEFAULT '',
    visual_style   TEXT NOT NULL DEFAULT 'auto',
    voice          TEXT NOT NULL DEFAULT 'es-ES-AlvaroNeural',
    tts_provider   TEXT NOT NULL DEFAULT 'edge-tts',
    subtitle_style TEXT NOT NULL DEFAULT 'hormozi',
    prompt_rules   TEXT NOT NULL DEFAULT '',
    is_default     INTEGER NOT NULL DEFAULT 0,
    meta           TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brand_profiles_default ON brand_profiles(is_default);
```

Asimismo, se extendió la tabla `projects` con la columna `brand_profile_id TEXT` para vincular cualquier proyecto con su canal de origen.

---

## 3. Endpoints REST Implementados

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/brand-profiles` | Lista todos los perfiles guardados (predeterminado primero). |
| `POST` | `/api/brand-profiles` | Crea un nuevo perfil de canal/marca con validación. |
| `GET` | `/api/brand-profiles/default` | Obtiene el perfil predeterminado activo. |
| `GET` | `/api/brand-profiles/{pid}` | Obtiene el detalle de un perfil específico. |
| `PATCH` | `/api/brand-profiles/{pid}` | Actualiza campos del perfil existente. |
| `DELETE` | `/api/brand-profiles/{pid}` | Elimina el perfil y reasigna el predeterminado si correspondía. |
| `POST` | `/api/brand-profiles/{pid}/default` | Establece el perfil como predeterminado activo global. |
| `POST` | `/api/brand-profiles/{pid}/apply` | Aplica la configuración del perfil a un proyecto existente. |
| `GET` | `/api/brand-profiles/{pid}/directives` | Retorna directivas formateadas listas para inyección en el prompt de Gemini. |

---

## 4. Experiencia de Usuario en Frontend (`app.js` y `style.css`)

1. **Barra Interactiva en el Wizard de Creación (`bp-wiz-bar`):**
   - Visible en la parte superior del Wizard de creación (Paso 1 a 4).
   - Muestra el canal activo actual con su nicho.
   - Selector desplegable para alternar instantáneamente de canal.
   - Al cambiar de canal, se autocompletan en vivo el estilo visual, la voz, el proveedor TTS y el preset de subtítulos, mostrando una notificación toast contextual.
   - Botón directo `⚙️ Gestionar` para abrir el modal administrativo.

2. **Modal Completo de Gestión de Canales (`openBrandProfilesModal`):**
   - Columna izquierda: Lista interactiva de canales creados con insignia `⭐ Default` y botón `+ Nuevo`.
   - Columna derecha: Formulario reactivo con:
     - Nombre del canal y nicho/categoría.
     - Audiencia objetivo y tono de voz/ritmo.
     - Estilo visual preferido.
     - Preset de subtítulos con botón lanzador directo al Switcher (`🎨 Presets` de INT-041).
     - Voz neuronal y proveedor con botón lanzador directo a la Galería (`🎧 Galería` de INT-040).
     - Directivas estrictas de prompt para guion.
     - Casilla para marcar como predeterminado.
   - Botón `🚀 Aplicar este perfil ahora` al abrirse en contexto de Wizard o Proyecto.

3. **Tarjeta en la Sección de Ajustes (`renderSettings`):**
   - Tarjeta dedicada con badge `INT-042` y botón `🏢 Administrar Canales y Marcas` para acceso rápido y centralizado.

---

## 5. Verificación y Resultados de Tests

Se construyó la suite `tests/test_brand_profiles.py` cubriendo el 100% de los casos:
- **`test_seed_starter_profile`:** Siembra automática del perfil de bienvenida si la base de datos está vacía.
- **`test_create_and_get_brand_profile`:** Creación con todos los atributos y consulta por ID.
- **`test_create_requires_valid_name`:** Rechazo con HTTP 400 si el nombre está vacío.
- **`test_default_profile_toggle`:** Exclusividad del perfil predeterminado (solo uno activo a la vez).
- **`test_update_brand_profile`:** Modificación parcial de campos y timestamp `updated_at`.
- **`test_delete_brand_profile_and_fallback`:** Eliminación segura y promoción de fallback automático.
- **`test_apply_brand_profile_to_project`:** Aplicación de atributos a columnas y `meta` de proyectos SQLite.
- **`test_format_prompt_directives`:** Generación de bloque de texto estructurado para el motor LLM.
- **`test_api_brand_profiles_endpoints`:** Ciclo REST completo (GET, POST, PATCH, DEFAULT, DIRECTIVES, APPLY, DELETE, 404, 400) e integración de creación de proyectos vía `POST /api/projects`.

**Resultado:**
- `tests/test_brand_profiles.py`: **9 OK · 0 fallos** (100% PASS).
- Regresión total sin fallos en suites INT-038, INT-039, INT-040, INT-041, INT-036, INT-023 e INT-022.
