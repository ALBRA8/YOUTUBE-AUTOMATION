# INT-011 — GATE C.2: FLOW VIDEO ↔ PRODUCTION ORCHESTRATOR

**Fecha:** 2026-10-21  
**Estado:** PASS — LIVE END-TO-END VALIDATION REPORTADA  
**Alcance:** `backend/config.py`, `backend/pipeline/orchestrator.py`, `backend/pipeline/images.py`, `backend/pipeline/asset_resolver.py`, `backend/services/flow_mcp_client.py`, `tools/GoogleFlowMCP/src/flow.js`, tests y documentación de integración.

---

## 1. Resumen Ejecutivo

Gate C.2 conecta la capacidad de generación de video validada en C.1 con el flujo normal de producción de YOUTUBE-AUTOMATION.

La integración se realizó sin crear un nuevo agente, orquestador, estudio de producción o sistema QA. El orquestador existente conserva el montaje, muxing, subtitulado y fallback Ken Burns.

Flujo validado:

```text
producción normal / orchestrator._run()
        ↓
feature flag FLOW_MCP_VIDEO_ENABLED o project.meta.flow_video
        ↓
flow_mcp_client.available()
        ↓
flow_import.find_flow_videos() → reutilización de clips existentes
        ↓
images.generate_scene_video() → escenas pendientes
        ↓
GoogleFlowMCP → Google Flow → MP4
        ↓
output/<project_id>/flow/Escena_XX_video.mp4
        ↓
flow_import.find_flow_videos()
        ↓
video.render_scenes(flow_videos=...)
        ↓
video final
```

---

## 2. Cambios de Integración

### Configuración

Se incorporó:

- `FLOW_MCP_VIDEO_ENABLED`, por defecto `False`.
- `FLOW_MCP_VIDEO_TIMEOUT`, valor reportado `900.0`.
- soporte de recarga mediante `config.reload()`.

La generación de video de Flow permanece **opt-in**; no se activa por defecto en producción.

### Orquestador

En `backend/pipeline/orchestrator.py` se añadió el paso opcional de generación de video:

- comprueba el feature flag o `project.meta.get("flow_video")`;
- comprueba disponibilidad de Flow MCP;
- detecta clips existentes mediante `flow_import.find_flow_videos()`;
- reutiliza clips existentes para evitar regeneración y consumo innecesario;
- genera únicamente escenas pendientes mediante `images.generate_scene_video()`;
- maneja fallos por escena sin cancelar el job completo;
- degrada la escena afectada a Ken Burns;
- entrega los clips reales a `video.render_scenes()`.

### Robustez

También se reportaron ajustes en:

- `flow_mcp_client.upload_file()`: timeout por defecto ampliado a 120 s.
- `images.generate_scene_video()`: propagación de timeout de subida y sanitización del nombre del activo mediante `asset_resolver.sanitize_asset_name()`.
- `tools/GoogleFlowMCP/src/flow.js`: detección/descarga binaria del video mediante interceptación del stream MP4 de Flow.

---

## 3. LIVE TEST C.2

Proyecto aislado:

`live_c2_test_01`

Escenas: `01` y `02`.

Evidencia reportada:

- Start Frame escena 01: `scene_01.png`, 963,905 bytes.
- Start Frame escena 02: `scene_02.png`, 890,967 bytes.
- Escena 01: clip Flow preexistente instalado deliberadamente para probar idempotencia.
- Escena 02: clip generado realmente durante el LIVE TEST.
- Job: `7d10b8f78d2c`.
- Estado final del proyecto: `ready`.
- Progreso: 100%.

### Clip reutilizado

`Escena_01_video.mp4`

- 1,911,579 bytes.
- 8.01 s.
- Reutilizado sin nueva llamada a Flow.

### Clip generado en vivo

`Escena_02_video.mp4`

- 3,238,415 bytes.
- 8.00 s.
- Generado realmente mediante Google Flow.

### Descubrimiento

`flow_import.find_flow_videos()` detectó correctamente los dos clips.

### Ensamblaje final

Ruta reportada:

`backend/data/output/live_c2_test_01/live_c2_test_01_final.mp4`

- Tamaño: 7,839,948 bytes (7.84 MB).
- Streams: video + audio.
- Duración reportada: 3.43 s.
- Artifact: `live_video_c2_final.mp4`.

El pipeline alcanzó estado `ready` y produjo el artefacto final.

**Observación no bloqueante:** la duración final reportada (3.43 s) es inferior a la duración individual de los dos clips (~8 s cada uno). Esto no invalida C.2 como prueba de wiring y consumo de clips, pero debe revisarse antes de declarar resuelta la política de duración temporal de una producción audiovisual real.

### Limpieza

- `.flow.lock`: liberado.
- `Lock on disk: False`.

---

## 4. TESTS

Suite reportada para `tests/test_flow_mcp_video.py`:

- Video deshabilitado → fallback Ken Burns: PASS.
- Video habilitado → generación y entrega de clips al ensamblador: PASS.
- Idempotencia → reutilización de clips existentes: PASS.
- Fallo de Flow → degradación elegante y job exitoso: PASS.

Resultado reportado:

**32 tests — PASS — 7.449 s**

El LIVE TEST C.2 también reportó PASS.

---

## 5. FRONTERAS ARQUITECTÓNICAS PRESERVADAS

- F5/F5.1 permanece fuera del alcance y sin modificaciones.
- GoogleFlowMCP sigue siendo un puente técnico, no un agente.
- YOUTUBE-AUTOMATION conserva la responsabilidad de orquestación audiovisual.
- El montaje existente continúa siendo responsable de ensamblar los clips.
- Ken Burns permanece como fallback cuando Flow está desactivado o falla.
- No se creó un nuevo Video Editor Agent.
- No se creó un nuevo Production Studio.
- No se creó un nuevo orquestador.

---

## 6. ESTADO DE GIT AL CIERRE DEL GATE

En el informe de Antigravity previo al cierre:

- No se había ejecutado commit.
- No se había ejecutado push.
- `git diff --check`: limpio.
- Working tree contenía únicamente cambios asociados a C.2 y su documentación.

La publicación de C.2 queda condicionada a la autorización y revisión final del diff. El commit/push debe registrarse como cierre posterior al presente informe si efectivamente se ejecuta.

---

## 7. DICTAMEN

**GATE C.2: PASS — integración funcional demostrada.**

La evidencia reportada demuestra que el orquestador normal puede:

1. reconocer la capacidad Flow Video;
2. reutilizar clips existentes de forma idempotente;
3. generar clips pendientes mediante Google Flow;
4. descubrir los clips mediante `flow_import`;
5. entregarlos al ensamblador existente;
6. completar el pipeline hasta `ready`;
7. producir un video final con audio/video;
8. degradar escenas individuales a Ken Burns ante fallos.

**Siguiente punto de atención:** duración/retiming del ensamblaje final antes de declarar producción audiovisual completa como cerrada.
