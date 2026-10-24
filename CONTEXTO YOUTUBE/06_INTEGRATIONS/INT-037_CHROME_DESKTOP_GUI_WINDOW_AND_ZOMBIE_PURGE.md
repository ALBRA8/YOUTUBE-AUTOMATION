# INT-037 · Chrome Desktop GUI Window Display & Zombie Purge Architecture

**Fecha:** 2026-10-24  
**Estado:** ✅ IMPLEMENTADO Y VERIFICADO  
**Módulos afectados:** `backend/services/mcp_manager.py`, `tools/mcp-setup/login-google-unificado.bat`, `VINCULAR-GOOGLE.bat`

---

## 1. Diagnóstico y Causa Raíz

### Síntoma Reportado:
Al pulsar **`1. 🔑 Abrir Login Seguro Google`** o invocar `/api/mcp/launch-clean-login`, la interfaz web indicaba que Chrome se había lanzado, pero **ninguna ventana visible de Chrome aparecía en el escritorio del usuario** (`MainWindowHandle == 0`).

### Causas Raíz Técnicas Descubiertas en Auditoría Windows:

1. **Aislamiento de Sesión y Supresión de Ventana GUI por `subprocess.Popen("start ...", shell=True)`:**
   - Uvicorn se ejecuta como proceso secundario en segundo plano. Cuando invocaba `start "" "chrome.exe" ...` a través de `cmd.exe /c`, el proceso de Chrome heredaba atributos de ventana no interactivos o se abría sin engancharse a la estación de ventanas del explorador interactivo (`MainWindowHandle == 0`).
2. **Procesos Zombis sin Ventana Capturando Peticiones (Chromium Single Instance IPC):**
   - Había procesos huérfanos de Chrome en segundo plano vinculados a `%LOCALAPPDATA%\FlowImageChrome` (como el PID 20032 y sus subprocesos renderers).
   - Chromium implementa una arquitectura *Single Instance*: cuando se intenta abrir Chrome con el mismo perfil, el nuevo ejecutable no crea una nueva ventana si detecta que la instancia ya existe; simplemente le envía un mensaje IPC a la instancia existente y se cierra. Dado que la instancia existente estaba oculta/zombi (`MainWindowHandle == 0`), el usuario nunca veía ninguna ventana.
3. **Falta de Purga en Modo Limpio (`cdp=False`):**
   - La purga de zombis (`kill_profile_processes`) solo se estaba ejecutando cuando `cdp=True`. Al pulsar `launch-clean-login` (que usa `cdp=False`), los zombis preexistentes nunca se eliminaban.

---

## 2. Soluciones Implementadas

### A. Lanzamiento Nativo Vía Shell de Windows (`os.startfile`)
En `backend/services/mcp_manager.py` (`_spawn_chrome`):
- Se sustituyó `subprocess.Popen('start "" ...', shell=True)` por `os.startfile(chrome, "open", arguments=args_str)`.
- `os.startfile` ejecuta internamente `ShellExecuteExW` a través del Explorador de Windows con `SW_SHOWNORMAL (1)`, garantizando que el navegador se ejecute en la estación de ventanas activa e interactiva del usuario y aparezca en primer plano con `MainWindowHandle != 0`.

### B. Purga Incondicional de Procesos Zombis Antes de Spawn
En `launch_google_login`:
- Se eliminó la restricción `if cdp:`. Ahora, siempre que `already_up` sea falso, se ejecuta `kill_profile_processes(profile)` antes de invocar Chrome, asegurando que cualquier instancia fantasma u oculta sea purgada y no intercepte el inicio de sesión.

### C. Actualización de Scripts Batch (`login-google-unificado.bat` y `VINCULAR-GOOGLE.bat`)
- Se incluyó la purga automática de procesos huérfanos de `FlowImageChrome` antes del paso 1 (login limpio) y antes del paso 2 (CDP 9333).

---

## 3. Análisis sobre ClonaKit

El usuario consultó sobre la utilización de **ClonaKit** para investigar y clonar soluciones.
- **Qué es ClonaKit:** Un kit metodológico en español diseñado para construir versiones funcionales de aplicaciones web desde cero mediante especificación en sala limpia (`FICHA.md`), investigación (`REA / informe.md`) y demos estáticas en HTML/CSS/JS.
- **Aplicabilidad al caso:** El fallo reportado no era de lógica frontend ni de clonación web, sino un problema de gestión de procesos y ventanas en el kernel de Windows (Win32 Shell Station & Chromium Single Instance IPC). La solución requería interactuar directamente con la API del sistema operativo (`ShellExecuteExW` / `os.startfile`) y la terminación de subprocesos zombis de Chromium.

---

## 4. Verificación y Resultados

1. **Pruebas de Proceso:**
   - Chrome lanzado con `os.startfile` registra ventana interactiva visible en pantalla (`MainWindowHandle > 0`).
2. **Baterías de Pruebas Automatizadas:**
   - `test_int036_profile_heal_and_strict_auth.py`: **23/23 OK (100%)**
   - `test_mcp_manager.py`: **38/38 OK (100%)**
3. **Servicio Activo:** Uvicorn reiniciado y respondiendo 200 en `http://127.0.0.1:8000/api/mcp/status`.
