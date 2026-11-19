# SES-2026-11-19-01 — Contexto Local de Respaldo por Nicho y Experimento de Cookies

- **Fecha:** 2026-11-19
- **Estado:** CLOSED / PASS
- **Autor:** Antigravity (DeepMind) & Usuario

---

## 1. Experimento de Cookies CDP vs RPC batchexecute (Parte 1)

Conforme a las directivas de seguridad estricta (cero impresión de secretos, claves, tokens o cookies; solo nombres, conteos y minutos):

1. **E-A (Respaldo):** Se respaldó de forma atómica `~/.notebooklm-mcp/auth.json`.
2. **E-B (CDP Network.getCookies):** En la pestaña activa de `notebook.google.com` (CDP 9333), la llamada a `Network.getCookies` con `urls=['https://notebook.google.com/']` devolvió 24 cookies de host específico, 0 duplicados de nombres de cookie.
3. **E-C (Prueba httpx estática con UA real):** Una petición `GET https://notebook.google.com/` con `httpx` (follow_redirects=True), enviando únicamente esas cookies de host y el User-Agent real de `/json/version`, devolvió **HTTP 200** y la URL final se mantuvo en `https://notebook.google.com/` (sin redirigir a accounts.google.com ni a CookieMismatch).
4. **E-D (Prueba RPC notebook_query):** La llamada RPC batchexecute falló con `400 Bad Request` debido al build label desactualizado de la librería upstream (`boq_labs-tailwind-frontend_20261112.11_p0` frente al frontend actual). El respaldo de `auth.json` fue restaurado intacto.
5. **E-E (Conclusión):**
   *E-C OK y E-D falla → otro factor (tokens/build): httpx en GET estático a notebook.google.com/ funciona con las 24 cookies de host específico (HTTP 200 sin CookieMismatch), pero las llamadas RPC batchexecute de notebooklm-mcp fallan por el build label desactualizado y desincronización de tokens f.sid/at en el paquete upstream.*

---

## 2. Contexto Local de Respaldo por Nicho (Parte 2 - BC)

Para dotar al pipeline de total autonomía frente a contingencias de sesión o caídas de upstream de NotebookLM:

1. **Fallback Automático en Etapa 1:**
   - Si la consulta a NotebookLM falla con error de autenticación/sesión expirada (`Authentication expired`, `re-authenticate`, `AUTH_REQUIRED`, `SESSION_INVALID`), el orquestador comprueba si existe `backend/data/nichos/<nicho_id>/contexto.md`.
   - Si existe, se carga automáticamente como contexto de investigación, se registra `context_source: "local"` y se emite un `log.warning`.
   - Si no existe, el pipeline falla con el error explícito `"Sin sesión de NotebookLM y sin contexto local del nicho '<nicho_id>'"` y código `CONTEXT_EMPTY`.
2. **Modo Directo Local (`PIPELINE_CONTEXT_SOURCE=local`):**
   - Si la variable de entorno o configuración `PIPELINE_CONTEXT_SOURCE` está fijada en `"local"`, el orquestador omite por completo cualquier consulta a NotebookLM en Stage 1 y su comprobación en el preflight gatekeeper, usando directamente el archivo de contexto local del nicho.
3. **Seguridad y Validación Estricta:**
   - `nicho_id` se valida contra la expresión regular `^[a-z0-9][a-z0-9_-]{0,40}$`.
   - Se previene activamente el path traversal mediante resolución canónica y verificación con `relative_to()`.
   - Se rechazan enlaces simbólicos (`is_symlink()`).
   - Se limita la lectura a un máximo de 64 KB en UTF-8 (`MAX_NICHO_CONTEXT_BYTES`).
4. **Batería Hermética y Suite Canónica:**
   - Se creó `tests/test_bc_contexto_local.py` cubriendo los 5 escenarios (fallback tras auth error, fallo limpio sin archivo local, salto total con `PIPELINE_CONTEXT_SOURCE=local`, rechazo de path traversal y corte en 64 KB).
   - Se integró en `tests/run_all.py` elevando el inventario canónico a **62 baterías**.
   - `ESTADO_REAL.md` y `ROADMAP.md` actualizados.
   - Trinquete `test_p2_2_except_ratchet.py` verificado (0 fallos, baseline preservado).
