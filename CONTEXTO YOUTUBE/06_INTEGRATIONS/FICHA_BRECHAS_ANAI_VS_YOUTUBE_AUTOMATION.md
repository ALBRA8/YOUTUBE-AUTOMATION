# Ficha de Análisis de Brechas: Anai App (`anaiapp.ai`) vs YouTube Automation

**Fecha:** 2026-10-24  
**Método:** ClonaKit (Ingeniería Inversa de Sala Limpia + Auditoría de Bundles Next.js + Mapeo de Flujo de Producción)  
**Objetivo:** Identificar qué capacidades tiene Anai que le faltan a `YOUTUBE AUTOMATION` para implementar las mejores funciones de forma nativa en nuestro sistema.

---

## 1. Resumen Ejecutivo de Anai App

**Anai (`anaiapp.ai`)** es un estudio SaaS de creación automatizada de **videos cortos verticales (formato 9:16)** para TikTok, Instagram Reels, YouTube Shorts y anuncios UGC.

### El Flujo de Trabajo que Utiliza Anai:
1. **Paso 1: Ideación y Guion con Ganchos:** El usuario introduce una idea; la IA estructura el guion y propone ganchos (hooks) de alta retención para los primeros 3 segundos.
2. **Paso 2: Selección de Personaje y Assets:** Elección de avatar/clon y estilo visual (`/api/user-assets/:assetId`).
3. **Paso 3: Renderizado por Línea de Tiempo (`/api/render-timeline/:jobId`):** Cada escena (3 a 5 segundos) se procesa de forma asíncrona.
4. **Paso 4: Revisión y Aprobación:** El usuario aprueba escena por escena o regenera fragmentos específicos.
5. **Paso 5: Exportación Directa:** Descarga MP4 vertical limpio sin marcas de agua.

---

## 2. Radiografía de APIs y Arquitectura Descubierta

Mediante el análisis de `_buildManifest.js` y los chunks compilados de Next.js (`0cz1d0mv5g_q7.js`, `39eogy59c0qzd.js`, `1ihsb1s53v94o.js`), extrajimos sus endpoints reales:

```
[Módulo de Producción y Render]
  POST /api/render-timeline                    -> Crea el job de renderizado del timeline
  GET  /api/render-timeline/:jobId/status       -> Polling del estado de cada escena
  GET  /api/render-timeline/:jobId/output       -> Previsualización del video
  GET  /api/render-timeline/:jobId/download     -> Descarga final del MP4
  GET  /api/user-assets/:assetId                -> Gestión de imágenes, logos y recursos del usuario

[Módulo de Autenticación y Sesión]
  POST /api/auth/google                        -> NextAuth Google OAuth
  POST /api/auth/login                         -> Login con correo
  GET  /api/auth/me                            -> Usuario y suscripción activa
  POST /api/auth/refresh                       -> Refresco de token JWT
  GET  /api/maintenance                        -> Chequeo de salud del backend

[Gestión de Estado (Zustand)]
  Store: "Onboarding Store"
    - setSessionId
    - setOnboardingProfile (nicho, tono, audiencia)
    - setScriptFromIdeasFlow (generador de guiones a partir de lluvia de ideas)
```

---

## 3. Matriz de Comparación y Brechas (Gap Analysis)

| Dimensión | En tu sistema (`YOUTUBE AUTOMATION`) | En Anai App (`anaiapp.ai`) | Veredicto / Brecha |
| :--- | :--- | :--- | :--- |
| **Modelo de Costo** | **\$0 ilimitado local.** Eres dueño del pipeline y del hardware. | **Sistema de créditos cerrado** (se acaban rápido y requieren pagar suscripciones mensuales). | 🟢 **Gana tu sistema** |
| **Generación Visual** | **Google Flow (Cinematográfico)**: Video e imagen generada con personajes consistentes (`@mention`) y Start Frame. | Avatares genéricos estáticos y banco de stock. | 🟢 **Gana tu sistema** |
| **Investigación** | **NotebookLM**: Fuentes reales, papers y extracción de contexto profunda. | Prompts básicos a LLM sin fuentes verificadas. | 🟢 **Gana tu sistema** |
| **Ganchos Virales (Hooks)** | Un solo gancho estándar redactado en el guion. | **Generador A/B de Hooks**: 3 propuestas distintas para los primeros 3 s (curiosidad, dolor, dato impactante). | 🔴 **BRECHA 1 (Alta Prioridad)** |
| **Editor de Guion por Bloques** | Guion en JSON o texto corrido en el panel. | **Línea de Escenas (Scene Cards)**: Cada bloque de 3-5 s tiene su texto, prompt visual asignado y botón de reintento. | 🔴 **BRECHA 2 (Alta Prioridad)** |
| **Selector de Voces** | Selección mediante string en `.env` (Edge TTS / Gemini TTS). | **Galería de Voces con Preescucha**: Botón "Play" para escuchar una frase de muestra antes de generar. | 🟡 **BRECHA 3 (Media Prioridad)** |
| **Presets de Subtítulos** | Tipografía dinámica de impacto Shorts (`typography.py`), configurada por código. | **Selector Visual de Estilos**: Botones para cambiar color de caja, resalto de palabra y emojis dinámicos. | 🟡 **BRECHA 4 (Media Prioridad)** |
| **Memoria de Canal / Marca** | Sin perfil persistente; cada ejecución requiere rellenar tema y nicho. | **Brand Profile persistente**: Guarda nombre, nicho, tono y colores de la marca. | 🟡 **BRECHA 5 (Media Prioridad)** |

