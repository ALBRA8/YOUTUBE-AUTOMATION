# INT-036 · AUTO-HEAL DE PERFIL CHROME, LANDING OAUTH DIRECTO Y VERIFICACIÓN ESTRICTA DE COOKIES CDP

**Estado:** IMPLEMENTADO, DEPURADO Y VERIFICADO AL 100%  
**Fecha:** 2026-10-24  
**Contexto:** Corrección integral de corrupción de perfiles Chrome (`Local State.bad` / `Preferences`), redirección directa al formulario de login OAuth de Google Flow y verificación estricta de cookies de sesión (`SID` / `__Secure-1PSID`) sobre CDP 9333.

---

## 1. Diagnóstico y Causas Raíz

1. **Corrupción del Perfil de Chromium (`Local State.bad` / `Preferences` modal de bloqueo):**  
   En Windows, cierres forzados de procesos anteriores (`taskkill` o reinicios) generaron archivos residuales `Local State.bad`, bloqueos huérfanos (`lockfile`, `SingletonLock`) y configuraron el estado del perfil en `Default\Preferences` como `"exit_type": "Crashed"` con `"exited_cleanly": false`.  
   Al arrancar, Chrome abría modales de recuperación de pestañas estrelladas o advertencias de perfil dañado (*"Se produjo un error en el perfil. Tu archivo de preferencias está dañado"*), bloqueando la inicialización del escucha CDP en el puerto 9333.

2. **URL de Destino Errónea (`flow.google.com/about` en vez del Login OAuth Real):**  
   Al abrir `https://flow.google.com/` o `https://accounts.google.com/` sin parámetros de continuación directos a la herramienta, Google redirigía a la página pública de marketing `https://flow.google.com/about`. Esto obligaba al usuario a interactuar manualmente buscando botones y causaba que las herramientas de automatización de Flow no encontraran los selectores esperados.

3. **Badge Falso de `auth_ok` y Verificación Débil:**  
   `mcp_manager.py` consideraba Google Flow como autenticado simplemente si el proceso de Chrome respondía en el puerto 9333 o si `flow_list_assets` devolvía un resultado vacío (el cual en la página de marketing no contenía el string `"not signed in"`). Esto generaba un estado `AUTENTICADO` falso y hacía que la ejecución fallara al 2% en la generación de imágenes, arrojando mensajes engañosos de autenticación.

---

## 2. Arquitectura de la Solución (INT-036)

### A. Auto-Heal de Perfil Chrome (`_heal_chrome_profile` / `repair_profile`)
- **Rutina Automática de Saneamiento:** Implementada en `backend/services/mcp_manager.py` (método `heal_chrome_profile` y `repair_profile`). Se ejecuta de forma determinista antes de cualquier lanzamiento de Chrome (`_spawn_chrome` y `launch_google_login`).
- **Acciones Ejecutadas por el Sanador:**
  1. Detección y eliminación inmediata de `Local State.bad`.
  2. Eliminación de bloqueos huérfanos: `lockfile`, `SingletonLock`, `SingletonCookie`, `SingletonSocket`.
  3. Validación estructural de `Local State` (eliminación segura si el JSON está truncado o corrupto).
  4. Saneamiento de `Default\Preferences`: si el JSON es inválido se regenera con estructura mínima limpia; si es válido, reescribe `"exit_type": "Normal"`, `"exited_cleanly": true` tanto en el objeto `profile` como en la raíz.
- **Supresión de Burbujas de Crash en Chrome:** Siempre se inyectan los flags:
  `--no-default-browser-check --no-first-run --disable-session-crashed-bubble --hide-crash-restore-bubble --disable-features=SessionCrashedBubble`.
- **Nuevo Endpoint REST:** `POST /api/mcp/repair-profile` permite activar el saneamiento bajo demanda desde la API o el frontend.

### B. Landing Directo al Formulario OAuth de Google
- **Pestaña 1 (Flow Directo):**  
  `https://accounts.google.com/ServiceLogin?continue=https://labs.google/fx/tools/flow`  
  El usuario aterriza directamente en el formulario oficial de inicio de sesión de Google con destino final en las herramientas de Flow (Nano Banana / FX).
- **Pestaña 2 (NotebookLM):**  
  `https://notebooklm.google.com/`  
  Permite que el inicio de sesión único valide la sesión simultáneamente para la investigación documental.
