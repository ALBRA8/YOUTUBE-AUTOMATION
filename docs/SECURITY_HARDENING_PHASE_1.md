# PHASE 1 — SECURITY & DATA INTEGRITY HARDENING (v2.20.0)

**Base:** `6609827` (Execution Contract V1.1, ext 2.4.1) · **Rama:** `phase1-security-hardening`
**Alcance:** exclusivamente vulnerabilidades de seguridad, integridad de datos y
aislamiento de proyectos detectadas por la auditoría consolidada. Cero cambios al
contrato creativo, a Creative Engine, a Reverse Engineering, a Muse (no implementado)
o al schema conceptual del Production JSON.

---

## 1. C1 — Delete project / path traversal (P0) — CORREGIDO

**Hallazgo (confirmado por runtime del canario):** `backend/main.py` ejecutaba
`shutil.rmtree(OUTPUT_DIR / pid, ignore_errors=True)` sin validar nada; el exploit
`DELETE /api/projects/%2e%2e` decodificaba a `..` y borraba `backend/data` completo
(DB, backups, token, .env).

**Causa:** el pid era parámetro de confianza cero tratado como componente de ruta.

**Corrección (política ÚNICA reutilizable, sin regex duplicados):**
- `security.validate_project_id(pid)` — formato canónico `^[0-9a-f]{12}$`
  (= `database.new_id()`). Un ID que no calce no puede existir ni en DB ni en
  disco: rechaza traversal (`..`, `%2e%2e`, `..\`), paths absolutos, slashes,
  NUL y caracteres inesperados EN UN SOLO LUGAR.
- `security.safe_project_output_dir(pid, must_exist=False)` — valida formato,
  resuelve la ruta y comprueba contención ESTRICTA dentro de `OUTPUT_DIR.resolve()`.
  Fail-closed; solo después de estos pasos se opera filesystem.
- `DELETE /api/projects/{pid}`: formato → existencia (404) → cancelación de job →
  ruta contenida → `rmtree` → `db.delete_project` (que ahora también purga
  `flow_jobs` — integridad, antes quedaban filas huérfanas reclamables).
- Aplicado a TODOS los endpoints que reciben `project_id` (21 superficies):
  GET/PATCH/DELETE project, cleanup, generate, subtitles.srt (M5), exports,
  import-flow, render-flow, reorder, publish, video_qa, preflight, flow enqueue,
  jobs/next, status/{pid}, extension/images, regen-image, patch-scene. El
  rechazo es 400 (formato) / 404 (inexistente); nunca 5xx.

**Archivos:** `backend/security.py`, `backend/main.py` · **Tests:**
`tests/security/test_project_path_security.py` (33 checks: los exploits del canario,
superficie completa, centinela de `backend/data` que sobrevive, handler real con
payload crudo).

## 2. M3 — IDOR entre proyectos (P0) — CORREGIDO

**Hallazgo:** un PATCH de scene modificaba una escena de OTRO proyecto (acceso por
`scene_id` sin verificar el padre).

**Corrección:** `database.get_scene_for_project(project_id, scene_id)` (SELECT
`WHERE id=? AND project_id=?`) y `update_scene(scene_id, project_id=...)` (UPDATE
scoped, rowcount 0 → 404). Endpoints: PATCH scene exige `project_id` en body
(400 si falta — el dashboard ya lo enviaba), GET scene image/audio exigen
`?project_id=` (dashboard actualizado: `<img>`, `<audio>`, cover_url del backend y
respuesta de regenerate). 404 en mismatch (sin filtrar existencia).
`/api/extension/images` rechaza registrar contra proyectos inexistentes (404).

**Archivos:** `backend/database.py`, `backend/main.py`, `backend/static/app.js` ·
**Tests:** `tests/security/test_project_isolation.py` (cross-project → 404, uso
legítimo → 200, sin filtrar existencia).

## 3. M7 — Job token / worker binding (P0) — CORREGIDO

**Hallazgo:** `job_token` era una credencial bearer sin expiración propia: filtrado
el token, cualquier tercero completaba/fallaba el job; ni `worker` ni vigencia de
lease se verificaban.

**Corrección (preservando BEGIN IMMEDIATE, nonce, rowcount condicional y leases):**
guardia única `_claimed_by_token(con, job_id, token, worker=None, require_lease=False)`
— siempre `status='claimed' AND job_token=?`; `worker is not None` añade `AND
worker=?` (fail-closed: `""` jamás coincide); `require_lease=True` añade
`AND lease_until >= ahora`. En el borde HTTP (`heartbeat`/`complete`/`fail`)
`worker` es OBLIGATORIO (400 si falta) y verify-if-provided en
`progress`/`generate-consent`. Una lease vencida rechaza las tres operaciones
aunque el token siga en la fila. Compat: llamadas posicionales históricas
(worker=None) mantienen comportamiento; la extensión 2.4.2 envía
`&worker=cfg.workerId` en las 5 operaciones (bridge.js).

**Archivos:** `backend/services/flow_jobs.py`, `backend/main.py`,
`extension/bridge.js`, `extension/manifest.json` (2.4.2) · **Tests:**
`tests/security/test_job_identity.py` (worker B rechazado, token falso, lease
vencida, sin worker → 400, flujo legítimo intacto).

## 4. M8 — Job ↔ Flow project binding (P0) — REGISTRADO HONESTAMENTE

**Hallazgo:** no existe identidad verificable de proyecto/sesión de Google Flow;
un asset se asociaba por numeración de escena sin comprobación de ejecución.

**Corrección sin inventar identidad:** columna `flow_jobs.binding_json` (migración
idempotente); en `complete()` (misma transacción) se persiste el binding v1
verificable de la ejecución: `{albra_project_id, job_id, scene_number, worker,
asset_sha256, flow_identity_state: "not_verifiable", flow_identity: null,
recorded_at}`. La identidad de Flow queda declarada `not_verifiable` SIEMPRE (Flow
no expone identidad fuerte hoy; NO se fabrica). El binding verificable v1 es
job+worker+token+lease (M7). Ninguna operación exige hoy binding fuerte; si una
fase posterior lo define, la columna ya distingue ejecuciones. Extensión de jobs:
`db.delete_project` elimina sus flow_jobs; `/api/extension/images` ya no registra
assets huérfanos contra proyectos inexistentes.

**Archivos:** `backend/database.py`, `backend/services/flow_jobs.py`,
`backend/main.py` · **Tests:** `tests/security/test_job_identity.py` (binding
persistido con sha256 y `not_verifiable`).

## 5. A1 — SSRF redirect bypass — CORREGIDO

**Hallazgo:** `_http_probe` (production_doctor/layers.py) validaba la 1ª URL pero
request con `urlopen` directo seguía hasta 10 redirects SIN revalidar
(público→privado pasaba); eco de 120 bytes de respuestas internas; y
`safe_fetch_bytes` descargaba sin tope.

**Corrección (sin duplicar implementaciones):** `security.safe_urlopen(url, timeout,
allow_private, headers)` — el opener con `_SafeRedirectHandler` revalida CADA salto
con `validar_url` (DNS resuelto por hop; bloquea loopback/127/8/::1/0.0.0.0/
link-local/RFC1918/metadatos/reservadas/multicast/unspecified/IPv4-mapped-IPv6 y
hosts que resuelvan a IP privada). `_http_probe` usa el opener central (el eco
solo puede venir de destinos ya validados). `safe_fetch_bytes(..., max_bytes=)`
rechaza descargas sobre tope. Conservado: `validar_url`, `SafeRedirectHandler`,
semántica `trusted_private` (solo relaja private/loopback, JAMÁS link-local).

**Archivos:** `backend/security.py`,
`backend/services/production_doctor/layers.py` · **Tests:**
`tests/security/test_ssrf.py` (matriz completa + redirect-handler unit + sonda
HTTP REAL contra servidor loopback que redirige a 169.254 → bloqueado).

## 6. A8 — yt-dlp SSRF — CORREGIDO

**Hallazgo:** `url_mode.py` entregaba URLs de usuario crudas a yt-dlp sin ninguna
validación (file://, LAN, metadatos pasaban).

**Corrección:** guardia `url_mode._guard_ssrf(url)` = `security.validar_url`
invocada en `fetch_metadata`, `download_audio` y `transcript_from_url` (esta última
valida la URL YA limpia). La política SSRF es de ALBRA, no de yt-dlp. Además
`POST /api/projects` (mode=url) valida con `security.validar_url` → 400 temprano.

**Archivos:** `backend/services/url_mode.py`, `backend/main.py` · **Tests:**
`tests/security/test_ssrf.py` (file://, metadatos, LAN → ValueError; el pipeline
rechaza antes de invocar yt-dlp).

## 7. M2 — CSRF — CORREGIDO

**Hallazgo:** endpoints mutables aceptaban requests cross-origin sin protección
(confirmado por runtime).

**Corrección (política clasificada, cero ruptura):** middleware `csrf_guard` —
MUTATING (POST/PUT/PATCH/DELETE) con Origin/Referer presente debe pasar
`security.origin_allowed` (mismo host · `http(s)://localhost|127.0.0.1|[::1]:puerto`
· `chrome-extension://` con ID válido); origen externo o `null` → 403. Sin
Origin/Referer (curl, API clients, workers) se permite: los navegadores SIEMPRE
envían Origin en mutaciones cross-site. SAFE_READ (GET/HEAD/OPTIONS) sin chequeo.
CORS intacto (regex extensión+local, sin credenciales). Además el middleware
rechaza `Content-Length > LIMITS["MAX_BODY_BYTES"]` con 413 (anti-DoS).

