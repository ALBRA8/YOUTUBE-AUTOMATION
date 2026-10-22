# INT-018 — Evaluación externa: lcy362/agnes-video-generator

> **Nota de numeración (2026-10-23):** este documento se renumera de
> INT-017 a INT-018 porque el número INT-017 ya estaba ocupado en `main`
> por `INT-017_P3B_EJECUCION_QUIRURGICA.md`. Contenido intacto.

- **Fecha de evaluación:** 2026-10-22
- **Repositorio analizado:** https://github.com/lcy362/agnes-video-generator
- **Rama observada:** master
- **Tipo de revisión:** análisis documental y revisión selectiva de código fuente público.
- **Estado:** EVALUACIÓN INICIAL COMPLETADA — CANDIDATO DE REFERENCIA; NO INTEGRAR DIRECTAMENTE.
- **Alcance importante:** no se clonó ni ejecutó el proyecto en un entorno local; no se ejecutaron sus tests ni se verificó generación real. Los hallazgos describen código/documentación consultados, no certificación de producción.

## 1. Dictamen ejecutivo

El repositorio aporta ideas aprovechables para YOUTUBE-AUTOMATION, especialmente en:
1. recuperación de tareas y escenas con checkpoint;
2. separación de pipelines y registro de artefactos intermedios;
3. estrategias de continuidad visual entre escenas;
4. pruebas de sincronización de audio/subtítulos y validación del producto final;
5. guías operativas de agente separadas para uso, diagnóstico y contribución.

**Recomendación:** conservarlo como referencia de diseño y realizar, si procede, una comparación focalizada con el código ALBRA existente. No importar el proyecto completo, no crear un nuevo agente audiovisual y no sustituir el orquestador, Production JSON, GoogleFlowMCP, sistema de jobs/leases/retries ni ensamblador de ALBRA.

## 2. Qué es el proyecto

Según su README y documentación pública, Agnes Video Generator es una aplicación local con interfaz web y backend FastAPI que ofrece varios modos: vídeo simple, vídeo creativo de varias escenas, vídeo desde manuscrito, ancla digital, poesía y generación de imágenes. La cadena creativa puede incluir planificación de historia/guion, imágenes de referencia, clips por escena, TTS, subtítulos y composición final.

La arquitectura documentada incluye:
- `server.py` y routers REST en `web/routes/`;
- modelos de tareas en `models/task.py`;
- estado/checkpoints en `core/task_manager.py`;
- pipelines en `core/pipelines/`;
- APIs de proveedores en `core/api/`;
- TTS/subtítulos en `core/audio/`;
- composición en `core/compositor/`;
- regresión y documentación de operación.

Fuentes:
- README: https://github.com/lcy362/agnes-video-generator
- Arquitectura: https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/architecture.md
- Guía de agentes: https://github.com/lcy362/agnes-video-generator/blob/master/AGENTS.md
- Plan de regresión: https://github.com/lcy362/agnes-video-generator/blob/master/docs/dev/regression_test_plan.md
- Productos de pipeline: https://github.com/lcy362/agnes-video-generator/blob/master/docs/dev/pipeline_products.md

## 3. Ideas con posible valor para ALBRA

### 3.1 Recuperación/checkpoints por artefacto — PRIORIDAD ALTA PARA COMPARAR

El proyecto persiste el estado de tareas en archivos `task_state.json`, usa estados tipados y documenta la reanudación después de interrupciones. Su documentación de regresión contempla aislar un fallo de segmento y reanudar solo el segmento fallido, evitando repetir los segmentos correctos.

**Uso posible:** comparar su modelo de checkpoints y productos por etapa con el sistema ALBRA existente de jobs, leases, heartbeat, retries y assets. Extraer criterios de diseño y pruebas; no crear un segundo task manager ni duplicar la cola.

### 3.2 Separación de pipeline y productos intermedios — PRIORIDAD ALTA PARA COMPARAR

La documentación distingue productos como historia, script de escenas, prompts de fotograma final, vídeos por escena, narración, SRT y vídeo final. Sus pipelines de varias escenas comparten una clase base con pasos comunes y puntos de extensión.

**Uso posible:** comprobar si nuestro contrato Production JSON y el registro de assets representan explícitamente todos los productos/dependencias necesarios para reanudar y auditar cada etapa. Adoptar solo mejoras demostradas y compatibles con la arquitectura existente.

### 3.3 Estrategias de continuidad visual — PRIORIDAD ALTA COMO REFERENCIA

La documentación describe tres modos: keyframes con fotograma inicial/final, transición entre escenas usando fotogramas intermedios, y escenas independientes con referencia compartida.

