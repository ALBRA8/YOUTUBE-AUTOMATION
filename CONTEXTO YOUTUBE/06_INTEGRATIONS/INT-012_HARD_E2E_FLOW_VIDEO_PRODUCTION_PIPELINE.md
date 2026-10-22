# INT-012 — HARD E2E: FLOW VIDEO → PRODUCCIÓN COMPLETA

**Fecha:** 2026-10-22  
**Estado:** FAIL — integración Flow E2E funcional; fallo en render final por timeout de FFmpeg  
**Proyecto:** `_hard_e2e_c2_01`  
**Alcance:** prueba dura E2E de múltiples escenas desde el orquestador hasta el MP4 final.

---

## 1. Objetivo

Ejecutar una prueba dura, no incremental, de la cadena:

```text
Production JSON
  ↓
YOUTUBE-AUTOMATION orchestrator
  ↓
Scene Asset Resolver
  ↓
Start Frames + referencias
  ↓
GoogleFlowMCP
  ↓
Google Flow
  ↓
4 clips MP4 reales
  ↓
flow_import
  ↓
ensamblado + audio
  ↓
subtítulos Hormozi
  ↓
MP4 final
```

El criterio buscaba validar la integración completa con cuatro escenas independientes y detectar el primer punto real de fallo.

---

## 2. Resultado Ejecutivo

La prueba demostró que la integración Google Flow no es el punto débil de esta ejecución.

**4/4 escenas fueron generadas realmente en Google Flow mediante MCP**, usando Start Frames independientes y referencias independientes. Los cuatro MP4 fueron descargados, validados e ingeridos por el pipeline.

El ensamblado y la mezcla de audio también completaron correctamente.

El fallo ocurrió posteriormente, durante el **quemado final de subtítulos dinámicos Hormozi**, cuando FFmpeg superó el timeout rígido de 900 segundos.

Por tanto:

> **GoogleFlowMCP + Google Flow + Start Frame + referencias + descarga + import + ensamblado: PASS en esta prueba.**
>
> **Render final con subtítulos: FAIL por timeout de FFmpeg.**

La prueba global queda **FAIL**, pero el primer fallo está claramente localizado fuera del puente Flow.

---

## 3. Evidencia por Escena

### Escena 01

- Start Frame: `backend/data/output/_hard_e2e_c2_01/scene_01.png`
- Start Frame: 963,905 bytes
- Referencia: `crystal_orb`
- Referencia local: `references/ref_asset_01.png`
- Media/asset reportado: `scene_01_start` / `crystal_orb`
- Video: `flow/Escena_01_video.mp4`
- Tamaño: 4,134,812 bytes
- Duración: 8.00 s
- Resolución: 720x1280
- Streams: H.264 + AAC
- Aislamiento Start Frame: PASS

### Escena 02

- Start Frame: `backend/data/output/_hard_e2e_c2_01/scene_02.png`
- Start Frame: 890,967 bytes
- Referencia: `ancient_columns`
- Referencia local: `references/ref_asset_02.png`
- Media/asset reportado: `scene_02_start` / `ancient_columns`
- Video: `flow/Escena_02_video.mp4`
- Tamaño: 3,336,408 bytes
- Duración: 8.00 s
- Resolución: 720x1280
- Streams: H.264 + AAC
- Aislamiento Start Frame: PASS

### Escena 03

- Start Frame: `backend/data/output/_hard_e2e_c2_01/scene_03.png`
- Start Frame: 818,393 bytes
- Referencia: `artisan_hands`
- Referencia local: `references/ref_asset_03.png`
- Media/asset reportado: `scene_03_start` / `artisan_hands`
- Video: `flow/Escena_03_video.mp4`
- Tamaño: 3,746,623 bytes
- Duración: 8.00 s
- Resolución: 720x1280
- Streams: H.264 + AAC
- Aislamiento Start Frame: PASS

### Escena 04

