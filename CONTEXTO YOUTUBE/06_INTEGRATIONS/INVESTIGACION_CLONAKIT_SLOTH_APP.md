# Informe de Investigación ClonaKit: Sloth Video Creator (`v0.3.48`)

**Fecha:** 2026-11-04  
**Objetivo:** Análisis arquitectónico, funcional y técnico de la suite de creación de videos **Sloth** (`Sloth-Setup-0.3.48.exe`), instalada localmente en `%LOCALAPPDATA%\Programs\sloth`. Identificación de componentes, pipelines de Google Flow / Remotion / MCP y estrategias clave para incorporar en `YOUTUBE AUTOMATION`.  
**Metodología:** Análisis de sala limpia e ingeniería inversa asistida (ClonaKit / inspección de bundles Electron, Node.js y Skills).

---

## 1. ¿Qué es Sloth y cuál es su arquitectura?

**Sloth (`Sloth.exe`)** es un estudio de producción y generación autónoma de videos (formato vertical 9:16 para TikTok/Reels/Shorts y horizontal 16:9 para YouTube) que funciona mediante un arnés agéntico local.

### Puntos Clave de su Arquitectura:
- **Frontend / Runtime:** Electron + Node.js + Python 3.11/3.12 embebido en `%LOCALAPPDATA%\Programs\sloth`.
- **Motor de Video:** **Remotion** (React / TypeScript `.tsx`) integrado con **Three.js / React Three Fiber** para renderizado programático cuadro por cuadro y composición procedural.
- **Motor de Orquestación Agéntica:** Funciona con un modelo de **Skills** (idéntico al estándar `SKILL.md` de Antigravity) ubicadas en `resources/skills/`.
- **Conectividad LLM:** Viene configurado por defecto con **Claude Code** (`@anthropic-ai/claude-agent-sdk`), pero el código fuente en `app/server/index.mjs` revela que su capa de abstracción de proveedores (`shared/providers.ts`) soporta:
  ```javascript
  var PROVEEDORES = ["claude", "codex", "deepseek", "gemini", "grok", "antigravity", "cursor", "muse", "pi"];
  ```
- **Servidor Interno Local:** Levanta un servicio API local en `http://127.0.0.1:4848` con endpoints como `/api/flow/generar`, `/api/flow/trabajos/:id`, `/api/voz`, etc., comunicado por MCP (Model Context Protocol) vía stdio con el agente.

---

## 2. Lo Mejor de Sloth: Hallazgos Críticos para YOUTUBE AUTOMATION

Del análisis de su código, scripts y plantillas en `resources/skills/`, identificamos **6 gemas técnicas** de altísimo valor que podemos adoptar o adaptar directamente:

### 1. Rotación Multi-Cuenta y Control de Créditos en Google Flow (`FLOW.md` & `flow/mcp.mjs`)
Sloth resuelve con maestría el problema de cuotas de Google Flow / Veo:
- **Pool de Cuentas:** Permite enlazar múltiples cuentas de Google. El servidor monitorea los saldos de créditos de cada cuenta en tiempo real (`estado_flow`).
- **Failover Transparente:** Si la cuenta en uso agota sus 50 créditos diarios de Veo, el backend pasa el pedido automáticamente a la siguiente cuenta disponible sin interrumpir la generación ni cobrar al usuario.
- **Topes de Gasto:** Modos de generación tipados con costo explícito:
  - `Omni Flash`: 6 créditos (360p).
  - `Veo 3.1 - Lite`: 10 créditos (720p).
  - `Veo 3.1 - Fast`: 20 créditos.
  - `Veo 3.1 - Quality`: 100 créditos.

### 2. El Truco Maestro de Consistencia Visual en Veo (`primerCuadro`)
Para evitar que el personaje o la ropa cambien entre tomas generadas por IA:
1. Genera **gratis** una imagen estática con Nano Banana / ImageFX (`generar_imagen`) pasando hojas de personaje (`referencias`).
2. Al generar video en Veo (`generar_video`), **obliga a que el video empiece en esa imagen** mediante el parámetro `primerCuadro: "<ruta_imagen>"`.
3. Esto garantiza **100% de consistencia de modelo, rostro, ropa e iluminación** en cada clip de 8 segundos.

### 3. Formato 3D Continuo en una Sola Toma (`video-explicativo`)
En lugar de pegar clips sueltos con transiciones estándar:
- Crea un **único mundo 3D continuo** en Remotion + Three.js (`Mundo.tsx`, `Escena3D.tsx`, `camara.ts`, `encuadra.ts`).
- La cámara viaja por el mundo sin cortes de edición tradicionales: se acerca a datos, muestra gráficos animados (`Grafica.tsx`, `diagrama.tsx`), muestra citas de Reddit (`reddit.tsx`) o voltea objetos/monedas 3D (`modelos-3d`).
- Un sticker narrador recortado con `rembg` (con borde blanco) reacciona con bocas abiertas/cerradas y cambios de postura al compás de la narración.

