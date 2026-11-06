# INT-092 · Google Flow Ecosystem, Timeout Hardening y Render 4K

**Estado:** IMPLEMENTADO, END-TO-END VERIFICADO EN PRODUCCIÓN (100% OK)  
**Fecha:** 2026-11-06  
**Módulos:** `backend/static/app-mcp.js`, `backend/services/mcp_manager.py`, `backend/services/flow_mcp_client.py`, `backend/config.py`, `backend/.env`

---

## 1. Problemas Diagnosticados

### A. Falso Estado «DESCONECTADO» en MCP Connection Manager
El panel mostraba el Ecosistema Google como `DESCONECTADO` a pesar de que el servidor `srz-google-flow-mcp` estaba activo y conectado (`auth=ok`) con la cuenta de Google activa (`account-albragroup8@gmail.com`).
* **Causa Raíz:** En `app-mcp.js:277`, la condición de conexión exigía conjuntamente NotebookLM:
  ```javascript
  const connected = gsessSvcState(st.flow) && gsessSvcState(st.notebooklm);
  ```
  Al estar NotebookLM desconectado, evaluaba a `false` y ocultaba la conexión viva de Flow.
* **Mismo problema en Backend (`mcp_manager.py:1516`):** Requería ambos servicios en `ST_CONNECTED` para transicionar `sso_phase` a `connected`.

### B. Timeouts Prematuros en Google Flow (`FLOW_MCP_TIMEOUT = 120s`)
Durante la generación de imágenes con Google Flow (Nano Banana / Imagen 3), cuando los servidores de Google tardaban más de 2 minutos por cola, el backend mataba el proceso con `FlowMCPTimeoutError(Timeout de 120.0s)`.
* Al fallar Flow, el sistema intentaba el fallback de Gemini (que devolvió error de API key), degradando las escenas a **placeholders de color sólido (tarjetas de 10 KB)** y forzando zooms Ken Burns.

### C. Prompts Genéricos Inapropiados
En caso de degradación del generador de guiones, el fallback local insertaba prompts de fotografía de cámara real (`"cinematic photography, shot on Sony A7R IV, 85mm f/1.8 lens"`), perdiendo el estilo animado 3D de Frutinovelas.

---

## 2. Correcciones Implementadas

### A. Desacoplamiento y One-Tap Nativo en Google Auth
1. **Frontend (`app-mcp.js`):**
   - Condición desacoplada:
     ```javascript
     const connected = gsessSvcState(st.flow) || gsessSvcState(st.notebooklm) || (js && js.sso_phase === 'connected') || !!(js && js.account);
     ```
   - El botón «Continuar con Google» abre directamente `window.open('https://flow.google.com', '_blank')` en el navegador del usuario (cero bloqueos de consola o sesión interactiva WinSta0).
   - El botón «Abrir Google Flow» permite acceso directo.
2. **Backend (`mcp_manager.py`):**
   - Transiciona `sso_phase = "connected"` cuando Flow o la sesión de Google están activas.
   - Extrae automáticamente la cuenta activa (`account-albragroup8@gmail.com`).

### B. Timeout Hardening (300 segundos / 5 minutos)
* `backend/.env`: `FLOW_MCP_TIMEOUT=300`.
* `backend/config.py`: `FLOW_MCP_TIMEOUT = 300.0`.
* `backend/services/flow_mcp_client.py`: timeout por defecto elevado a 300.0 s para `call_tool`, `flow_generate_image` y `upload_file`.

### C. Estilo Coherente Frutinovelas (`pixar-3d`)
* Selección de tema `pixar-3d` (`"Pixar-style 3D animation, soft global illumination, appealing stylized characters, subsurface scattering skin, vibrant colors, heartwarming cinematic render"`).
* Generación de personajes Manolo y Fresita con consistencia 3D e iluminación volumétrica.

---

## 3. Resultado de la Prueba Real E2E

* **ID de Proyecto:** `5637bfa9cd08` (Título: *"Frutinovelas: Manolo y Fresita"*).
* **Imágenes Flow:** 100% generadas por Google Flow Nano Banana (pesos entre 600 KB y 880 KB, cero placeholders de 10 KB).
* **Render de Video:**
  * **Resolución:** **`2160 x 3840` (4K Ultra HD Vertical 9:16)**.
  * **Duración:** `60.9 segundos`.
  * **Peso del Archivo:** `82.6 MB` (`82,620,513 bytes`).
  * **Subtítulos:** Quemados con libass en Montserrat ExtraBold y contraste dinámico de brillo.
  * **Sincronización:** Guardado automáticamente en `D:\PROYECTOS\CANALES DE YOUTUBE Y TIKTOK\NICHOS\FRUTINOVELAS\Episodio_01\out\video_final.mp4`.