**Archivos:** `backend/main.py`, `backend/security.py` · **Tests:**
`tests/security/test_csrf.py` (evil.example → 403, referer → 403, null → 403,
local/extensión/same-host/sin-Origin → permitidos, GET no se protege, 413).

## 8. M1 — Docs / OpenAPI auth — CORREGIDO

**Hallazgo:** `/docs`, `/redoc`, `/openapi.json` (y `/mcp/docs`) quedaban fuera de
`auth_guard` incluso con MASTER_API_KEY.

**Corrección:** `auth_guard` extendido a `/docs`, `/redoc`, `/openapi.json` y sus
subrutas (`/docs/oauth2-redirect` incluido) con las 4 vías de clave existentes
(header/cookie/bearer/query). Sin clave configurada (modo local) siguen abiertas:
cero ruptura. Documentación NO eliminada.

**Archivos:** `backend/main.py` · **Tests:** `tests/security/test_docs_auth.py`
(sin auth → 401; con X-API-Key/Bearer → 200; modo local abierto; health pública).

## 9. A2 — .env newline injection — CORREGIDO

**Hallazgo:** `config.save_env` escribía valores crudos: un valor con `\r/\n`
inyectaba variables nuevas en `.env` (p. ej. `NVIDIA_MODEL=x\nMASTER_API_KEY=pwn
\nNVIDIA_BASE_URL=http://atacante` — exfiltración de prompts/claves al reiniciar).

