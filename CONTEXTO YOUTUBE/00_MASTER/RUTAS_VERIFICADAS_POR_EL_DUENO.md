# Rutas Verificadas por el Dueño (Google SSO y MCP)

Este documento cataloga las rutas del backend y botones del panel web que el dueño del proyecto ejecutó con éxito en su entorno real (Windows, Chrome con perfil de usuario y servidores MCP locales).

> **REGLA DE ORO DE ARQUITECTURA (LEEME_PRIMERO.md):**  
> Estas rutas no se sustituyen, no se eliminan y no se altera su semántica sin evidencia directa y pruebas comprobadas en la máquina real del dueño.

---

## 1. Catálogo de Rutas Verificadas

### 1.1 `POST /api/mcp/google-sso/launch` (con `force_window: true`)
- **Propósito:** Abrir la ventana interactiva de Chrome con depuración remota CDP en el puerto 9333, garantizando que el proceso sea visible y usable por el usuario para iniciar sesión en Google.
- **Origen / Referencia:** INT-071, INT-081, INT-081b.
- **Comportamiento en Backend:**
  - Invoca `mcp_manager.launch_google_login(pages, cdp=True, force_window=True)`.
  - Si detecta un proceso Chrome fantasma (abierto pero sin `MainWindowHandle`), purga procesos con `kill_profile_processes` y sanea cerrojos (`Singleton*`).
  - Lanza Chrome con `--remote-debugging-port=9333` y valida que el puerto CDP 9333 responda.
  - Comprueba y confirma la creación de ventana interactiva.
- **Validación en la PC del Dueño:**
  1. El dueño pulsa el botón «Abrir ventana de Chrome» en la sección *Avanzado* del panel MCP.
  2. Se abre una ventana visible de Google Chrome en su pantalla con la página de inicio o login de Google.
  3. El dueño inicia sesión con sus credenciales de Google.
  4. El endpoint responde `{ ok: true, relaunched: bool, chrome_up: true }`.
  5. La fila de Chrome en `/api/mcp/resumen` y en la tarjeta «Ecosistema Google» se torna verde (`ok: true`, CDP 9333 activo).

---

### 1.2 `POST /api/mcp/launch-auth-browser`
- **Propósito:** Lanzamiento alternativo de navegador para autenticación manual de Google SSO cuando se requiere forzar navegación al flujo web de login.
- **Origen / Referencia:** Implementación base del servidor SSO MCP (`backend/main.py`).
- **Comportamiento en Backend:**
  - Invoca `mcp_manager.launch_auth_browser()`.
  - Inicia la instancia del navegador orientada a la URL de autenticación o perfil de trabajo.
- **Validación en la PC del Dueño:**
  1. El dueño pulsa «Lanzar Navegador Auth» desde la consola o interfaz de soporte.
  2. Responde `{ ok: true, message: ... }`.
  3. Se despliega el navegador permitiendo completar el flujo OAuth/SSO de Google.

---

### 1.3 `POST /api/mcp/repair-profile`
- **Propósito:** Sanear el directorio del perfil de Chrome si quedó bloqueado por un cierre anormal, proceso huérfano o zombi.
- **Origen / Referencia:** `heal_chrome_profile` en `backend/services/mcp_manager.py`.
- **Comportamiento en Backend:**
  - Invoca `mcp_manager.heal_profile()`.
  - Mata procesos Chrome que usen el directorio con `taskkill /F /IM chrome.exe`.
  - Elimina los archivos de cerrojo `SingletonLock`, `SingletonCookie` y `SingletonSocket`.
  - Devuelve lista de acciones tomadas: `{ ok: true, actions: [...] }`.
- **Validación en la PC del Dueño:**
  1. Cuando Chrome no responde o el puerto 9333 colapsa, el dueño pulsa «Reparar perfil» en *Avanzado*.
  2. El sistema purga locks y procesos colgados.
  3. La respuesta confirma `perfil saneado` con las acciones ejecutadas.
  4. Un intento posterior de lanzamiento abre Chrome limpiamente sin bloqueos de perfil.

---

### 1.4 `POST /api/mcp/connect` (servicio `google-flow`)
- **Propósito:** Conectar el cliente MCP de Google Flow usando las credenciales / sesión del perfil activo de Chrome y el puente CDP.
- **Origen / Referencia:** Servicios MCP y orquestador de proyectos.
- **Comportamiento en Backend:**
  - Recibe `{ "service": "google-flow" }`.
  - Inicia o enlaza el subproceso MCP correspondiente (transporte stdio o SSE hacia FastMCP / Flow bridge).
  - Consulta `tools/list` para verificar conectividad y capacidades.
  - Devuelve `{ state: "connected", ... }` o `{ state: "auth_required", ... }`.
- **Validación en la PC del Dueño:**
  1. Con Chrome activo y sesión iniciada en Google Flow (labs.google / flow.google.com).
  2. El dueño pulsa «Conectar» en la tarjeta Google Flow o se invoca desde «Conectar todo».
  3. El endpoint responde `{ state: "connected" }`.
  4. La tarjeta y badge de Google Flow pasan a estado conectado (`🟢`).

---

## 2. Garantías de No Regresión

1. **Frontend (`backend/static/app-mcp.js`):** Debe mantener intactas las funciones que invocan estas 4 rutas:
   - `gsessOpenWindow()` → `/mcp/google-sso/launch` con `force_window: true`
   - `gsessRepairProfile()` → `/mcp/repair-profile`
   - `mcpConnect('google-flow')` → `/mcp/connect`
   - `launch-auth-browser` llamado en acciones avanzadas de autenticación.
2. **Backend (`backend/main.py`):** Los 4 endpoints deben permanecer declarados y funcionales.
3. **Guardia Estática:** El test `tests/test_w3_rutas_verificadas.py` verifica de forma automatizada y permanente que ninguna de estas rutas sea retirada ni del frontend ni del backend.
