# INT-010 — GATE C.1: IMPLEMENTACIÓN MÍNIMA Y PRODUCCIÓN REAL DE VIDEO (MCP × PIPELINE BRIDGE)

**Fecha:** 2026-10-21  
**Estado:** PASS (VALIDACIÓN EN VIVO CONFIRMADA)  
**Alcance:** Capa MCP (`tools/GoogleFlowMCP`), cliente backend (`flow_mcp_client.py`), puente de pipeline (`backend/pipeline/images.py`) e importador (`flow_import.py`).

---

## 1. Resumen Ejecutivo

En el hito **Gate C.1**, se implementó la frontera técnica mínima entre el pipeline de **YOUTUBE-AUTOMATION** y la capacidad nativa de video en Google Flow demostrada en C.0. Se eliminó la brecha de integración sin crear nuevos agentes, sin sistemas paralelos y preservando intactos los contratos F5/F5.1 y de extensión existentes.

Flujo ejecutado de extremo a extremo:

```text
scene.image_path (scene_01.png)
        ↓
generate_scene_video() [backend/pipeline/images.py]
        ↓
flow_mcp_client.upload_file("crystal_orb_c1")
        ↓
flow_mcp_client.generate_video(start_frame="crystal_orb_c1")
        ↓
GoogleFlowMCP (herramienta 'flow_generate_video')
        ↓
CDP :9333 → Google Flow (Video → Fotogramas → Start Frame)
        ↓
Síntesis de video en Google Flow (Omni 1.1 Flash)
        ↓
Descarga directa del stream MP4
        ↓
output/_live_video_test_02/flow/Escena_01_video.mp4
        ↓
flow_import.find_flow_videos() → Detección nativa exitosa
```

---

## 2. Evidencia Técnica Registrada (LIVE TEST C.1)

| Parámetro | Valor Registrado |
| :--- | :--- |
| **Proyecto** | `_live_video_test_02` |
| **Escena** | `01` |
| **Start Frame origen** | `backend/data/output/_live_mcp_test_01/scene_01.png` |
| **Tamaño Start Frame** | 963,905 bytes |
| **Nombre de Activo Flow** | `crystal_orb_c1` |
| **Media ID del Activo** | `065e800a-9509-4da8-a638-e06fe00c021a` |
| **Selección en UI Flow** | `Video → Fotogramas` → Slot `Iniciar` asociado a `crystal_orb_c1` |
| **Media ID del Video Generado** | `6e70d09a-1753-4468-b0c0-c6f010c80537` |
| **Ruta del Archivo Generado** | `backend/data/output/_live_video_test_02/flow/Escena_01_video.mp4` |
| **Tamaño del Video** | `3,159,358 bytes` (3.16 MB) |
| **Duración** | `8.00 s` (192 frames) |
| **Resolución** | `720x1280` (9:16 vertical portrait) |
| **Codec de Video** | H.264 / AVC High Profile, nivel 31 |
| **Codec de Audio** | AAC estéreo 48 kHz (audio ambiental de Flow) |
| **Framerate** | 24 fps progresivo |
| **Consumo en Pipeline** | `flow_import.find_flow_videos()` devolvió `{0: Path(.../Escena_01_video.mp4)}` |
| **Estado del Lock** | `.flow.lock` liberado (`clean = True`) |

---

## 3. Cambios Implementados

1. **`tools/GoogleFlowMCP/src/flow.js`**:
   - `generateVideo({ prompt, startFrame, aspect, outDir, outFile, timeoutMs })`: Automatiza navegación al proyecto, activación del modo `Video`, submodo `Fotogramas`, asociación del Start Frame en el slot `Iniciar`, inyección del prompt, envío y descarga.
   - Robustecimiento de `openPicker` para contemplar menú de herramientas multimedia (`div.tools-button-group`, `.cdk-overlay-container`).
   - `inProject()`: Blindaje de navegación evitando quedar retenido en rutas `/edit/...`.
   - `tiles()`: Lectura precisa de títulos mediante `textContent`.
2. **`tools/GoogleFlowMCP/src/mcp.js`**:
   - Registro de la herramienta MCP `flow_generate_video` con validación Zod.
3. **`backend/services/flow_mcp_client.py`**:
   - `verify_video_file()`: Verificación binaria de contenedores de video.
   - `parse_video_paths_from_text()`: Extracción determinista de rutas devueltas por MCP.
   - `generate_video()`: Método asíncrono para llamada a `flow_generate_video`.
4. **`backend/pipeline/images.py`**:
   - `generate_scene_video()`: Puente mínimo entre escenas del pipeline y Google Flow MCP, depositando el archivo directamente en `flow/Escena_{idx+1:02d}_video.mp4`.
5. **Baterías de Tests**:
   - `tests/test_flow_mcp_video.py`: 6 tests unitarios herméticos de validación, parsing y bridge.
   - `tests/test_live_execution_c1.py`: Suite de ejecución en vivo y validación con `ffprobe`.

---

## 4. Pruebas de Regresión

- Suite unitaria Node: `3/3 PASS` (`npm test` en `tools/GoogleFlowMCP`).
- Suite unitaria Python: `49/49 PASS` (`test_flow_mcp_video.py`, `test_scene_asset_resolver.py`, `test_flow_mcp_bridge.py`).
- Cero regresiones en la generación de imágenes, F5/F5.1 y contratos existentes.