**Corrección:** validación central `security.validate_env_value(key, value)` —
rechaza EXPLÍCITAMENTE (ValueError, sin sanitizar en silencio) `\r`, `\n` y NUL en
cualquier valor destinado a `.env`; `config.save_env` la invoca; `POST /api/config`
responde 400 y no escribe nada. Claves legítimas siguen guardándose/aplicándose
al instante.

**Archivos:** `backend/security.py`, `backend/config.py`, `backend/main.py` ·
**Tests:** `tests/security/test_config_security.py` (inyección → ValueError/400,
el .env queda intacto, valor legítimo sigue aplicando).

## 10. Límites de entrada (A7/A9/M10/M11) — CORREGIDOS

Centralizados y configurables (`.env` con defaults seguros) en `config.LIMITS`
(leídos en runtime): `MAX_BODY_BYTES` 64MB · `MAX_UPLOAD_JSON_BYTES` 2MB ·
`MAX_ZIP_COMPRESSED_BYTES` 150MB · `MAX_ZIP_UNCOMPRESSED_BYTES` 600MB ·
`MAX_ZIP_FILES` 300 · `MAX_IMAGE_PIXELS` 40M · `MAX_PRODUCTION_UNITS` 40 (≈
guion_json.MAX_ESCENAS) · `FLOW_JOB_BODY_BYTES` 64MB ·
`FLOW_JOBS_RETENTION_DAYS` 30 · `LEDGER_MAX_LINES` 5000.

- **A7 zip bombs:** `import-flow` lee el upload CON TOPE (streaming → 413) y
  `flow_import` valida nº de entradas y tamaño DESCOMPRIMIDO declarado ANTES de
  leer un byte (42.zip ya no agota RAM). Anti zip-slip intacto.
- **A9 production JSON:** `validate()` rechaza > MAX_PRODUCTION_UNITS con
  ValueError explícito (→400); `parse_payload` captura RecursionError
  (JSON ultranidado → 400, nunca 500).
