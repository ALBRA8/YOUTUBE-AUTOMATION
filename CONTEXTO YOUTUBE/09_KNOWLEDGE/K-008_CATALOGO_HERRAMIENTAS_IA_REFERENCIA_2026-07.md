# K-008 — CATÁLOGO DE HERRAMIENTAS DE IA (FUENTE EXTERNA, JULIO 2026)

**Fuente:** archivo aportado por el usuario, *Herramientas de Inteligencia Artificial*, versión 5.0, julio de 2026, Joaquín Barberá.  
**Tipo:** referencia exploratoria de herramientas y proveedores.  
**Estado:** REFERENCIA NO VERIFICADA — no es una auditoría de proveedores ni una especificación de YOUTUBE-AUTOMATION.  
**Fecha de incorporación al contexto:** 2026-10-22.

---

## 1. Propósito

Conservar este catálogo como mapa inicial de posibles herramientas para tareas de texto, investigación, imágenes, edición/composición, vídeo, música y voz. Puede servir para descubrir proveedores candidatos; no autoriza por sí mismo a integrar, sustituir o activar ninguna herramienta.

El documento original presenta información comercial y comparaciones según su autor y fecha. Sus afirmaciones sobre calidad, modelos utilizados, precios, límites gratuitos, disponibilidad y ausencia de censura **no se consideran verificadas** y pueden quedar desactualizadas.

## 2. Herramientas recogidas por categoría

### 2.1 Generación de texto e investigación
- **ChatGPT** — chat multimodal y generación de contenido: https://chatgpt.com/
- **Gemini** — chat multimodal: https://gemini.google.com/app
- **Claude** — texto, código y funciones agénticas según la fuente: https://claude.ai/
- **Copilot** — chat multimodal: https://copilot.microsoft.com/
- **Z AI / Z.ai** — chat, modo agente y presentaciones: https://chat.z.ai/
- **DeepSeek** — modelos de texto: https://www.deepseek.com/en/
- **Perplexity** — investigación y búsqueda de fuentes: https://www.perplexity.ai/
- **Jasper AI** — generación de contenido de marketing: https://www.jasper.ai/
- **Kimi** — texto, agentes, código y presentaciones: https://www.kimi.com/
- **Qwen** — texto, código y, según la fuente, capacidades multimodales: https://qwen.ai/

### 2.2 Generación de imágenes
- **Google Flow / modelos de imagen de Google:** https://labs.google/fx/tools/flow
- **Gemini:** https://gemini.google.com/app
- **Meta AI:** https://www.meta.ai/
- **ChatGPT:** https://chatgpt.com/
- **Qwen:** https://qwen.ai/
- **Midjourney:** https://www.midjourney.com/
- **Tensor.Art:** https://tensor.art/
- **SeaArt:** https://www.seaart.ai/es
- **Shakker AI:** https://www.shakker.ai/

### 2.3 Edición y composición de imágenes
La fuente destaca Google Flow, Gemini, ChatGPT y Qwen como opciones de edición/composición, especialmente con imágenes de referencia. Estas valoraciones son del autor del catálogo y no constituyen una comparación reproducida ni una prueba de ALBRA.

### 2.4 Generación de vídeo
- **Google Flow** — la fuente menciona Veo y Omni: https://labs.google/fx/tools/flow
- **Vibes AI (Meta)** — generación desde cero o a partir de imagen, según la fuente: https://vibes.ai/
- **Dreamina / CapCut** — la fuente la asocia con Seedance: https://dreamina.capcut.com/ai-tool/home
- **Kling:** https://kling.ai/es
- **Higgsfield** — agregador/plataforma de modelos de imagen y vídeo según la fuente: https://higgsfield.ai/

### 2.5 Generación de música
- **Suno:** https://suno.com/
- **Udio:** https://www.udio.com/
- **Tad AI:** https://tad.ai/es

**Nota de fidelidad:** el documento original contiene posibles errores editoriales en esta sección, incluida una URL de Udio que parece repetir la de Suno y una comparación de calidad redactada de forma inconsistente. Verificar los sitios oficiales antes de usar estos datos.

### 2.6 Generación de voz
- **Google AI Studio:** https://aistudio.google.com/apps
- **ElevenLabs:** https://elevenlabs.io/es

## 3. Lectura para YOUTUBE-AUTOMATION

Este catálogo es un **inventario de candidatos**, no una arquitectura recomendada. Para el proyecto:

1. Mantener Google Flow como proveedor/capacidad dentro del pipeline audiovisual ya existente, no como orquestador.
2. Considerar proveedores alternativos solo para una necesidad concreta —por ejemplo, imagen, vídeo, música, voz o investigación— y compararlos con pruebas reproducibles.
3. No integrar una herramienta solo porque el catálogo la describa como gratuita, ilimitada, superior o sin marca de agua.
4. Antes de seleccionar un proveedor, comprobar directamente sus capacidades actuales, términos, límites, coste, derechos de uso, acceso regional, API/MCP y condiciones de automatización.
5. Preferir una integración desacoplada que conserve el contrato de entrada/salida del pipeline y permita fallback controlado; no duplicar orquestadores ni introducir un agente nuevo por cada proveedor.
6. Para herramientas de generación visual, validar la salida real: formato, dimensiones, duración, calidad, consistencia de personaje, uso efectivo de referencias/Start Frame y compatibilidad con la postproducción.

## 4. Límites de evidencia

- El archivo es una guía de terceros fechada en julio de 2026.
- La inclusión de una herramienta solo demuestra que aparece en la fuente; no demuestra que ALBRA la haya evaluado, conectado o probado.
- Las descripciones de modelos subyacentes, comparativas de calidad, precios, cuotas gratuitas y afirmaciones como “sin censura” o “sin límites” requieren verificación independiente y actualizada.
- No se han realizado pruebas de estas herramientas como parte de la incorporación documental.
- Este registro no modifica el estado técnico de GoogleFlowMCP, los tests LIVE, el pipeline ni la decisión de arquitectura de YOUTUBE-AUTOMATION.

## 5. Regla de mantenimiento

Cuando una herramienta pase de candidata a opción evaluada, crear un registro separado con fecha, caso de uso, fuente oficial, coste/limitaciones verificadas, método de integración, prueba reproducible, resultados y decisión **ADOPT / HOLD / REJECT**. Mantener este catálogo como referencia histórica, sin convertir sus afirmaciones en hechos del proyecto.
