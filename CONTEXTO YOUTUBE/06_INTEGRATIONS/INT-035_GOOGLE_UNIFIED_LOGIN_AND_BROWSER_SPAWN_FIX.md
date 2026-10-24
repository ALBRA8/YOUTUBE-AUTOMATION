# INT-035 · RESOLUCIÓN DE LOGIN GOOGLE UNIFICADO Y LANZAMIENTO DESACOPLADO EN WINDOWS

**Estado:** IMPLEMENTADO, DEPURADO Y VERIFICADO  
**Fecha:** 2026-10-24  
**Contexto:** Corrección de apertura de Chrome en Windows, limpieza de procesos zombis en segundo plano y bypass del bloqueo OAuth de Google.

---

## 1. Diagnóstico del Problema

1. **Procesos Zombis en Segundo Plano (Causa Raíz de la Ausencia de Ventana):**  
   Al lanzar Chrome previamente con rutas que contenían espacios (`D:\PROYECTOS\YOUTUBE AUTOMATION`), el argumento se dividió en `--user-data-dir=D:\PROYECTOS\YOUTUBE`. Esto creó 22 procesos huérfanos de Chrome corriendo de forma invisible en segundo plano. Cuando el usuario pulsaba el botón, el ejecutable de Chrome detectaba una instancia en ejecución en ese perfil y le delegaba la apertura por IPC, pero al ser procesos sin ventana de escritorio interactiva, **no se mostraba ninguna ventana**.

2. **Bloqueo OAuth de Google:**  
   Google detecta flags de depuración remota (`--remote-debugging-port`) y bloquea activamente los inicios de sesión con el error:  
   > *"No se pudo iniciar sesión. Es posible que este navegador o aplicación no sea seguro."*  
   Por tanto, el inicio de sesión inicial de Google debe realizarse en un Chrome limpio con el perfil compartido pero SIN el puerto CDP activo.

3. **Lanzamiento de Procesos en Windows con Rutas con Espacios:**  
   Se requiere que `--user-data-dir="<ruta_completa>"` viaje con las comillas encapsulando únicamente la ruta del directorio después del signo `=`, ejecutado mediante `start "" "<chrome.exe>" ...` en una subshell nativa de Windows.

---

## 2. Cambios Implementados

### A. Limpieza de Procesos Zombis y Lockfiles
- Terminación de todos los procesos huérfanos de Chrome que tenían bloqueado el directorio `D:\PROYECTOS\YOUTUBE`.
- Eliminación de archivos residuales `lockfile` en `backend/data/google_profile_global`.

### B. Backend (`backend/services/mcp_manager.py`)
- **Sintaxis Blindada en Windows:** `_spawn_chrome` formatea cada argumento asegurando `--user-data-dir="<ruta>"` y lanza mediante `start "" "<chrome_bin>" <args>` con `shell=True`, garantizando la creación de una ventana interactiva en el escritorio del usuario.
- **Parámetro `cdp: bool = True`:** `launch_google_login(urls, cdp=True)` permite lanzar Chrome en modo limpio (`cdp=False`, sin `--remote-debugging-port`) para el login humano inicial sin bloqueos de Google, y en modo depuración (`cdp=True`, puerto 9333) una vez completado.

### C. Endpoints FastAPI (`backend/main.py`)
- **Nuevo Endpoint:** `POST /api/mcp/launch-clean-login` con purga automática previa de `lockfile`.

### D. Frontend Dashboard (`backend/static/app.js`)
- **Flujo Guiado de 3 Pasos en la Tarjeta de Sesión Google:**
  1. `1. 🔑 Abrir Login Seguro Google`: Abre Chrome en modo limpio para iniciar sesión en Google Accounts sin bloqueos.
  2. `2. 🔌 Conectar Chrome (CDP 9333)`: Abre/reconecta Chrome con el puerto CDP 9333 reutilizando la sesión activa.
  3. `3. 📥 Capturar sesión → NotebookLM`: Extrae las cookies de Google del Chrome CDP y las escribe en `storage_state.json`.

---

## 3. Verificación
- Verificado `POST /api/mcp/launch-clean-login` respondiendo HTTP 200 OK y levantando proceso Chrome con renderer interactivo.
- Verificado servidor uvicorn activo y saludable en `http://127.0.0.1:8000/api/health`.