- **M10 imagen:** `security.harden_pil(MAX_IMAGE_PIXELS)` fija el techo global de
  Pillow al importar la app (DecompressionBombError → 4xx/422); uploads y bodies
  con tope de streaming en `client-secret`, `import-flow` y `flow complete`.
- **M11 ledgers:** rotación idempotente del ledger de Flow Adaptation (cola 60%
  del tope, tmp+os.replace); purga con retención de `flow_jobs` done/dead >
  FLOW_JOBS_RETENTION_DAYS dentro de `recover_expired` (misma tx, idempotente).

**Archivos:** `backend/config.py`, `backend/security.py`, `backend/main.py`,
`backend/pipeline/flow_import.py`, `backend/services/production_json.py`,
`backend/services/flow_adaptation.py`, `backend/services/flow_jobs.py` ·
**Tests:** `tests/security/test_input_limits.py`.

## 11. M4 — Malformed body → 500 — CORREGIDO

`regenerate-image` usaba `body["project_id"]` directo (KeyError→500, confirmado):
ahora `.get()` + `_pid` → 400/404. `render-flow` comprueba existencia (antes
ValueError→500). `publish/exchange` captura el fallo OAuth (→400). PATCH scene sin
campos → 4xx controlado. Regla: ninguna entrada externa indexa claves sin guardia.

**Tests:** `tests/security/test_input_limits.py` ({}, null, tipo incorrecto, campo
ausente → 4xx siempre).

## 12. M5 — Subtitle path traversal — CORREGIDO

`GET /api/projects/{pid}/subtitles.srt` construía `OUTPUT_DIR / pid / "words.json"`
sin validar: ahora pasa por `_pid` + `safe_project_output_dir` (formato canónico +
contención estricta). Un proyecto solo puede leer SUS archivos permitidos.
**Tests:** `test_project_path_security.py` (traversal → 400/404).

## 13. M6 — Meta patch / system-owned state — CORREGIDO

**Hallazgo:** `meta_patch` aceptaba CUALQUIER clave: se podía falsificar
`meta.qa_final` (gate de publicación) y escribir `publish_state`/rutas arbitrarias.

**Corrección:** separación explícita — `_SYSTEM_META_KEYS` (qa_final, publish_state,
publish_error, youtube_id, audio_path, video_url, thumbnail_url, exec_state,
execution_state, contract_result, binding, asset_validity, publishability) → 403
si se intentan vía meta_patch; TODO lo demás sigue editable (transitions,
subtitle_style, ideas, custom prompts…). El estado de confianza lo emite el
backend (QA, publish, Execution Contract).

**Tests:** `test_project_isolation.py` + `test_config_security.py` (spoof → 403,
legítimos → 200 aplicados).

## 14. M9 — Chat confirm / fuzzy delete — CORREGIDO

**Hallazgo:** `/api/chat` confirm ejecutaba `delete_project` por fuzzy matching
(substring any-word, primer match) y el borrado por chat ni siquiera limpiaba el
filesystem (carpetas huérfanas).

**Corrección:** acciones destructivas NUNCA fuzzy — exigen `project_id` exacto y
validado; si solo llega nombre, único puente de compatibilidad = título EXACTO
único (case-insensitive); 0 o ≥2 candidatos → NO se ejecuta y se listan los
candidatos con sus ids. El borrado usa el MISMO pipeline seguro que DELETE REST
(`safe_project_output_dir` → rmtree → `db.delete_project` con purga de flow_jobs).
`cleanup_failed` opera por estado exacto en DB con el mismo pipeline.

**Archivos:** `backend/services/agent.py` · **Tests:**
`test_project_isolation.py` (ambiguo → rechazo con candidatos y el proyecto
sobrevive; exacto → ejecuta).

## 15. A6 — Job expiration / queue recovery — CORREGIDO

**Hallazgo:** leases vencidas solo se reciclaban en el PRÓXIMO claim (con la
extensión parada quedaban claimed indefinidamente) y en la extensión un
RATE_LIMITED con el Service Worker muerto quedaba zombi estancando la cola local
(`__bridgeHandleJob` rechazaba todo mientras existiera).