- Start Frame: `backend/data/output/_hard_e2e_c2_01/scene_04.png`
- Start Frame: 748,520 bytes
- Referencia: `golden_cleat`
- Referencia local: `references/ref_asset_04.png`
- Media/asset reportado: `scene_04_start` / `golden_cleat`
- Video: `flow/Escena_04_video.mp4`
- Tamaño: 3,037,730 bytes
- Duración: 8.00 s
- Resolución: 720x1280
- Streams: H.264 + AAC
- Aislamiento Start Frame: PASS

---

## 4. Ensamblado Pre-Fallo

El pipeline llegó a producir:

- `video_raw.mp4`
- audio TTS ensamblado
- música de fondo mezclada
- ensamblado de los clips completado

El paso siguiente fue el quemado de subtítulos dinámicos Hormozi mediante `libass` + `libx264` en 1080x1920 / flujo de salida de alta resolución reportado.

Esto confirma que el fallo ocurrió **después** de la generación/ingesta de los cuatro clips y después del ensamblado/audio.

---

## 5. Punto Exacto de Fallo

**Archivo:** `backend/pipeline/video.py`  
**Función:** `burn_subtitles`  
**Línea reportada:** 311

La llamada utiliza:

```python
p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=900))
```

Error reportado:

```text
subprocess.TimeoutExpired
...
timed out after 900 seconds
```

Comando relevante:

```text
ffmpeg -y
-i .../video_raw.mp4
-vf ass=.../subs.ass
-c:v libx264
-preset medium
-crf 20
-c:a copy
.../_hard_e2e_c2_01_final.mp4
```

---

## 6. Diagnóstico

El diagnóstico reportado es que FFmpeg, procesando por CPU con `libx264 -preset medium` y filtro `libass`, tardó ligeramente más de 900 segundos al codificar el render final.

El timeout rígido provocó `TimeoutExpired` y el orquestador terminó marcando el proyecto como `failed`, aun cuando la cadena de Google Flow había completado correctamente.

**Importante:** este documento registra el diagnóstico de la prueba. No declara todavía cuál debe ser la corrección arquitectónica o de rendimiento.

---

## 7. Resultado Final Observado

El archivo final fue producido durante el procesamiento antes de que el runner declarara el timeout:

- Ruta: `backend/data/output/_hard_e2e_c2_01/_hard_e2e_c2_01_final.mp4`
- Artefacto: `hard_e2e_final.mp4`
- Tamaño: 45,892,538 bytes (~45.8 MB)
- Duración: 19.733008 s
- Video: H.264
- Audio: AAC
- Resolución reportada: 2160x3840
- Subtítulos Hormozi: presentes
- Audio mezclado: presente

El hecho de que el archivo final exista y contenga video/audio/subtítulos no convierte el run en PASS, porque el proceso supervisor excedió su timeout y marcó la ejecución como fallida.

---

## 8. Idempotencia

**NO EJECUTADA.**

Run 2 no se alcanzó porque el test runner detuvo la prueba al producirse el timeout del Run 1.

No existe evidencia de regeneración duplicada.

La idempotencia de C.2 ya había sido demostrada previamente en `INT-011`, pero **no debe extrapolarse como resultado de esta prueba dura**.

---

## 9. Limpieza

- `.flow.lock`: liberado.
- Procesos FFmpeg: finalizados limpiamente según el informe.
- Procesos Node MCP: finalizados limpiamente según el informe.
- Locks huérfanos: ninguno reportado.

---

## 10. Dictamen

### HARD E2E: FAIL

Pero el fallo queda localizado en:

```text
video.py → burn_subtitles → FFmpeg → timeout 900 s
```

No hay evidencia en esta ejecución de fallo en:

- GoogleFlowMCP
- upload de referencias
- Start Frame lineage
- generación de los cuatro videos
- descarga de MP4
- `flow_import`
- ensamblado/audio

El siguiente trabajo debe concentrarse exclusivamente en el rendimiento/timeout del render final y, antes de modificarlo, inspeccionar la implementación real de `burn_subtitles` y sus parámetros de codificación.

**No tocar F5/F5.1.**

**No rediseñar GoogleFlowMCP.**

**No crear otra capa de orquestación.**

**No repetir la prueba completa hasta resolver/validar el punto de fallo.**
