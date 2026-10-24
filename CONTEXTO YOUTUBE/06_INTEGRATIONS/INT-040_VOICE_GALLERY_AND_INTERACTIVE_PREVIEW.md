# INT-040 — Galería de Voces Neuronales con Preescucha Interactiva

**Fecha de Implementación:** 24 de Octubre de 2026  
**Tipo:** Feature / Audio & TTS / UX / Frontend  
**Origen:** ClonaKit Feature Gap #2 (Inspirada en Anai App `anaiapp.ai`)  
**Estado:** IMPLEMENTADO / VERIFICADO AL 100% (Batería `test_voice_gallery`: 25/25 OK · 0 fallos, `test_scene_surgical_regen`: 17/17 OK, `test_pipeline_orchestrator`: 56/56 OK, `test_viral_hooks_generator`: 6/6 OK, `test_int036`: 23/23 OK, `test_mcp_manager`: 38/38 OK).

---

## 1. Problema y Necesidad

1. **Selección de Voz a Ciegas:** Anteriormente, el usuario seleccionaba la voz de sus videos a través de un simple `<select>` desplegable de texto en Ajustes o en el creador de Avatares, sin tener idea de cómo sonaba cada voz (tono, cadencia, acento o naturalidad).
2. **Falta de Catálogo Enriquecido por Acento y Nicho:** El sistema no exponía la variedad real de voces en español disponibles en Edge TTS ($0 ilimitado) ni las voces multimodales de Google Gemini TTS, agrupadas con metadatos descriptivos (género, país, estilo y casos de uso recomendados).
3. **Imposibilidad de Preescucha Rápida:** No existía ningún mecanismo para reproducir una muestra de audio corta e impactante sin tener que lanzar una generación completa de video.

---

## 2. Solución Arquitectónica Implementada

### 2.1 Catálogo Curado de Voces Neuronales (`backend/services/voices_catalog.py`)
- Definición de 17 voces neuronales de alta calidad con banderas (`flag`), países (`country`), género (`gender`), estilo vocal (`tone`), etiquetas (`tags`) y frases de muestra contextuales:
  - **Edge TTS ($0 Gratis e Ilimitado):**
    - 🇨🇴 `es-CO-SalomeNeural` (Salomé - Cálida y dinámica · Shorts y TikTok)
    - 🇨🇴 `es-CO-GonzaloNeural` (Gonzalo - Juvenil y moderno · Vlogs y tecnología)
    - 🇲🇽 `es-MX-JorgeNeural` (Jorge - Enérgico y contundente · Máxima retención)
    - 🇲🇽 `es-MX-DaliaNeural` (Dalia - Expresiva y versátil · Educación y tutoriales)
    - 🇦🇷 `es-AR-TomasNeural` (Tomás - Carismático y reflexivo · Ensayos y debate)
    - 🇦🇷 `es-AR-ElenaNeural` (Elena - Pausada y elegante · Finanzas y análisis)
    - 🇪🇸 `es-ES-AlvaroNeural` (Álvaro - Profundo y misterioso · Documentales y terror)
    - 🇪🇸 `es-ES-ElviraNeural` (Elvira - Formal y narrativa · Noticias y ciencia)
    - 🇺🇸 `es-US-AlonsoNeural` (Alonso - Ritmo alto y comercial · Motivación y fitness)
    - 🇺🇸 `es-US-IsabellaNeural` (Isabella - Fresca y contemporánea · Entretenimiento y moda)
    - 🇨🇱 `es-CL-LorenzoNeural` (Lorenzo - Sereno y descriptivo · Viajes e historia)
    - 🇵🇪 `es-PE-AlexNeural` (Alex - Neutro y didáctico · Universal LATAM/España)
  - **Google Gemini TTS Studio (Modelos Multimodales):**
    - 🎖️ `Fenrir` (Épica y dramática · Superproducciones y misterio)
    - 🎖️ `Puck` (Enérgica y pícara · Comedia y retos)
    - 🎖️ `Charon` (Solemne y profunda · Historia e imperios)
    - 🎖️ `Kore` (Cálida y envolvente · Bienestar y desarrollo personal)
    - 🎖️ `Aoede` (Artística y fluida · Literatura y mitología)
- **Caché en Disco Automática:** Las muestras de audio generadas se almacenan en `backend/data/voice_previews/` en formato MP3 (Edge) o WAV (Gemini), respondiendo en menos de 1 milisegundo a partir de la segunda reproducción.

### 2.2 Endpoints REST del Backend (`backend/main.py`)
- **`GET /api/voices`**:
  Devuelve el catálogo de voces con soporte de filtrado por `country`, `gender`, `provider` y búsqueda por texto libre `q`.
