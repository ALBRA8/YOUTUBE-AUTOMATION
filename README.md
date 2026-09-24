# 🎬 YOUTUBE AUTOMATION v2.0

**Fábrica local de videos con IA — estilo Labsia, pero a costo $0 y con modo fábrica.**

Pipeline completo: **guion (Gemini 2.5) → imágenes (Gemini 2.5 Flash Image) → locución (TTS dual) → render Ken Burns (ffmpeg) → subtítulos Hormozi/TikTok → música con ducking → (opcional) autopublicar en YouTube.**

| | Labsia.es | **YT Automation v2.0** |
|---|---|---|
| Coste | €14.99–49.99/mes con créditos | **$0.00** (Gemini free + edge-tts) |
| Modo fábrica (3+/día solo) | ❌ | ✅ **cron con horarios + cola de ideas** |
| Autopublish YouTube | ❌ | ✅ OAuth + programación |
| Modo "Desde URL" (recrear virales) | ✅ (gasta créditos) | ✅ **gratis** (yt-dlp + Whisper + Gemini) |
| Imágenes | Fal.ai (créditos) | Gemini 2.5 Flash Image + **extensión Chrome Plan B** |
| Límite | créditos mensuales | cuota diaria de Gemini (~500 imgs/día) |
| Datos | en su nube | **100% local** (SQLite + archivos) |

---

## ⚡ Inicio rápido (5 minutos)

