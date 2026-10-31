# INT-071 — Google One-Tap Hub · «[G] Continuar con Google»

- **Fecha:** 2026-10-31.
- **Estado:** IMPLEMENTADO / batería **18/18** · suite pytest **226/226** (antes 208). Validación visual y con Chrome real → Antigravity.
- **Origen:** petición directa del propietario: la pestaña `#mcp` mostraba 5 botones técnicos dispersos y códigos de depuración (CDP 9333, bytes de storage) dentro de `#gsess-card`; se pide una tarjeta única con el botón oficial de Google y transformación automática a panel de perfil al conectar.

## 1. Problema y diseño

**Antes (INT-025/043):** 5 acciones técnicas ("Iniciar Chrome y Conectar Todo", "Abrir Ventana de Chrome", "Capturar sesión → NotebookLM", "Reparar Perfil", "Refrescar estado") + diagnóstico crudo (puerto, bytes). El usuario no debería necesitar entender CDP ni storage_state.

**Ahora — UNA tarjeta, DOS estados:**

- **ESTADO A · DESCONECTADO:** botón oficial de Google (SVG multicolor con los 4 arcos de marca, fondo blanco, borde `#dadce0`, tipografía `Google Sans/Roboto` en `#3c4043`, pill redondeada) + subtítulo: *"Inicia sesión una sola vez para conectar automáticamente Google Flow (VideoFX/ImageFX), NotebookLM (Investigación y Studio) y tu Google Drive"* + footer discreto (Reparar perfil / Refrescar).
- **Transición:** al pulsar → `POST /api/mcp/google-sso`: abre el Chrome del perfil global (CDP 9333 intacto) en **`https://accounts.google.com/AccountChooser?service=lso&continue=https://labs.google/fx/tools/flow`** + 2ª pestaña NotebookLM; el backend arranca un **watchdog** (poll `GOOGLE_SSO_POLL_S=2` s) que comprueba por CDP la cookie de autenticación (`__Secure-1PSID` / `SID` / `__Secure-3PSID` / `SAPISID`, reutiliza `_cdp_has_google_auth`). Al detectarla: captura cookies → `storage_state.json`, conecta MCP de Flow y de NotebookLM, y extrae el correo/nombre de la cuenta. El frontend muestra mientras tanto un estado "Esperando tu inicio de sesión…" con pulso y polling de 2 s.
- **ESTADO B · CONECTADO:** cabecera de perfil (avatar con inicial en gradiente azul→violeta #1a73e8→#7c5cff, nombre legible derivado del correo, email) + badge verde "🟢 Ecosistema Google Conectado" + **3 pills** (Google Flow · CDP 9333, NotebookLM MCP · N tools, Google Workspace & Gemini · misma sesión) + acciones rápidas: **📂 Ver mis Notebooks** (puebla el desplegable y hace scroll), **🌐 Abrir Chrome** (reutiliza la ventana del perfil), **🚪 Cambiar cuenta / Desconectar**.
- **Header global:** las pills `Flow` / `NotebookLM` del header se pintan verdes vía `updatePills()` (sin cambios en index.html; `gsessApply` llama `mcpRefresh(true)` al conectar).

## 2. Backend (aditivo — cero endpoints rotos)

| Pieza | Cambio |
|---|---|
| `backend/services/mcp_manager.py` | NUEVO bloque INT-071: `google_sso_start()`, `_sso_watchdog()` (asyncio task, fail-soft total, timeout `GOOGLE_SSO_TIMEOUT_S=900` → phase=timeout, nunca bloquea el backend), `_sso_finish_connect()` (captura + conexión + cuenta; `NO_GOOGLE_COOKIES` vuelve a watching), `google_sso_status()` (fase, cuenta, pills por servicio, regla honesta de CONECTADO: cookie viva O watcher conectado — sobrevive reinicios del backend), `google_sso_logout()` (cancela watcher, desconecta MCPs, ARCHIVA storage como `.bak-<ts>` — nunca destruye cookies sin copia — y cierra el Chrome del perfil), `google_account_info()` (2 estrategias fail-soft: targets CDP `/json/list` → HTML de `SignOutOptions` vía Playwright en thread), `_cdp_list_targets()` |
| Funciones puras (testeables sin red) | `_account_from_email()`, `account_from_html()`, `account_from_targets()` — parseo de cuenta con filtro de falsos positivos (`example`, `domain.com`…) |
| `backend/main.py` | 3 endpoints nuevos: `POST /api/mcp/google-sso` · `GET /api/mcp/google-sso/status` · `POST /api/mcp/google-sso/logout`. Los legacy (`login-google`, `connect-all-google`, `capture-google-session`, `launch-auth-browser`, `launch-clean-login`, `repair-profile`) quedan intactos (test de regresión de rutas) |
| `backend/config.py` + `.env.example` | `GOOGLE_SSO_URL` (AccountChooser→Flow), `GOOGLE_SSO_POLL_S=2`, `GOOGLE_SSO_TIMEOUT_S=900` |
| Estado | `self._sso` en `__init__` (`phase/started_at/error/account/task` — el task NUNCA se serializa a la UI) |

**Invariante preservado:** puerto `9333` (`GOOGLE_LOGIN_CDP_PORT = FLOW_CDP_PORT`), perfil `%LOCALAPPDATA%/FlowImageChrome`, persistencia de cookies en el storage_state de notebooklm-py, pipeline de `video_assembler.py` sin tocar (0 líneas cambiadas).

## 3. Frontend

| Fichero | Cambio |
|---|---|
| `backend/static/app.js` | Bloque INT-025 sustituido por el Hub: `mcpGsessHTML()` (markup mínimo con `#gsess-body` dinámico), `gsessStart()`, `gsessApply()` (máquina de 2 estados + badge), renders (`gsessDisconnectedHTML` / `gsessWaitingHTML` / `gsessConnectedHTML`), polling (`gsessStartPoll`/`gsessStopPoll` — 2 s solo durante la espera, se autodetiene al conectar o al salir de `#mcp`), acciones (`gsessOpenNotebooks`, `gsessOpenChrome`, `gsessLogout`), `G_LOGO_SVG` oficial. Eliminadas las funciones muertas (verificado con grep: cero referencias). `gsessRepairProfile` conservada en el footer |
| `backend/static/style.css` | `.gbtn` (botón oficial con hover/active/disabled según brand), `.ghub-avatar`, `.ghub-pills/.ghub-pill(.on/.off)`, `.ghub-pulse` (animación de espera), `.ghub-actions`, `.ghub-foot` — integrado en la paleta dark existente (`--ok`, `--card`, `--border`) |

## 4. Verificación

- Batería INT-071 (`tests/test_int071_google_hub.py`): **18/18** — extracción de cuenta (7), arranque SSO con URLs AccountChooser+NotebookLM (1), watchdog: conexión al detectar cookie / NO_GOOGLE_COOKIES→watching→timeout / error de MCP no rompe (3), status: fase connected con alias honesto + watching gana + task nunca serializado (2), logout: cancela watcher + archiva storage `.bak` + desconecta (1), endpoints REST con TestClient (3), regresión de rutas legacy (1).
- **Bug capturado por la batería:** `account_from_targets` usaba `group(1)` también en el regex genérico (sin grupos) → `IndexError` con email en el título de la pestaña; corregido con selección explícita de grupo y aserción de regresión.
- Suite completa: **226/226** (antes 208). Hermeticidad: cero red, cero Chrome, cero Playwright.

## 5. Límite honesto

Los 2 estados y el watchdog están verificados con tests y mocks; el ciclo completo con **Chrome real** (elegir cuenta en el AccountChooser, ver la detección en ~2 s, la extracción del correo y las pills verdes) pertenece a la sesión de Antigravity: arrancar backend, abrir `http://localhost:8000/#mcp` y recorrer Estado A → espera → Estado B → Desconectar. Si la cuenta no aparece (Google cambia el HTML), el Hub degrada con elegancia a "Cuenta Google" sin bloquear nada.