---

## 4. Las 5 Funciones de Anai que Podemos Clonar e Implementar

### 🎯 1. Generador A/B de Hooks Virales (Primeros 3 Segundos)
- **Por qué importa:** En TikTok y YouTube Shorts, el 70% de las personas deslizan el video en los primeros 3 segundos. Si el gancho no atrapa, el video muere.
- **Cómo lo implementamos:** En el Stage 2 del orquestador (`script_gen.py`), hacer que Gemini genere **3 variantes de hook**:
  1. *Pregunta provocadora / Curiosidad.*
  2. *Contradicción / Mito común.*
  3. *Dato chocante / Estadístico.*
- **En la UI:** Un selector radio o pills donde el usuario elige cuál hook quiere para su video antes de renderizar.

### 🎬 2. Interfaz de Escenas Desglosadas (Scene Cards con Regeneración)
- **Por qué importa:** Actualmente, si una escena en Google Flow no te gusta, regenerar todo el video cuesta tiempo.
- **Cómo lo implementamos:** En el panel web (`app.js`), renderizar cada escena como una tarjeta interactiva:
  - Texto de la locución (3-5 s).
  - Prompt visual y personaje `@mention`.
  - Botón: **🔄 Regenerar solo esta toma**.
- **En el backend:** Ya tenemos el endpoint de retry quirúrgico en `pipeline_orchestrator.py` (`PARTIAL_FAILURES`), solo nos falta la UI para activarlo visualmente.

### 🎙️ 3. Galería de Voces con Reproductor de Muestra (Audio Preview)
- **Por qué importa:** Elegir voces como `es-CO-SalomeNeural`, `es-MX-DaliaNeural` o `Fenrir` a ciegas es incómodo.
- **Cómo lo implementamos:** 
  - Endpoint `GET /api/tts/voices` que lista las voces disponibles con un archivo MP3 de muestra pre-renderizado de 2 segundos.
  - En la UI: Una lista visual donde pulsas ▶️ Escuchar y seleccionas tu locutor preferido.

### 🎨 4. Selector Visual de Estilos de Subtítulos
- **Por qué importa:** Nuestro motor `typography.py` ya soporta subtítulos estilo Shorts con contraste dinámico y fuentes como Montserrat ExtraBold.
- **Cómo lo implementamos:** 
  - Crear 3 o 4 presets seleccionables en la UI:
    - *Estilo Hormozi* (Amarillo fosforescente + caja negra).
    - *Estilo MrBeast* (Texto blanco + borde grueso negro + resalto en verde).
    - *Estilo Minimalista* (Texto limpio blanco con sombra sutil).

### 🏷️ 5. Perfil de Canal / Marca (`Brand Profile`)
- **Por qué importa:** Evita tener que repetir tu nicho ("Curiosidades de Historia", "Emprendimiento", "Finanzas") en cada video.
- **Cómo lo implementamos:** 
  - Una tabla en SQLite (`brand_profiles`) con: nombre del canal, nicho, tono, voz default y estilo visual de subtítulo.

---

## 5. Próximo Paso Recomendado

De estas 5 brechas identificadas mediante ClonaKit, las dos que generan un impacto inmediato más brutal en la calidad de tus videos son:
1. **El Generador A/B de Hooks Virales (3 segundos de impacto).**
2. **La Galería de Voces con Preescucha (Audio Preview en el panel).**

¿Empezamos implementando el **Generador A/B de Hooks Virales** o la **Galería de Voces con Preescucha**?
