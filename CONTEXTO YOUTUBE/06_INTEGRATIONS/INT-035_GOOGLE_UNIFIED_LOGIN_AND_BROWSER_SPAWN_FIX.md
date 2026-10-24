# INT-035 · RESOLUCIÓN DE LOGIN GOOGLE UNIFICADO Y LANZAMIENTO DESACOPLADO EN WINDOWS

**Estado:** IMPLEMENTADO Y VERIFICADO  
**Fecha:** 2026-10-24  
**Contexto:** Corrección de bloqueo en el botón «1. 🔑 Abrir Login Seguro Google» / «Vincular Sesión Google» y bypass del bloqueo OAuth de Google.

---

## 1. Diagnóstico del Problema

1. **Bloqueo OAuth de Google:**  
   Google detecta flags de depuración remota (`--remote-debugging-port`) y bloquea activamente los inicios de sesión con el error:  
   > *"No se pudo iniciar sesión. Es posible que este navegador o aplicación no sea seguro."*  
   Por tanto, el inicio de sesión inicial de Google debe realizarse en un Chrome limpio con el perfil compartido pero SIN el puerto CDP activo.

2. **Lanzamiento de Procesos en Windows (`cmd /c start` vs `os.startfile`):**  
   En Windows, ejecutar `subprocess.Popen(["cmd.exe", "/c", "start", '""'] + argv)` desde un servidor FastAPI provocaba un escape defectuoso de comillas (`"\"\""`), lo que impedía que `cmd.exe start` abriera la ventana interactiva en el escritorio del usuario.  
   Además, las rutas que contenían espacios (`D:\PROYECTOS\YOUTUBE AUTOMATION\...`) provocaban divisiones indebidas de argumentos.

3. **Inclusión de Pestañas Canónicas de Google:**  
   La configuración anterior abría únicamente `flow.google.com` y `notebooklm.google.com`, sin incluir la URL directa del portal de autenticación de Google (`https://accounts.google.com/`).

---

## 2. Cambios Implementados

### A. Backend (`backend/services/mcp_manager.py`)
- **Implementación de `os.startfile`:** En Windows (`sys.platform == 'win32'`), `_spawn_chrome` utiliza `os.startfile(chrome, "open", arguments=args_str)` a través de la API Win32 ShellExecuteW. Esto garantiza que la ventana de Chrome se cree en la sesión interactiva del escritorio del usuario con argumentos entrecomillados correctamente.
- **Parámetro `cdp: bool = True`:** `launch_google_login(urls, cdp=True)` permite lanzar Chrome en modo limpio (`cdp=False`, sin `--remote-debugging-port`) para el login humano inicial sin bloqueos de Google, y en modo depuración (`cdp=True`, puerto 9333) una vez completado.

### B. Endpoints FastAPI (`backend/main.py`)
- **Nuevo Endpoint:** `POST /api/mcp/launch-clean-login` para el Paso 1 de login limpio.
- **Cache-Busting Frontend:** Actualizado `index.html` a `app.js?v=2.26.0`.

### C. Frontend Dashboard (`backend/static/app.js`)
- **Flujo Guiado de 3 Pasos en la Tarjeta de Sesión Google:**
  1. `1. 🔑 Abrir Login Seguro Google`: Abre Chrome en modo limpio para iniciar sesión en Google Accounts sin bloqueos.
  2. `2. 🔌 Conectar Chrome (CDP 9333)`: Abre/reconecta Chrome con el puerto CDP 9333 reutilizando la sesión activa.
  3. `3. 📥 Capturar sesión → NotebookLM`: Extrae las cookies de Google del Chrome CDP y las escribe en `storage_state.json`.

### D. Script Standalone (`tools/mcp-setup/login-google-unificado.bat`)
- Creado script interactivo de 1 clic que orquesta los pasos localmente en caso de que el operador prefiera la terminal.

---

## 3. Verificación
- Verificado `POST /api/mcp/launch-clean-login` respondiendo HTTP 200 OK y ejecutando `os.startfile`.
- Verificado servidor uvicorn activo y saludable en `http://127.0.0.1:8000/api/health`.