**Corrección:** backend — `status_for_project` ejecuta `recover_expired()`
(idempotente, BEGIN IMMEDIATE) en cada consulta: la extensión desatasca leases
vencidas sin esperar un claim. `enqueue_project` y `delete_project` no dejan
huérfanos. Extensión 2.4.2 — `armRateLimitRestore()` idempotente re-armado en
`loadState` y en `tick()` (condición sin check temporal: si el SW durmió más que
el cooldown igual restaura), `clearTimeout` donde el cooldown se anula. Se
preservan íntegros: leases, lease_cycles, zombie recovery, MAX_ATTEMPTS,
MAX_LEASE_CYCLES.

**Archivos:** `backend/services/flow_jobs.py`, `extension/background.js` ·
**Tests:** `test_job_identity.py` (recuperación idempotente por consulta),
`test_live_boot.py` (34 OK), `test_extension_*` (65/58 OK).

---

## Suite y reproducibilidad

- **Nuevas baterías (`tests/security/`, 8 archivos, 154 checks, runtime HTTP real
  con httpx.ASGITransport sobre la app FastAPI completa):** 154 OK · 0 fallos.
  Python puro — reproducibles en Windows con `pytest` (sin Node, sin bash, sin
  lifespans); cada una aísla DB/OUTPUT en `tempfile.mkdtemp` parcheando `config`
  ANTES de importar (binds por valor). NO se mockea la función protegida: los
  exploits pasan por el HTTP real (`%2e%2e` incluido, más llamada directa al
  handler real para el target crudo de un proxy hostil).
- **Regresión completa:** 42 baterías en verde (34 existentes + 8 security),
  incluidas contract (77/93/99/55), hands (121/58/33/55), concurrencia/chaos,
  10 escenas, golden fixture, bridge_e2e, extensión (65/58/70), live boot real
  (34), production JSON (76), doctor (54/48), security_hardening histórico (47).
  Ajustes de compatibilidad en tests: ids de fixtures migrados al formato
  canónico 12-hex (`test_flow_bridge`, `test_autopublish_generate`), worker en
  curls del smoke (`live_cycle_smoke.sh`), expectativa de versión 2.20.0
  (`test_merge_216_pyav`), verificación PHASE 1 del Production JSON endurecido
  (`test_flow_observability_v11` — contrato creativo intacto verificado por
  marcadores canónicos), manifest 2.4.2 (2 asserts).

## Integridad del alcance

- Sin cambios en: Creative Engine (guion_json.py byte-idéntico — verificado por
  la batería de observabilidad), themes, niches, flow_export, prompts, Reverse
  Engineering, contrato conceptual del Production JSON (schema 1.0 intacto; solo
  límites de seguridad en la puerta), HANDS (aislamiento intacto),
  `security.validar_url`/`SafeRedirectHandler` (conservados y ahora sí usados por
  todos), `safe_filename`, PathBoundary, QA gate, publish idempotente, Execution
  Contract V1.1 (estados, gate §7.1, terminales CONFIG_*), Production JSON
  adapter, compatibilidad legacy guion_json.
- `BEGIN IMMEDIATE`, nonce job_token, rowcount condicional, leases, lease_cycles,
  zombie recovery, whitelists de columnas y SQL parametrizado: intactos y ahora
  con binding de identidad.

## Riesgos restantes (honestos, para fases posteriores)

1. **DNS rebinding TOCTOU** en `validar_url` (documentado en su docstring): la IP
   se resuelve al validar y el socket re-resuelve al conectar. Mitigación real:
   egress firewall — fuera del alcance de esta fase.
2. **Identidad de proyecto Flow no verificable** (M8): el binding queda registrado
   como `not_verifiable`; una identidad fuerte exigiría cooperación del proveedor.
3. **MASTER_API_KEY sigue siendo opt-in** (modo local abierto por diseño): la
   política CSRF mitiga el navegador, pero un despliegue expuesto debe fijar
   clave (documentado en security.py).
4. **Rate limiting por IP/clave** no implementado (no estaba en el alcance P0/P1
   de esta fase; el tope de body y los límites de input reducen la superficie).
5. **`hands/flow_operator.urlopen`** sin guardia: objetivo 1st-party de config y
   driver deshabilitado por diseño (§37) — se conserva el aislamiento HANDS.
6. **`--cookies-from-browser`** sigue permitido (funcionalidad legítima local;
   whitelist de navegadores ya existente).
7. **Retención de `memorydv` y `hands evidence`** sin rotación (crecen lento;
   el ledger crítico ya rota).
