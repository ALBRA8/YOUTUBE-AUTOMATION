# SES-2026-11-25-01 — Recuperación Google Flow CDP, Limpieza de Procesos Zombi y Generación Real de Vídeo

- **Fecha:** 2026-11-25
- **Estado:** CLOSED / PASS (RECUPERACIÓN TOTAL Y GENERACIÓN REAL DEMOSTRADA)
- **Repo:** `D:\PROYECTOS\YOUTUBE AUTOMATION`
- **HEAD:** `ac9340d` (`main`)
- **Herramientas Validadas:** Google Flow MCP (`srz-google-flow-mcp`), Chrome CDP 9333, Playwright connectOverCDP, ffprobe.

---

## 1. Objetivo y Alcance

1. **Investigación y Diagnóstico Forense:** Identificar la causa de los cuelgues recurrentes en la conexión Chrome CDP (puerto 9333) y descartar posibles regresiones de código.
2. **Protección e Integridad:** Garantizar que no se toquen procesos del navegador Chrome personal del usuario ni se modifique destructivamente el repositorio.
3. **Limpieza Quirúrgica:** Terminar exclusivamente los procesos zombi asociados al perfil dedicado `FlowImageChrome` y verificar la liberación del puerto 9333.
4. **Recuperación de Conectividad:** Re-arrancar la instancia de Chrome dedicada y validar la reconexión de Playwright y del servidor MCP.
5. **Prueba Real E2E en Google Flow:**
   - Ejecutar `flow_list_assets` vía `POST /api/mcp/execute`.
   - Ejecutar una generación de vídeo 100% real mediante `flow_generate_video` con un ancla de imagen existente.
   - Descargar el archivo MP4, verificar su existencia en disco, tamaño (>0 bytes), duración, resolución y códecs con `ffprobe`.

---

## 2. Auditoría y Diagnóstico de Procesos (Fase 1 y Fase 2)

### Auditoría del Sistema:
- **Total de procesos `chrome.exe` activos:** 28 procesos.
- **Chrome personal del usuario:** 17 procesos (conservados intactos, sin tocar).
- **Procesos huérfanos de Flow:** 11 procesos asociados a `FlowImageChrome`:
  - Proceso raíz: PID `11896` escuchando en `127.0.0.1:9333` (`LISTEN`).
  - Renderers y utilities hijos: PIDs `5708, 6688, 7900, 14548, 25976, 26204, 29436, 29540, 29772, 30056`.

### Causa Raíz Identificada:
Al consultar `http://127.0.0.1:9333/json/list` se constató la presencia de targets de interfaz interna de Chrome:
- `chrome://omnibox-popup.top-chrome/` (`type: browser_ui`)
- `chrome://omnibox-popup.top-chrome/omnibox_popup_aim.html` (`type: browser_ui`)

En Windows, cuando `chromium.connectOverCDP("http://127.0.0.1:9333")` se ejecuta, Playwright intenta negociar targets globales con el WebSocket del navegador (`ws://.../devtools/browser/...`). La presencia de ventanas emergentes ocluidas del omnibox de Chrome bloqueaba el handshake interno de Playwright, desencadenando timeouts de 120,000 ms. A su vez, `cdpAlive()` en `chrome.js` detectaba HTTP 200 en `/json/version`, reusando indefinidamente la instancia zombi.

---

## 3. Limpieza Controlada (Fase 3)

Se ejecutó script con `psutil 7.2.2` para terminar de forma selectiva los procesos que contenían `FlowImageChrome` en su línea de comandos:
- PIDs terminados: `[11896, 5708, 6688, 7900, 14548, 25976, 26204, 29436, 29540, 29772, 30056]`.
- Procesos de Chrome del usuario preservados: 17 procesos intactos.
- Estado del puerto 9333: Completamente liberado (`LISTEN` = False).

---

## 4. Recuperación de la Conexión (Fase 4)

Se invocó `POST /api/mcp/connect-all-google`.
- Chrome arrancó con PID `23896` en el puerto 9333.
- Playwright y Google Flow MCP conectaron de inmediato:
  ```text
  [flow] CDP connect OK en 924ms
  ```
- Comprobación de `http://127.0.0.1:9333/json/version`:
  - `Browser`: `Chrome/158.0.8127.36`
  - `webSocketDebuggerUrl`: `ws://127.0.0.1:9333/devtools/browser/8417d865-9756-45c5-b6bb-6cf7f0afe527`

---

## 5. Pruebas Reales de Google Flow (Fase 5)

### Primera Prueba: `flow_list_assets`
- **Endpoint:** `POST /api/mcp/execute` con `{"service": "google-flow", "tool": "flow_list_assets"}`.
- **Tiempo:** 36.51 s (apertura y carga inicial del proyecto).
- **Resultado:** HTTP 200 OK, 27 assets detectados, incluyendo el ancla:
  `- personaje [id:02b5fa3d-179c-488a-b99b-64cc219a573e]`.

### Segunda Prueba: Generación Real de Vídeo (`flow_generate_video`)
- **Parámetros:**
  - `startFrame`: `"id:02b5fa3d-179c-488a-b99b-64cc219a573e"` (asset `personaje`)
  - `prompt`: `"Slow zoom in on the red apple character with big expressive eyes, looking shocked in a kitchen"`
  - `aspect`: `"9:16"`
  - `timeout`: `720`
- **Ejecución:**
  - Generación en Google Flow (Fotogramas) completada en **84 segundos**.
  - Descarga automática del archivo MP4 a disco completada en 107.1 s totales.
- **Respuesta API literal:**
  ```json
  {
    "ok": true,
    "service": "google-flow",
    "tool": "flow_generate_video",
    "text": "Generated video in 84s (1342954 bytes, 9:16) with startFrame \"id:02b5fa3d-179c-488a-b99b-64cc219a573e\" (asset \"personaje\"):\nD:\\PROYECTOS\\YOUTUBE AUTOMATION\\tools\\GoogleFlowMCP\\output\\2026-11-25T06-18-29-slow-zoom-in-on-the-red-apple-character-.mp4",
    "elapsed_s": 106.77
  }
  ```

---

## 6. Verificación Técnica del Archivo MP4 (ffprobe)

- **Ruta del archivo:** `tools/GoogleFlowMCP/output/2026-11-25T06-18-29-slow-zoom-in-on-the-red-apple-character-.mp4`
- **Existe en disco:** `True`
- **Tamaño:** `1,342,954 bytes` (1.28 MB)
- **Formato contenedor:** `mov, mp4, m4a, 3gp, 3g2, mj2`
- **Duración:** `8.010884 s`
- **Bitrate:** `1,341,129 bps`
- **Stream de Vídeo:** `h264`, `720x1280` (9:16 vertical), `24 fps`
- **Stream de Audio:** `aac`

---

## 7. Estado de Mandatos y Conclusiones

| Componente | Estado | Evidencia |
| :--- | :--- | :--- |
| **Limpieza Chrome Flow** | **PASS** | 11 procesos zombi purgados; 17 procesos de Chrome personal intactos; puerto 9333 liberado. |
| **Conexión CDP** | **PASS** | Handshake de Playwright exitoso en 924 ms; endpoint `/json/version` verificado. |
| **Google Flow Assets** | **PASS** | `flow_list_assets` devolvió 27 assets en 36.51 s. |
| **Generación de Vídeo Real** | **PASS** | Generado en 84 s mediante Flow Fotogramas con startFrame `personaje`; MP4 válido descargado. |
| **Integridad del Repositorio** | **PASS** | Cero regresiones en código base; `main` en `ac9340d` completamente operativo. |