### 1. Requisitos
- **Python 3.10+** ([python.org](https://python.org)) — en Windows marca "Add to PATH"
- **FFmpeg** instalado y en el PATH:
  - Windows: `winget install Gyan.FFmpeg` (o descarga de ffmpeg.org)
  - Mac: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

### 2. Arrancar
```bash
# Windows: doble clic en start.bat
# Linux/Mac:
chmod +x start.sh && ./start.sh
```
O manual:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```
Abre **http://127.0.0.1:8000** 🎉

### 3. Claves (opcional pero recomendado) — **directo desde el dashboard**
**Ya no hace falta editar archivos a mano**: entra en **⚙️ Configuración** en el menú lateral y:
1. Pega tu **GEMINI_API_KEY** (gratis en [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
2. **💾 Guardar clave** → se escribe en `backend/.env` y **se activa al instante, sin reiniciar**
3. **🔌 Probar clave** → verifica con una llamada real que todo funciona

También desde ahí: elegir voz y proveedor TTS, subir el `client_secret.json` de YouTube, elegir modelo Whisper y FPS.

> ¿Prefieres el archivo? `cd backend && cp .env.example .env` y edita `GEMINI_API_KEY=...`. Sin clave: el dashboard funciona, pero los videos salen con imágenes placeholder y solo voz edge-tts. Con clave: calidad completa a $0.

### 4. (Recomendado) Whisper para subtítulos perfectos
```bash
pip install faster-whisper
```
Sin Whisper, los tiempos de subtítulo se estiman (funciona bien, pero el exacto es mejor).

---

## 🧭 El flujo en el dashboard

### 🤖 Agente VÓRTICE (nuevo en v2.1) — habla con tu fábrica
Chat conversacional que ejecuta acciones reales del motor:
- «**crea un video sobre el imperio romano**» → produce el video completo y abre el progreso
- «**muéstrame mis proyectos**» → lista clicable con el estado de cada uno
- «**¿cómo va el video de las bermudas?**» → estado y avance
- «**crea un video de misterios con Sofía Explora**» → vincula tu avatar/personaje automáticamente

Funciona con Gemini (respuestas redactadas por IA) o sin clave (detección de intención local, coste $0). Nunca se rompe.

### 🎭 Avatares PRO (v2.1.1) — personajes consistentes con menús desplegables
Crea un personaje completo con **15 menús desplegables** (89 opciones): género, edad aparente, tono de piel, color y forma de ojos, cabello (color/largo/textura), tipo de cuerpo, estilo de ropa, maquillaje, arquetipo (12: Rebelde, Seductora, Exploradora, Sabio Mentor…), personalidad, acento al hablar (costeño, bogotano, paisa, mexicano…) y jerga regional — más texto libre para accesorios, referencia de influencer y otros detalles.
Al usarlo en un video:
- Cada característica se **traduce a inglés y se inyecta en los prompts reales** (ver el botón 📄 Prompt del avatar: retrato + consistencia de escenas + persona del guion)
- La **apariencia** acompaña a TODAS las escenas para mantener el mismo personaje
- El **arquetipo/acento/jerga** moldean narración y tono del guion
- Al elegir el **acento** se sugiere automáticamente una voz edge-tts acorde (10 voces es-*)
- Su **voz y estilo visual** se usan por defecto en cada video
- Retrato del avatar: IA de Gemini o generación local $0

### Crear (wizard de 4 pasos, como Labsia y mejorado)
1. **Modo** — 📜 Guion · 💡 Idea · 🔗 **URL** · 🎙️ Audio
2. **Formato** — Short 9:16 (1080×1920) o Largo 16:9 (1920×1080)
3. **Estilo** — 25 estilos (los 20 de Labsia + 5 exclusivos v2: MRI Brainrot, Claymation, Barroqueremax, Holo-Ghost, Papercraft) + Custom Studio
4. **Detalles** — tu entrada, avatar opcional, plataformas destino (▶️ YouTube · 🎵 TikTok · 📷 Instagram · 👤 Facebook), voz, título → **🚀 Crear**

Veras el progreso en vivo por pasos (guion → imágenes → locución → render → subtítulos). Al terminar, el editor de escenas se abre solo.

### Editor de escenas
- Arrastra ⠿ para **reordenar**
- Edita narración y prompt de cada escena
- Clic en la imagen para **regenerarla**
- 🔊 escucha la locución de cada escena
- Descarga MP4 y SRT

### 🏭 Fábrica (la ventaja propia)
1. Activa la **producción automática**
2. Define horarios (`07:00,12:30,19:00`), nicho, estilo y formato
3. Alimenta la **cola de ideas** (o deja que la IA invente del nicho)
4. Opcional: **autopublicar** cada video (privado, para revisar antes)
5. `⚡ Producir uno ahora` para probar sin esperar el cron

### 📺 Publicar en YouTube
Ver §Configurar YouTube abajo. El video se sube con OAuth de tu propio canal; puedes programar fecha/hora.
Si elegiste TikTok/Instagram/Facebook en el wizard, el editor muestra el **kit multi-plataforma**: descargas el MP4 9:16 y lo subes en cada red (la API de TikTok requiere aprobación externa; no fingimos botones que no funcionan).

---

## 🔗 Modo "Desde URL" — recrear virales (killer feature)
1. Pega el enlace del video viral de TikTok/YouTube
2. `yt-dlp` descarga solo el audio → Whisper lo transcribe
3. Gemini analiza la **estructura ganadora** (hook → tensión → giro → CTA)
4. Genera un guion **100% original** con el mismo ángulo probado (nunca copia frases)

> ⚠️ Úsalo como inspiración de estructura. El contenido resultante es original; revisa siempre antes de publicar.

## 🎙️ Modo "Desde Audio" — tu voz
Sube tu grabación (mp3/wav/m4a): se transcribe con Whisper, Gemini la divide en escenas respetando TUS frases, y se produce el video con tu voz real grabada en la pista.

## 🧩 Extensión Chrome — "Flow Script Processor" (IMAGENES FLOW_EXT)
Réplica 1:1 de tu extensión real (manual EXTENSION TOUTUBE), reescrita en JS puro: **sin npm ni build**. Automatiza Flow/ImageFX con la arquitectura de 4 mundos:

1. `chrome://extensions` → modo desarrollador → "Cargar descomprimida" → carpeta `extension/`
2. Abre **Flow (labs.google/fx)** y el icono de la extensión
3. **Vincular Proyecto** → carpeta del proyecto (autodetecta `out/ideas/idea_NNNNNN/script.json` con el número MÁS ALTO) o plan B **Subir JSON**
4. Elige Tipo de Contenido (Imágenes PNG / Videos MP4-WebM) e imágenes por escena (1/2/4/6)
5. **Iniciar Generación**: mecanografía humana en el editor Slate, intercepta tRPC/NDJSON (fetch+XHR en MAIN world), sondeo DOM cada 3s (`[data-tile-id]`), cooldown 90s ante "too quickly", salta escenas bloqueadas por políticas con botón **Reintentar**
6. Escribe DIRECTO en disco: `Escena_01/imagen_1.png`, `Escena_01/video_1.mp4` (FileSystemDirectoryHandle en IndexedDB; fallback a `Descargas/<PROYECTO>/Escena_XX/`)
7. Resiliencia MV3: cola persistida en `chrome.storage.session` + keepalive por alarmas — sobrevive a la suspensión del Service Worker

El **botón "Exportar a Flow"** del dashboard genera un ZIP con `script.json` bajo `out/ideas/idea_NNNNNN/` justo en el formato que esta extensión autodetecta. Detalles de operación y fallos: `extension/README.txt`.

---

## 📺 Configurar YouTube (autopublish)
1. En [Google Cloud Console](https://console.cloud.google.com) crea un proyecto → habilita **YouTube Data API v3**
2. Crea credenciales **OAuth 2.0 → Aplicación de escritorio** → descarga `client_secret.json`
3. Súbelo desde **⚙️ Configuración → YouTube** (o cópialo a `backend/data/client_secret.json`)
4. En el dashboard: **Publicar → 1. Conectar mi canal** → autoriza → pega el código → **Guardar token**
5. Listo: publica manual o activa autopublish en la Fábrica

> Nota: apps sin "verificación" de Google solo pueden subir videos como **privados** — perfecto para revisión y programación.

## 🗂️ Estructura del proyecto
```
yt_automation_v2/
├── backend/
│   ├── main.py               # FastAPI: API + SSE + dashboard
│   ├── config.py             # .env, rutas, modelos, voces
│   ├── database.py           # SQLite (projects/scenes/jobs/ext_images)
│   ├── pipeline/
│   │   ├── orchestrator.py   # motor: 5 pasos + SSE + cancelación
│   │   ├── script_gen.py     # 1. guion (4 modos)
│   │   ├── images.py         # 2. imágenes híbridas (Gemini→extensión→PIL)
│   │   ├── tts_step.py       # 3. TTS dual + alineación Whisper
│   │   ├── video.py          # 4. Ken Burns + mux + ducking
│   │   └── subtitles.py      # 5. ASS Hormozi/TikTok/karaoke
│   ├── services/
│   │   ├── gemini_client.py  # texto/imagen/TTS con reintentos
│   │   ├── tts_service.py    # Gemini TTS + edge-tts (fallback mutuo)
│   │   ├── whisper_service.py# timestamps por palabra
│   │   ├── url_mode.py       # yt-dlp + transcripción
│   │   ├── youtube_publish.py# OAuth + upload + programar
│   │   ├── scheduler.py      # modo fábrica (APScheduler)
│   │   └── themes.py         # 25 estilos visuales
│   ├── static/               # dashboard v2 (HTML/CSS/JS sin build)
│   └── data/                 # DB, videos, audios, thumbs (gitignored)
├── extension/                # Chrome MV3: puente ImageFX
├── start.sh / start.bat
└── README.md
```

## 💡 Voces disponibles
- **edge-tts (gratis ilimitado)**: Salomé 🇨🇴, Elvira 🇪🇸, Jorge 🇲🇽, Alonso 🇺🇸, Elena 🇦🇷 (+ cualquier id de edge-tts)
- **Gemini TTS (con key)**: Fenrir (épico), Puck (energético), Kore (cálida), Charon (documental), Aoede (juvenil)
- El sistema **cae automáticamente** al otro proveedor si uno falla.

## 🛠️ Solución de problemas

| Problema | Solución |
|---|---|
| `ffmpeg: command not found` | Instala FFmpeg y reinicia la terminal (`winget install Gyan.FFmpeg`) |
| Gemini: `429 RESOURCE_EXHAUSTED` | Cuota diaria → espera o activa la extensión ImageFX (Plan B automático) |
| Subtítulos desincronizados | Instala `faster-whisper` (tiempos exactos por palabra) |
| El video tarda mucho | Normal: ~1-3 min para un Short. Sube `FPS` menos o usa preset `veryfast` |
| No puedo subir a YouTube | Revisa `client_secret.json` y que YouTube Data API v3 esté habilitada |
| La extensión no ve el backend | ¿Está el servidor corriendo en 127.0.0.1:8000? Recarga la extensión |
| Puerto 8000 ocupado | Cambia `PORT` en `.env` |

## 🎯 Diferencias v1.0 → v2.0
- ✅ Reemplazada la automatización frágil de la extensión como fuente **primaria** → ahora es **Plan B**; Gemini 2.5 Flash Image es el primario
- ✅ TTS dual con fallback mutuo (antes solo edge-tts)
- ✅ Wizard 4 pasos + editor de escenas visual (antes: CSV)
- ✅ Modo URL viral y modo Audio (nuevos)
- ✅ Modo fábrica con cron + cola de ideas (nuevo)
- ✅ Autopublish YouTube con programación (nuevo)
- ✅ SQLite en vez de CSV: proyectos, escenas, jobs, KPIs
- ✅ Subtítulos estilo Hormozi con pop animado (ASS) + SRT descargable

## ⚖️ Nota legal
Genera contenido **original**. El modo URL analiza estructuras (no copia texto). Respeta los derechos de autor de música: coloca tus pistas libres (`.mp3`) en `backend/data/music/` y se mezclarán con ducking automático.