**Uso posible:** usar esta taxonomía al evaluar continuidad y lineage de referencias/Start Frames. Los nombres y parámetros de Agnes no son contrato de Google Flow y no deben trasladarse literalmente a ALBRA.

### 3.4 Recuperación de sincronización de subtítulos — PRIORIDAD MEDIA

El documento de productos del pipeline explica cómo recuperar cues temporales de TTS cuando se reanuda una tarea cuyo archivo de audio ya existe, para no degradar la sincronización de subtítulos a una estimación heurística.

**Uso posible:** estudiar el patrón y sus tests como referencia para audio/subtítulos. No se ha demostrado que este patrón solucione el timeout de FFmpeg de ALBRA; ese incidente permanece separado en INT-012.

### 3.5 Pruebas basadas en artefactos finales — PRIORIDAD ALTA

El plan de regresión enumera validaciones de existencia y tamaño del MP4, duración, resolución real del contenedor, pista de audio, contenido hablado y visibilidad/coincidencia de subtítulos. Distingue comprobaciones automáticas de revisión visual manual.

**Uso posible:** comparar la matriz de pruebas de ALBRA para detectar huecos. Deben adaptarse a nuestros proveedores, contratos y criterios; no asumir que las pruebas de Agnes prueban nuestro E2E.

### 3.6 Skills operativas separadas — PRIORIDAD MEDIA

El README describe tres conjuntos de skills: uso, diagnóstico y contribución. Las instrucciones orientan al agente para instalar/arrancar el servicio, revisar una tarea fallida y trabajar en cambios de código.

**Uso posible:** como referencia de documentación y límites de responsabilidad de agentes ALBRA. No justifica adoptar su gestor de skills ni crear otra capa de agentes.

## 4. Qué no debemos importar ni confundir

- **No reemplazar YOUTUBE-AUTOMATION:** Agnes es una aplicación generadora de vídeo de extremo a extremo con sus propios contratos, UI, modelos y backend; ALBRA ya tiene su orquestador y Production JSON.
- **No sustituir GoogleFlowMCP:** Agnes está orientado a las APIs/modelos de Agnes AI. Su soporte de keyframes o referencias no prueba compatibilidad con Google Flow.
- **No añadir otro orquestador o agente:** las ideas se pueden estudiar dentro de YOUTUBE-AUTOMATION; no justifican un VIDEO EDITOR AGENT.
- **No duplicar colas/checkpoints:** comparar con jobs, leases, heartbeats, retries y asset lineage existentes antes de proponer cambios.
- **No asumir que “gratis” significa contrato estable:** los claims de precio, límites y disponibilidad de modelos son del proveedor/proyecto y pueden cambiar.
- **No asumir producción verificada:** esta evaluación no instaló ni ejecutó el repositorio, no auditó exhaustivamente todos los archivos ni reprodujo sus tests.

## 5. Licencia y reutilización

El archivo `LICENSE` consultado declara MIT License, copyright 2026 lcy362. En principio permite reutilización y modificación sujeta a sus condiciones, incluida la conservación del aviso de copyright y licencia en copias o porciones sustanciales. Antes de copiar código, verificar la licencia en el commit concreto, conservar avisos requeridos y revisar dependencias/licencias de terceros. La recomendación actual es adoptar ideas y patrones primero, no copiar código.

Licencia consultada: https://github.com/lcy362/agnes-video-generator/blob/master/LICENSE

## 6. Próxima acción recomendada

No iniciar integración ni modificación de código ahora. Si se decide profundizar, encargar al Constructor una comparación dirigida y basada en código entre:
1. checkpoints/recuperación de Agnes y el sistema actual de jobs/leases/retries de YOUTUBE-AUTOMATION;
2. registro de artefactos de Agnes y nuestro asset lineage/Production JSON;
3. matriz de regresión de artefactos finales y pruebas actuales de ALBRA;
4. recuperación de cues de subtítulos y nuestra implementación actual.

La salida debe ser una tabla de **ya existe / gap real / idea adaptable / coste-riesgo / tests necesarios**, con referencias archivo:línea de ambos repositorios. No implementar automáticamente los gaps detectados.

## 7. Decisión registrada

**DECISIÓN:** Agnes Video Generator es una **referencia externa útil para análisis selectivo**, no una dependencia ni una pieza que se incorpore directamente. Priorizar comparación de recuperación/checkpoints, artefactos por etapa, continuidad visual y regresión de producto final. Preservar arquitectura y ownership actuales de ALBRA.