- **`POST /api/voices/preview`**:
  Sintetiza la muestra de audio bajo demanda o la recupera de la caché local, retornando la URL pública del archivo, duración y formato MIME.
- **`GET /api/voices/audio/{filename}`**:
  Sirve el archivo de audio con cabeceras `audio/mpeg` o `audio/wav` optimizadas para streaming en el navegador.
- **`POST /api/voices/select`**:
  Aplica la voz seleccionada tanto a nivel global del sistema (`config.EDGE_TTS_VOICE`, `config.TTS_PROVIDER`) como a nivel de un proyecto específico en SQLite (`db.update_project`).

### 2.3 Interfaz Web Interactiva (`backend/static/app.js` y `style.css`)
- **Modal de Galería de Voces (`openVoiceGallery`):**
  - Buscador reactivo por nombre, país, tono o etiquetas.
  - Chips de filtrado rápido por países (🇨🇴 Colombia, 🇲🇽 México, 🇪🇸 España, 🇦🇷 Argentina, 🇺🇸 US Latino, 🎖️ Gemini Studio).
  - Chips de filtrado por género (👩 Femenina / 👨 Masculina).
  - Tarjetas de voz con badges, descripción y botones:
    - **▶️ Escuchar / ⏸️ Pausar**: Con reproductor HTML5 `Audio` reactivo, feedback de carga (`⏳ Cargando…`) y estado visual activo.
    - **✓ Elegir / Usar voz**: Aplica la voz directamente al destino deseado (Ajustes Globales, Proyecto en creación, o Avatar).
- **Puntos de Integración en el Panel:**
  - En **⚙️ Ajustes (Locución TTS)**: Botón `🎙️ Galería de Voces`.
  - En **Wizard de Creación de Proyectos (Paso 4)**: Botón `🎧 Galería` junto al selector de voz.
  - En **🎭 Avatar Studio PRO**: Botón `🎧 Galería` junto a la selección de voz del avatar.

---

## 3. Archivos Modificados e Impacto

| Archivo | Cambio |
| :--- | :--- |
| `backend/services/voices_catalog.py` | NUEVO: Catálogo enriquecido de 17 voces, filtros deterministas, síntesis y caché de preescucha. |
| `backend/main.py` | Endpoints `/api/voices`, `/api/voices/preview`, `/api/voices/audio/{filename}` y `/api/voices/select`. |
| `backend/static/app.js` | Módulo `VG_STATE`, `openVoiceGallery`, `previewVoice`, `selectVoiceFromGallery`, e integración en Ajustes, Wizard y Avatares. |
| `backend/static/style.css` | Clases `.voice-gallery-overlay`, `.vg-card`, `.vg-chip`, `.vg-play-btn`, etc. |
| `tests/test_voice_gallery.py` | NUEVO: Suite de pruebas unitarias y de integración (25/25 OK · 0 fallos). |
| `CONTEXTO YOUTUBE/06_INTEGRATIONS/INTEGRATION_INDEX.md` | Registro de INT-040 en el índice canónico. |

---

## 4. Verificación y Resultados de Tests

Se ejecutó la batería de pruebas automatizada `tests/test_voice_gallery.py`:
- ✓ `GET /api/voices` responde 200 con al menos 15 voces catalogadas.
- ✓ Filtrado por país Colombia devuelve voces colombianas (Salomé, Gonzalo).
- ✓ Filtrado por género devuelve solo voces del género indicado.
- ✓ Filtrado por proveedor devuelve solo voces de dicho proveedor.
- ✓ Búsqueda por texto (query `q`) localiza voces por estilo y descripción.
- ✓ `POST /api/voices/preview` sintetiza y devuelve URL de audio válida.
- ✓ `GET /api/voices/audio/{filename}` sirve el binario MP3 con MIME `audio/mpeg`.
- ✓ `POST /api/voices/select` actualiza la configuración global del sistema y los proyectos en SQLite.
- ✓ Guardias de error (400 en payload vacío, 404 en archivo inexistente o voz no catalogada).

**Regresión Global:**
- `test_voice_gallery.py`: 25/25 OK (100%)
- `test_scene_surgical_regen.py`: 17/17 OK (100%)
- `test_pipeline_orchestrator.py`: 56/56 OK (100%)
- `test_viral_hooks_generator.py`: 6/6 OK (100%)
- `test_int036_profile_heal_and_strict_auth.py`: 23/23 OK (100%)
- `test_mcp_manager.py`: 38/38 OK (100%)