- **Sincronización Total:** Actualizado en `backend/config.py` (`GOOGLE_LOGIN_PAGES` y `GOOGLE_LOGIN_URL`), `tools/mcp-setup/login-google-unificado.bat`, el acceso directo de escritorio `C:\Users\Johan\Desktop\VINCULAR-GOOGLE.bat`, y `tools/GoogleFlowMCP/src/chrome.js`.
- **Protección en `flow.js`:** `assertSignedIn` detecta de forma estricta redirecciones a `/about` o `accounts.google.com` y lanza un error descriptivo claro hacia el pipeline.

### C. Verificación Estricta Basada en Cookies CDP (`_cdp_has_google_auth`)
- **Inspección Real de Cookies en Chrome por CDP:**  
  Implementada la función asíncrona `_cdp_fetch_cookies_raw(port)` que consulta directamente el protocolo Chrome DevTools sobre WebSocket (`Storage.getCookies` y `Network.getAllCookies`) utilizando el cliente nativo `aiohttp` (con fallback a Playwright).
- **Criterio Estricto de Autenticación:**  
  La función `_cdp_has_google_auth(port)` inspecciona las cookies obtenidas y requiere que exista al menos una cookie de autenticación de Google con valor no vacío en el dominio `.google.com`:
  - `__Secure-1PSID`, `SID`, `__Secure-3PSID` o `SAPISID`.
- **Preflight Blindado:**  
  En `mcp_manager.py:_preflight`, Google Flow ya **no** se marca como `ok` si faltan estas cookies. Si el puerto 9333 está abierto pero no hay cookies de sesión, degrada de inmediato a `auth = "auth_required"` con detalle `"Sesión no iniciada: falta cookie __Secure-1PSID / SID en FlowImageChrome"`.
- **Captura sin Dependencia de Playwright:**  
  `capture_google_session()` utiliza `_cdp_fetch_cookies_raw` para volcar las cookies directamente en el `storage_state.json` de NotebookLM sin requerir que Playwright esté instalado en el entorno de Python 3.14.

### D. Interfaz de Usuario y Scripts de Soporte
- **Dashboard Web (`backend/static/app.js`):**
  - Añadido botón interactivo `🔧 Reparar Perfil` en la sección de Sesión Google unificada.
  - Al hacer clic, invoca `/api/mcp/repair-profile` y notifica al usuario con un toast de las acciones de reparación realizadas.
- **Scripts Batch Actualizados:**
  - `tools/mcp-setup/login-google-unificado.bat` y `VINCULAR-GOOGLE.bat` ejecutan auto-saneamiento antes de abrir Chrome y cargan las URLs oficiales con supresión de crash bubble.

---

## 3. Pruebas y Verificación

### A. Batería de Pruebas Específica INT-036 (`tests/test_int036_profile_heal_and_strict_auth.py`)
- **Auto-Heal:**
  - Creación de perfil con `Local State.bad`, 4 tipos de `lockfile`/`Singleton*` y `Preferences` con `"exit_type": "Crashed"`.
  - Verificada la eliminación completa de archivos residuales y la reescritura de `exit_type` a `"Normal"` y `exited_cleanly` a `True`.
  - Verificada la recuperación y regeneración de archivos de preferencias con JSON dañado o incompleto.
- **Landing OAuth:**
  - Verificada la presencia de las dos pestañas prioritarias con `accounts.google.com/ServiceLogin?continue=https://labs.google/fx/tools/flow`.
- **Verificación Estricta:**
  - Verificado que CDP abierto sin cookies de Google devuelve `auth_ok = False` y detalle de sesión faltante.
  - Verificado que cookies ajenas (ej. `example.com`) no autorizan el preflight.
  - Verificado que la presencia de `__Secure-1PSID` o `SID` valida el preflight y marca `auth = "ok"`.
- **Resultado:** **23 tests ejecutados, 23 OK, 0 fallos.**

### B. Pruebas de Regresión de la Suite Existente
- `tests/test_mcp_manager.py`: **38 OK · 0 fallos.**
- `tests/test_pipeline_orchestrator.py`: **56 OK · 0 fallos.**
- `tests/test_int025_google_session.py`: **73 OK.**

### C. Verificación en Vivo con Servidor Uvicorn
- Invocación de `POST /api/mcp/repair-profile`: responde HTTP 200 con `{ok: True, profile: FlowImageChrome}`.
- Invocación de `POST /api/mcp/test-pipeline` para `google-flow`: responde con `state: "auth_required"`, `auth: "auth_required"`, `browser_up: false` sin falsos positivos.