### 4. Control de Calidad Visual por Hoja de Contacto (`hoja.mjs`)
- En lugar de reproducir o procesar videos pesados para evaluar si quedaron bien, Sloth ejecuta `hoja.mjs video.mp4 hoja.png --n 16 --zonas`.
- Genera una cuadrícula de 16 fotogramas clave con marcas de tiempo y el contorno de las **zonas seguras** (área donde la interfaz de TikTok/Shorts no tapa los subtítulos).
- Esto permite que un agente de IA revise visualmente un video entero con una sola lectura de imagen rápida y económica.

### 5. Normalización Estricta de Audio Broadcast (`masterizar.mjs`)
- Estandariza todo el audio a `-14 LUFS` y True Peak $\le -1.0 \text{ dBTP}$ a 48 kHz / 24 bits usando filtros avanzados de FFmpeg (`loudnorm` con limitador de sobremuestreo).
- Esto garantiza que las plataformas (YouTube, TikTok, Reels) no bajen el volumen ni distorsionen el sonido.

### 6. Persistencia de Modelos en GPU (`voz_viva.py` y `vectores_vivo.py`)
- Mantiene cargados en la VRAM de la GPU NVIDIA los modelos pesados de WhisperX y embeddings semánticos con un temporizador de inactividad (TTL) de 10 minutos.
- Evita tener que recargar 2-4 GB de pesos en memoria en cada ejecución: transcribir 6 minutos de voz tarda ~40 segundos en lugar de minutos de espera de arranque.

---

## 3. ¿Cómo Romper la Dependencia de Claude?

El usuario observó que Sloth *"se conecta con Claude"*. Efectivamente, Sloth viene preconfigurado con Claude Code como agente orquestador, pero **no estamos atados a Claude**:

1. **Sus Skills y Scripts son agnósticos:** Todo el valor real (plantillas Remotion, scripts de masterización, recorte con rembg, bibliotecas 3D y reglas de prompt de Google Flow) está escrito en **Node.js, TypeScript y Python puro**. No dependen de la API de Anthropic.
2. **Podemos orquestarlos con Gemini:** Dado que nuestro backend `YOUTUBE AUTOMATION` ya tiene integración directa con **Google Gemini 2.5/Flash** y **Google Flow MCP**, podemos invocar los mismos generadores y plantillas sin pagar suscripciones ni tokens de Claude.
3. **Reutilización directa:** Podemos importar los scripts más potentes (`hoja.mjs`, `masterizar.mjs`, `FLOW.md`, `recorte.py` y las bibliotecas 3D de `modelos-3d`) directamente a nuestra carpeta `backend/tools/` o `scripts/`.

---

## 4. Tabla Comparativa: YOUTUBE AUTOMATION vs. Sloth

| Capacidad | YOUTUBE AUTOMATION (Actual) | Sloth (v0.3.48) | Oportunidad de Integración |
|---|---|---|---|
| **Pipeline de Video** | FFmpeg puro (zoompan, concat, muxing, LatentSync) | Remotion (React `.tsx`) + Three.js + FFmpeg | Incorporar Remotion para animaciones 3D y motion graphics |
| **Integración Google Flow** | 1 sesión por CDP (Flow MCP) | Multi-cuenta con rotación automática y saldo de créditos | Implementar balanceador multi-cuenta en nuestro `mcp_manager` |
| **Consistencia en Video IA** | Prompt engineering + LatentSync v2v | `primerCuadro` en Veo partiendo de Nano Banana con referencias | Adoptar `primerCuadro` en nuestro pipeline de Flow |
| **Inspección de Video** | Reproducción en HTML5 (`/api/projects/{id}/video`) | Generador de hojas de contacto (`hoja.mjs`) con safe zones | Integrar generador de hojas de contacto para previsualizaciones instantáneas |
| **Audio** | Edge-TTS / Gemini TTS + Pacing gap compensation | Normalización estricta `-14 LUFS` y True Peak `-1 dBTP` | Incorporar el filtro de masterización de `masterizar.mjs` |

---

## 5. Recomendación de Próximos Pasos

1. **Fase 1 (Inmediata - 0 Costo):** Copiar los scripts de utilidad que no requieren dependencias complejas (`masterizar.mjs` para audio profesional y `hoja.mjs` para generación de miniaturas/hojas de contacto de escenas).
2. **Fase 2 (Google Flow Multi-Cuenta):** Adaptar en nuestro `backend/services/mcp_manager.py` la lógica de rotación de perfiles Google para que podamos conectar más de una cuenta y sumar créditos gratuitos diarios de Veo.
3. **Fase 3 (Técnica primerCuadro):** Modificar el generador de video de Flow para que primero genere el fotograma base y luego anime con Veo, asegurando consistencia absoluta sin desfigurar personajes.
