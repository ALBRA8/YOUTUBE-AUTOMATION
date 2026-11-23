# INT-091 · Selector de Carpetas Nativo en PC y Workspace Mirroring

**Estado:** IMPLEMENTADO Y VERIFICADO (100% PASS)  
**Fecha:** 2026-11-06  
**Módulo:** `backend/static/app-wizard.js`, `backend/main.py`, `backend/services/project_workspace.py`  
**Test Suite:** `tests/test_int091_custom_folder_picker.py` (9/9 passed)

---

## 1. Contexto y Problema

El usuario rechazó enfáticamente la imposición de rutas predefinidas o forzadas para sus proyectos y nichos:
* **El usuario manda sobre el almacenamiento:** El usuario debe poder navegar por sus discos duros (`C:`, `D:`, etc.) mediante el explorador nativo de Windows y seleccionar la carpeta exacta donde vivirá cada video.
* **Modelo Mental:**
  * **Plantilla (Nicho / Universo):** `FRUTINOVELAS`, `RECETAS`, `PRIMITIVE VIRAL`, `REFLEXIONES` (define reglas de producción, 3D animado vs realismo, cadencia, voces, prompts Flow; nunca se mezclan).
  * **Proyecto:** Un episodio o video específico dentro de ese nicho.
  * **Ubicación Física:** Libre y decidida por el usuario.

### El Fallo Anterior
Se intentó abrir el selector mediante procesos de fondo en Python (`powershell.exe -Command FolderBrowserDialog`). En entornos Windows de escritorio o servicios sin estación interactiva (`WinSta0`), el diálogo se congelaba, abría detrás de las ventanas o producía excepciones de permisos (`PropertyAssignmentException`).

---

## 2. Solución Arquitectónica (Patrón Nativo del Navegador)

Inspirado en la extensión de Chrome (`extension/popup.js:278`), la solución ejecuta la apertura directamente en el navegador del usuario:

1. **Frontend (`app-wizard.js` - `qcPickDestino`):**
   - Llama a la API nativa de Chrome: `window.showDirectoryPicker({ mode: 'readwrite' })`.
   - Como se dispara directamente por el evento de clic del usuario en pantalla, Chrome le ordena a Windows abrir el explorador de archivos de inmediato, sin bloqueos del SO ni procesos fantasma.
   - Extrae el nombre de la carpeta seleccionada (`handle.name`).

2. **Resolución de Ruta Absoluta (`main.py` - `GET /api/dialog/resolve-folder-path`):**
   - El navegador por seguridad sandbox no expone la ruta absoluta completa en `handle.name`.
   - El endpoint `resolve-folder-path?name=...` busca la coincidencia exacta en las raíces de trabajo del usuario (ej. `D:\PROYECTOS\CANALES DE YOUTUBE Y TIKTOK\NICHOS\...`) y resuelve la ruta física absoluta en milisegundos.
   - El input de destino se rellena automáticamente y permite edición libre.

3. **Fallback Automático con Diálogo de Windows:**
   - Si el navegador no soporta File System Access API (ej. navegadores heredados), el backend ejecuta el diálogo nativo de Windows con `.NET FolderBrowserDialog` saneado (sin `AutoUpgradeEnabled`), resolviendo en thread asíncrono sin bloquear el event-loop de FastAPI.

4. **Sincronización Total al Destino (`project_workspace.py`):**
   - Al finalizar el render, todos los artefactos se espejan en la carpeta física elegida:
     - `out/video_final.mp4` (Video máster)
     - `out/contact_sheet.png` (Hoja de contactos)
     - `guion/guion.json` y `guion.md`
     - `voz/narracion.wav` y `voz/audio_master.json`
     - `portada.png` y `marca.json`

---

## 3. Verificación
* **Test automatizado:** `python -m pytest tests/test_int091_custom_folder_picker.py -k "not sin_gui"` (9/9 PASSED).
* **Prueba de usuario:** Confirmado en vivo: *"por fin se arreglo"*. El diálogo de Windows abre instantáneamente.
