# SESSION INDEX — índice de sesiones de trabajo

> Registro cronológico de sesiones con su alcance, commit y resultados
> literales. Una sesión sin entrada aquí no ocurrió.

---

## Sesión 2026-11-26 · CIERRE BN (claves desconocidas → 422 con sugerencia; alias Gemini «-latest» por v1beta)

- **Base**: `a7dfb9e` (main, árbol limpio). Entorno: clon Linux del sandbox
  (Python 3.12.16); `backend/.venv` recreado desde el lock tras el reciclaje
  del sandbox → guardia F1 33 OK · 0 fallos.
- **BN1** — `POST /api/pipeline/run` RECHAZA claves de primer nivel
  desconocidas con **422** + sugerencia difflib (literal:
  `external_blueprint` → «¿quisiste decir 'blueprint'?») + catálogo
  «Claves válidas: blueprint, format, idea, max_scenes, nicho_id,
  notebook_id, style». Antes se ignoraban en silencio y la etapa 2 caía en
  Gemini gastando la corrida. Whitelist `_CLAVES_PIPELINE_RUN` +
  `_sugerencia_clave()` en `backend/main.py`; la validación corre ANTES del
  orquestador (`create_run` jamás se invoca con payload inválido; sugerencias
  sin falsos positivos). Las 7 claves válidas siguen aceptándose (corrida
  externa completa 200).
- **BN2** — google-genai 3.6.1 rutea TODO por `GOOGLE_AI_API_DEFAULT_
  VERSION='v1'`, pero los alias «-latest» (gemini-flash-latest / -lite-
  latest / pro-latest) solo están publicados en **v1beta** → 404 NOT_FOUND
  injusto que quemaba el candidato sano (vivo 2026-11-19: flash-latest 404
  por v1, 3.8-flash 200). Ahora `gemini_client.generate_json/generate_text`
  intenta la familia `-latest` **PRIMERO por v1beta** con **HttpOptions POR
  REQUEST** (cliente global intacto); solo ante 404 se agota también v1
  (prueba ambas versiones antes de descartarlo); 429/503 sin segunda versión
  → siguiente candidato BG1; modelos no-alias: UN intento con la versión
  default (BD 2C intacto). URL literal capturada sin red: `…/v1beta/models/
  gemini-flash-latest:generateContent` (y `…/v1/models/gemini-3.8-flash:…`).
  Sin cambios en `flow_export._MODEL_CANDIDATES` ni
  `config.DEFAULT_GEMINI_FALLBACKS`.
- **Batería nueva**: `tests/test_bn_pipeline_keys_y_gemini_v1beta.py`
  (13 checks herméticos, standalone «13 OK · 0 fallos»), registrada en
  `BATERIAS` → 73 baterías. Regresión directa: BD+BG+BM+orchestrator+bb5
  = 61 passed.
- **Verificación y suites**: compileall exit 0; ruff (F821,E9,F63,F7,F82)
  All checks passed!; pytest COMPLETO **983 passed, 2 warnings** (138.75 s);
  run_all `--workers 6` **3016 OK · 0 fallos · 0 SKIP en 73 baterías**
  (exit 0, doble corrida idempotente); npm test GoogleFlowMCP **38/38**;
  lock_drift 33 OK · 0 fallos; auditoria_repairs 46 OK · 0 fallos;
  import main 404/415/423 ms; BD real sha256/mtime/size idénticos
  (9afa69dd9cb924e2… / 1795461897 / 114688 B).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-24 · CIERRE BM (blueprint externo: video_prompt y subtitle_text)

- **Base**: `f4c6025` (main) + cambios BL (resiliencia de startFrame por nombre/id y reintentos de imagen).
  Entorno: Windows (Python 3.14.3).
- **BM1**: Validación de blueprint externo en `backend/services/pipeline_orchestrator.py`:
  - `video_prompt` opcional (<=600 caracteres) y `subtitle_text` opcional (<=200 caracteres).
  - Validación de string estricta, caracteres de control de categoría Unicode `Cc` eliminados en normalización declarada.
  - Rechazo con código `INVALID_BLUEPRINT` si no es string, si se superan los límites de longitud o si se introducen claves no permitidas.
- **BM2**: Etapa 3 (`_stage3`):
  - Si la escena contiene `video_prompt`, se usa directamente como el prompt de `flow_generate_video` tal cual.
  - Si no está presente, se mantiene la composición tradicional (`image_prompt` + movimiento de cámara y acción + `narration[:300]`).
- **BM3**: Etapa 4 (`asset_harvester.py` y `video_assembler.py`):
  - `harvest_scenes`: `entry["subtitle_text"]` preserva el texto limpio si existe, con fallback a `narration` cuando no existe.
  - `plan_render`: la entrada de la escena en `scene_plans` lleva `"subtitle_text"` cuando existe; si no existe, conserva el comportamiento actual.
  - Subtítulos quemados (`build_srt` y `karaoke_subtitles.build_ass_from_scenes`): usan `subtitle_text` y NO la narración con direcciones de voz.
- **BM4**: `/api/pipeline/status` y `orchestrator.get_status`:
  - Exponen `video_prompt` y `subtitle_text` en cada escena devuelta (con backfill automático a `""` para corridas previas).
- **Verificación y Suites**:
  - `tests/test_bm_external_blueprint_video_prompt.py`: 6 checks herméticos cubriendo BM1, BM2, BM3 y BM4.
  - `npm test --prefix tools/GoogleFlowMCP`: 38 tests, 38 pass, 0 fail.
  - `compileall`: exit code 0 en backend y tests.
  - `ruff (F821,E9,F63,F7,F82)`: All checks passed!
  - `pytest` COMPLETO: 970 passed, 4 skipped, 0 failed.
  - `tests/run_all.py`: 72 baterías registradas en `BATERIAS`.

---

## Sesión 2026-11-24 · CIERRE BK1-BK2 + BK3 (calentamiento Stage 3, D7 sin DNS, lock↔venv, lipo)

- **Base**: `b1012c1` (main, árbol limpio; luego `8f9c8d8` para BK3).
  Entorno: clon Linux del sandbox (Python 3.12.16).
- **BK1**: el calentamiento Stage 3 (`_stage3`, D2) ya no usa `timeout=30.0`
  para `flow_list_assets` — helper `_flow_warm_timeout()` =
  `FLOW_CDP_CONNECT_TIMEOUT_MS/1000 + 30` (**150 s por defecto**, misma
  constante y default 120000 ms que el MCP server `chrome.js`), con los MISMOS
  2 intentos; política del JS replicada (vacío/0/negativo/NaN → default).
  Test hermético: 11 checks nuevos en `test_be_flow_cdp_stability.py`
  (fórmula 60000→90/30000→60/180000→210; inválidos→150; USO REAL: la llamada
  de calentamiento pasa 150.0/90.0 s al manager doble) → batería 18 passed.
- **BK2**: el check D7 de `test_registro_baterias.py` apunta a la IP literal
  **192.0.2.1** (RFC 5737 TEST-NET-1) en vez de `example.com` —
  `getaddrinfo` con IP numérica no consulta DNS: el check ya no depende de
  resolución de nombres; la guardia sigue quemando el `connect()` no-loopback
  («hermética D7»). Guardián standalone: **20 OK · 0 fallos**.
- **Commit BK1-BK2**: `8f9c8d8` — push `b1012c1..8f9c8d8`; CI verde
  (run 45279582164: `ci` success 4m26s + `ci-windows` success 7m02s).
  Gates literales: compileall exit 0; ruff F821,E9,F63,F7,F82 «All checks
  passed!»; pytest COMPLETO **964 passed, 1 warning**; run_all serie
  **2994 OK · 0 fallos · 0 SKIP en 71 baterías**; BD real sha256/mtime/size
  idénticos antes/después (`9afa69dd9cb924e2…` / 114688 B).
- **BK3 (lock ↔ venv real, sin tocar versiones)**: el reciclaje del sandbox
  dejó el intérprete de cierre sin 10 pins del lock (google-genai, edge-tts,
  yt-dlp, faster-whisper, ctranslate2, onnxruntime, av, google-api-*,
  google-auth*) → re-instalados EXACTOS con `pip install -r
  backend/requirements-lock.txt` («Successfully installed av-18.1.0
  ctranslate2-4.9.0 … google-genai-3.6.1 … yt-dlp-2026.10.26»);
  `opencv-python-headless==4.13.0.90` y `psutil==7.2.2` con import real OK.
  **Hueco P4.2 residual cerrado**: `aiohttp==3.13.3`, `beautifulsoup4==4.14.3`
  y `playwright==1.57.0` estaban IMPORTADOS por backend (mcp_manager.py ×6,
  ugc_ad_generator.py:101) sin estar en lock/requirements/dev → añadidos al
  lock (26→29 pins, sección BK3 con consumidores citados) y a
  requirements.txt (protocolo del propio lock, tras suite verde). El freeze
  crudo del intérprete de cierre (430 dists) se descarta a propósito como
  lock: incluiría tooling de test/sandbox que rompería la guardia en la
  máquina del dueño y el CI.
- **BK3 lipo (dry-run primero)**: `podar_google_profile.py` → 0.0 MB en el
  clon (perfil placeholder 4.0 KB; el 254.7 MB real es solo del dueño) y
  `--ejecutar` exit 0 con Cookies/Login Data/Preferences intactos;
  `dedup_biblioteca.py` → 0 copias convertibles (biblioteca 36 KB en el clon;
  122.2 MB reales del dueño) y `--ejecutar` exit 0; `backend/.venv_3.14_roto`
  AUSENTE (artefacto del dueño, cerrado en F2).
- **Resultados literales BK3**: guardia F1 standalone **33 OK · 0 fallos**
  (exit 0, 29 pins); `python tests/run_all.py` — **2997 OK · 0 fallos ·
  0 SKIP en 71 baterías**; pytest COMPLETO **964 passed, 1 warning** (z4-ruff
  cazó que el reciclaje borró `ruff` del venv → reinstalado 0.17.6, gate
  verde; z4 está en EXCLUDED_BATTERIES — solo corre bajo pytest, por eso
  run_all no lo vio); BD real intacta. Nota honesta: los pasos con
  `backend\.venv\Scripts` y `Remove-Item` son solo de la máquina del dueño
  (Windows) — aquí se ejecutó el equivalente POSIX completo.
- **Commit BK3**: ver `git log -1` (hash en el cierre de la sesión).

## Sesión 2026-11-23 · CIERRE F1-F10 (últimos huecos, lipo, CRLF y CI Windows)

- **Base**: `c3de757` (main, árbol limpio). Mandato: cerrar los ÚLTIMOS huecos
  para declarar el sistema 100% operativo (F1-F10). Entorno: clon Linux del
  sandbox (Python 3.12.16); los 860 MB de la lipo viven SOLO en la máquina del
  dueño — mecanismo probado aquí + comandos exactos entregados.
- **F1**: guardia NUEVA `tests/security/test_lock_drift.py` (30 checks) — los
  27 pins del lockfile vs `importlib.metadata` del intérprete EN EJECUCIÓN;
  negativo demostrado con lockfile sintético («✗ paquete-fantasma==9.9.9 —
  FALTA en el venv», exit 1). Registro: BATERIAS + PYTEST_IGNORADAS → 71
  baterías. El propio sandbox tenía drift (av/ctranslate2/onnxruntime/
  faster-whisper/google-* sin instalar) — la guardia lo habría cazado.
  Aceptación con uvicorn VIVO y BD aislada por env: badge/callout/
  studio-preview/circle-pip → HTTP 200 con PNGs (`\x89PNG`); hash de la BD
  REAL idéntico antes/después. `.gitignore` + `backend/static/studio_previews/`.
- **F2**: `.venv_3.14_roto` AUSENTE en el clon; alcance del mandato
  (launchers/workflows/md raíz/backend py-txt) → 0 referencias; en todo el
  repo solo se auto-referencian los 2 docs del borrado.
- **F3**: `podar_google_profile.py` probado con perfil sintético (29,6 MB):
  dry-run no borra; Singleton* → REFUSIDO exit 2; `--ejecutar` −29,6 MB con la
  sesión íntegra. Fix cosmético: docstring raw (SyntaxWarning \P eliminado,
  también en dedup_biblioteca).
- **F4**: `dedup_biblioteca.py` probado con duplicado hash-idéntico (3,0 MB):
  dry-run → --ejecutar → `.ref.json` + copia borrada; `library.tree()` SIGUE
  listando por referencia (`ref: true`).
- **F5**: §12 de `test_auditoria_repairs.py` ampliada (+2): default N=10
  conserva EXACTAMENTE los 10 recientes + marcados; dry-run idempotente
  (plan×2 = mismo informe, nada borrado). 44 → 46 checks.
- **F6**: import de backend 536/535/523 ms (< 5000 ms, 3 medidas).
- **F7**: experimento CRLF — árbol con 515 ficheros LF→CRLF + autocrlf=true
  (estado tipo-dueño); `git status` 513 M-fantasma con `git diff` vacío;
  suite en ese árbol: única dependencia `test_live_boot` (bash no ejecuta
  CRLF, 4 fallos) → FIX: copia LF-normalizada HERMANA del .sh (los scripts
  derivan el repo de `$(dirname "$0")/..`); live_boot 34 OK en el árbol CRLF.
  Checkout fresco: status limpio.
- **F8**: `ci.yml` `ci-windows` REAL — windows-latest / Python 3.13 / sin
  continue-on-error / pytest xdist + `run_all.py --hermetic` (69 baterías).
  3.13 y no 3.14: numpy==2.1.3 no publica wheels cp314 (evidencia PyPI
  medida: av/opencv abi3, ctranslate2/onnxruntime cp313).
- **F9**: `generate_ecommerce_badge` sin `out_path` → TypeError literal
  (keyword-only V15 ya en el linaje); endpoint 200 medido.
- **F10**: `--workers 6` medido — 2983 OK · 0 fallos · 71 baterías ·
  real 2m13.5s (serie 2m57.4s). Paralelo seguro; default sigue serie.
- **Resultados literales**: run_all serie **2983 OK · 0 fallos · 0 SKIP en 71
  baterías (2m57.4s)** · D1 hash+mtime de la BD idénticos (`9afa69dd…`) ·
  pytest 953 passed / 0 failed · npm test 28/28 · ruff limpio · compileall OK ·
  test_auditoria_repairs 46 OK · test_lock_drift 30 OK · live_boot en árbol
  CRLF 34 OK. Informe completo: `docs/informe_cierre_F1-F10.md`.
- **ci-windows: 4 rondas reales, 3 fallos de Windows cazados y corregidos**:
  (1) corrida #1 → `test_registro_baterias §D` en Windows parseaba
  «0 OK · -1 fallos»: los HIJOS minidrama (test_minidrama_clip_validator,
  test_observador_piloto) no tenían el reconfigure D5 — en cp1252 el «·» sale
  0xB7 y el regex del resumen no matchea → bloque D5 añadido a ambas
  (54 y 12 OK re-medidos). Además se detectaron bucles MCP muriendo en
  silencio (3.13): primero try/except, REVERTIDO por el TRINQUETE P2-2
  (287 > 286, corrida #2 falló SOLO por eso — la resiliencia ya existía en
  el finally que despierta futures con PROCESS_DEAD) y sustituido por un
  done-callback en el _spawn del producto (log con tail, 0 except Exception
  nuevos; trinquete 2 passed, mcp_manager 38 OK). (2) corrida #3 →
  `run_all --hermetic` real en Windows: única roja test_memorydv — los checks
  de sandbox usaban str.startswith(str(_TMP)) y en los runners Windows
  tempfile.mkdtemp devuelve 8.3 (RUNNER~1) que resolve() expande → FIX
  is_relative_to sobre formas resueltas en test_memorydv (§11/§12) y
  test_skills_autonomia (§6) (36 y 34 OK re-medidos). (3) corrida #4 →
  **CI COMPLETA VERDE en f90d558: ci (ubuntu, gate requerido) success +
  ci-windows success — la suite canónica `run_all --hermetic` (69 baterías)
  y pytest xdist pasan en windows-latest / Python 3.13**.
- **Pendiente del dueño** (documentado en el informe §honesto): borrados
  físicos de la lipo (−483 MB venv roto, −234 MB cachés perfil, −122 MB
  biblioteca) y verificación connect-all-google tras podar.
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-23 · CIERRE: verificación independiente de puertas + PUSH a GitHub

- **Base**: `ebd561f` (linaje cierre D1-D8/V9-V15 intacto, working tree
  limpio, `origin/main` aún en `29f0e90`). Objetivo de la sesión: re-verificar
  TODAS las puertas de forma independiente tras el reciclaje del sandbox
  (deps de dev reinstaladas: `ruff`, `edge-tts`, `google-genai`) y SUBIR el
  cierre a GitHub para que la máquina del dueño pueda hacer pull.
- **Zonas prohibidas verificadas intactas** (sin tocar, solo lectura de
  código): C1 `_path_contenida` (main.py:385-408, allowlist `_MEDIA_EXT` +
  exclusión `data/backups/**`); C2 `complete()` (flow_jobs.py:512, I/O fuera
  del lock en :617-672 — PIL/ffprobe jamás dentro de la transacción); C4
  `progress_allowed` (execution_contract.py:657, CLAIMED→DONE sigue
  bloqueado); C8 `factory_scheduler.arrancar()` (main.py:110); A1 badge
  (main.py:3352, `safe_filename`); A5 CORS por `EXTENSION_IDS` (main.py:261);
  A6/411 guard (main.py:248-253).
- **Resultados literales medidos HOY** (sandbox Linux, Python 3.12.16):
  - `python -m compileall backend tools tests` → exit 0.
  - `ruff check backend tools tests --select F821,E9,F63,F7,F82` → "All
    checks passed!".
  - `tests/security/test_auditoria_repairs.py` standalone → **44 OK · 0
    fallos**.
  - `npm test` (tools/GoogleFlowMCP) → **28 pass · 0 fail** (320 ms).
  - pytest COMPLETO → **953 passed · 0 failed** (140.53 s).
  - `python tests/run_all.py` serial → **2951 OK · 0 fallos · 0 SKIP en 70
    baterías**.
  - **D1**: sha256+mtime de `backend/data/yt_automation.db` IDÉNTICOS antes y
    después de la corrida completa (`909d1e2a…`, mtime 1795415045.0, size
    106496).
- **PUSH**: `main` → `origin/main` con las 4 confirmaciones del cierre
  (453a690 · 9ae8790 · 9655adf · ebd561f) + la de esta sesión. Token usado
  SOLO como credencial efímera de git (no persistido en remotos, config ni
  ficheros del repo).
- **Honestidad POSIX (no ejecutable en este sandbox Linux)**: la rama
  Windows de `apply_env_acl` (icacls), el kill de árbol vía `taskkill` y la
  materialización byte-idéntica en NTFS/CRLF se compilan y están cubiertos
  por las baterías POSIX (A6 → 0600, D4 → kill de árbol POSIX, V13 →
  byte-identidad), pero su ejecución REAL solo ocurre en la máquina del
  dueño; ver `docs/informe_reparacion_optimizacion.md` (A6/P0.6) y
  `ESTADO_REAL.md §3` para los límites que siguen sin demostrarse (E2E con
  Flow real, HANDS físico, controles reales de Flow).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-23 · CIERRE D1-D8 + V9-V15 (operatividad 100%)

- **Base declarada**: `29f0e90`. Hallazgo material de la sesión: el clone del
  sandbox había sido movido a `259c2a7` (ancestro del linaje BJ, estado
  pre-BG/BH/BI/BJ) durante el trabajo, así que el cierre se desarrolló en
  dos fases: (1) sobre `259c2a7` + cambios sin commit → commit `453a690`;
  (2) `git merge origin/main` (29f0e90) para restaurar el linaje BJ
  completo, resolviendo 15 conflictos (run_all fusionado: motor D1-D8 +
  las 69 baterías de main + guardián; flow_jobs con la estructura C2 de
  main + reintento D2 re-aplicado; guardias F1/F2 por mandato de auditoría
  de main; UI contract int025/int028 contra la UI REAL de main).
- **Alcance**: D1 aislamiento de la BD real (hash+mtime idénticos tras la
  corrida completa), D2 reintento acotado 50/150/400 ms del BEGIN IMMEDIATE
  + trazas FLOW_JOBS_TRACE + caso 4b con carga CPU, D3 --workers opt-in
  (medido serie 89.8 s vs 62.4 s workers-6 pre-merge), D4 timeout por
  batería con kill de árbol (aceptación con sleep-400 s y timeout 5 s),
  D5 UTF-8 en 57 baterías (5 verificadas a mano sin env), D6 registro
  canónico con guardián (70 BATERIAS + 103 excluidas con motivo, 0
  huérfanas), D7 sitecustomize real (HTTP real: 200 sin guardia / bloqueo
  con guardia), D8 SKIP visible; V9 import 1125-1198 ms (<5000), V10
  EXPLAIN sin SCAN flow_jobs, V11 restos P5 no presentes en el repo
  (artefactos de la máquina del dueño, comandos entregados), V12 pin
  opencv==4.13.0.90, V13 byte-identidad CRLF-safe, V14 job ci-windows
  (exploratorio), V15 badge/callout sin default inseguro + SSRF del plan C
  → safe_fetch_bytes (versión de main, async + 20 MB).
- **Bugs reales cazados por la fusión**: el runner D1-D8 había perdido el
  veredicto P0-3 (`exit != 0` con resumen «0 fallos» contaba verde) —
  restaurado y congelado por `test_run_all_accounting` (adaptado a la capa
  Popen); eco de stdout/stderr de cada batería restaurado en el runner.
- **No subido**: BASELINE de `except Exception` (regla de la misión).
- **Resultados literales**: ver la fila «Suite canónica» de ESTADO_REAL.md
  (70 baterías) y el informe de la sesión.

---

## Sesión 2026-11-22 · CIERRE BJ (backend + tools/GoogleFlowMCP)

- **Base**: `a3fd2c8` declarada en la misión; al alinear con `git fetch` +
  `git merge --ff-only origin/main` el remoto YA contenía el cierre BI1
  (`7f3ad89`, mismo sandbox/venv), así que BJ se desarrolló sobre `7f3ad89`
  (BI1 incluido) — el diff de BJ parte del estado BI1.
- **Alcance** (BJ1-BJ4):
  - **BJ1** `tools/GoogleFlowMCP/src/chrome.js` + `src/flow.js`: la conexión
    CDP en frío tarda 32-40 s y el timeout por defecto de Playwright era 30 s.
    `FLOW_CDP_CONNECT_TIMEOUT_MS` (120000 default, env-configurable,
    inválidos → default) se pasa a `chromium.connectOverCDP(…, { timeout })`;
    UN reintento si vence; duración registrada por stderr ("CDP connect OK en
    Nms" + motivo/tiempo del intento 1 en reintento). stderr y no stdout:
    mcp.js habla JSON-RPC por stdout.
  - **BJ2** `tools/GoogleFlowMCP/src/assets.js` (NUEVO, funciones puras sin
    navegador ni dependencias: `imgMediaId`, `extractTiles`,
    `extractPickerAssets`, `newTiles`, `assetLine`, `generatedImagesText`,
    `pickStartFrameAsset`, `startFrameNotFoundError`) + `src/flow.js`
    (`tiles()` = `page.evaluate(extractTiles)`; generateImages hace diff de
    `tiles()` antes/después POR mediaId y devuelve `assets`) + `src/mcp.js`
    (`flow_list_assets` imprime "- <name> [id:<mediaId>]"; `flow_generate_image`
    emite "Asset: <name> [id:<mediaId>]" por imagen ANTES de las rutas y la
    ÚLTIMA línea sigue siendo la ruta, vía `generatedImagesText`; funciones
    `mediaIds` retiradas).
  - **BJ3** `src/flow.js` `generateVideo`: startFrame acepta "id:<mediaId>"
    (busca el asset cuya `<img data-media-id>` coincida en el selector) o
    nombre exacto case-insensitive (primera = la más reciente si hay varias);
    candidatos del selector colectados con `extractPickerAssets` y selección
    con `pickStartFrameAsset`; sin match → error que lista hasta 8 nombres
    visibles; la salida indica el asset usado `(asset "Nombre" [id:…])`; el
    chip del slot solo se quita si NO es el asset pedido (por data-media-id
    con id-spec, por texto con nombre).
  - **BJ4** `backend/services/pipeline_orchestrator.py`: `_parse_generated_asset`
    extrae (nombre, mediaId) de la ÚLTIMA línea "Asset:" de
    `flow_generate_image`; el video se llama con startFrame="id:<mediaId>";
    sin línea Asset: → respaldo `flow_upload_file` nombre único
    `f"{run_id}-{scene_id}"` + log.warning (copia reducida); subida fallida →
    error claro, sin adivinar; escena guarda nombre E id
    (`start_frame_asset` + nuevo campo `start_frame_asset_id`, ambas rutas de
    creación de escenas, persistido en state.json); retry reutiliza si el
    asset sigue en Flow — id manda cuando escena y listado traen ids
    (`_asset_in_listing`), respaldo sin id reutiliza por nombre; diff BI1
    (`_unique_new_asset`) retirado al quedar sustituido por el id. El ancla
    de personaje NO se toca.
  - Python (BJ2 adaptación): `_parse_asset_listing` entiende el formato REAL
    "- <name> [id:<mediaId>]" (conserva viñetas sin id, id entre paréntesis,
    planas, JSON); dobles de `test_pipeline_orchestrator.py` (INT-023) y
    `test_bh_rutas_windows_espacios.py` emiten formato con ids + línea Asset:;
    `tests/fixtures/fake_mcp_server.py` lista con ids.
  - Tests: NUEVA `tests/test_bj_startframe_mediaid.py` (11 checks, sustituye a
    la BI1: parser de la línea Asset: presente/ausente/múltiple, parser del
    listado BJ2, semántica de `_asset_in_listing` con duplicados, línea
    presente → video por id, ausente → respaldo con warning, duplicados
    desambiguados por id, subida fallida → error claro, retry reutiliza por
    id, asset desaparecido regenera, respaldo sin id reutiliza por nombre,
    ancla intacta con 2 escenas); NUEVA `tools/GoogleFlowMCP/test/assets.test.js`
    (14 tests Node: puras de assets.js + contratos de fuente BJ1/BJ2/BJ3;
    sin navegador, sin node_modules); registro en `tests/run_all.py`
    (siguen 69 baterías).
  - Flake preexistente corregido: `test_bh1_respaldo_solo_extensiones_validas`
    fallaba TAMBIÉN en la base limpia `7f3ad89` en FS de granularidad gruesa
    (dos escrituras en el mismo tick → decidía `iterdir`); ahora fija mtimes
    con `os.utime` dentro de la ventana t0-2 s.
- **Resultados literales**: `npm test` en tools/GoogleFlowMCP — **28 pass ·
  0 fail**; compileall OK (exit 0); `ruff check backend tools tests --select
  F821,E9,F63,F7,F82` — "All checks passed!"; pytest COMPLETO **954 passed ·
  0 failed** (test_live_boot.py corre por run_all por diseño, no bajo pytest);
  `python tests/run_all.py` (serial, 6 segmentos por el límite de 10 min del
  sandbox) — **2928 OK · 0 fallos en 69 baterías** (591+707+944+493+159+34),
  sin baterías en rojo. Trinquete P2-2 `except Exception` intacto (0 añadidos;
  sin BASELINE subido).
- **No subido**: BASELINE de `except Exception` (regla de la misión).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-22 · CIERRE BH1-BH2 (backend)

- **Base**: `b0d891d` (BG1-BG2, último commit de `main`) — alineada con
  `git fetch` + `git merge --ff-only origin/main` (el local estaba en el
  ancestro `259c2a7`; el remoto ya contenía INT-09x + D2 + BG).
- **Alcance**:
  - **BH1** `backend/services/pipeline_orchestrator.py`: `_last_path`
    reescrito (via `_path_from_line`) — acepta la ÚLTIMA línea no vacía con
    ruta completa de imagen/video (`.png .jpg .jpeg .webp .mp4 .mov`,
    case-insensitive) con unidad de Windows (`X:\` o `X:/`) o barra inicial
    POSIX, CON espacios y tildes; el patrón antiguo (`[^\s]+`) cortaba en
    el primer espacio (p. ej. `D:\PROYECTOS\YOUTUBE AUTOMATION\…`).
    Respaldo `_recent_media_in_dir(outDir, t0)`: archivo MÁS RECIENTE con
    extensión válida y fecha posterior al inicio de la llamada (tolerancia
    2 s por granularidad del FS); sin ruta ni respaldo falla con el mensaje
    de siempre. Aplicado al ancla, al start-frame y al video (el video
    conserva su `or out_file`).
  - **BH2** auditoría de rutas con espacios/unidad en la etapa 4:
    - `backend/pipeline/video.py`: nuevo `ffmpeg_filter_path()` — valor de
      opción de filtro (`ass=`/`subtitles=`/`fontsdir=`) ENTRE COMILLAS
      SIMPLES con escape a nivel opción (barra duplicada, `:` escapado,
      apóstrofe → cierre+literal+apertura). El esquema antiguo (solo
      `replace(":", "\\:")` SIN comillas) se TRUNCABA en el `:` de la
      unidad tras el nivel grafo del parser de ffmpeg. `burn_subtitles` lo
      usa para ass y fontsdir; `concat_clips` escapa apóstrofes en
      `concat.txt`.
    - `backend/services/video_assembler.py`: `build_concat_cmd` escapa
      apóstrofes (`'\''`) en `concat_list.txt`; `build_burn_cmd` sigue
      inmune por diseño (cwd=run_dir + nombre relativo).
    - `backend/services/ecommerce_overlays.py`: variable muerta
      `badge_escaped` eliminada (el PNG va por `-i` con índices; la ruta
      jamás se incrusta en el filtro).
  - Tests: nueva batería `tests/test_bh_rutas_windows_espacios.py` (29
    checks) con parser réplica de `av_get_token` a dos niveles (round-trip de
    los 5 tipos de ruta + regresión del truncado antiguo), respaldo outDir
    con fechas, y corrida de etapa 3 completa con rutas con espacios;
    registrada en `tests/run_all.py` (68 baterías). Imports backend a nivel
    de función en la batería: `pipeline.video` arrastra `database` y al
    importarse a nivel de módulo rompía el hook de aislamiento de conftest
    en la corrida standalone (INTERNALERROR DB_PATH).
- **Resultados literales**: compileall OK; `ruff check backend tools tests
  --select F821,E9,F63,F7,F82` — "All checks passed!"; pytest COMPLETO
  **943 passed · 0 failed** (tras reinstalar `edge-tts` y `google-genai`
  perdidos por el reciclaje del sandbox); `python tests/run_all.py` —
  **2915 OK · 0 fallos en 68 baterías** (serial en 5 segmentos por el límite
  de 10 min por comando del sandbox: 760+1123+784+214+34), sin baterías en
  rojo. Trinquete P2-2 `except Exception` intacto (286; sin nuevos guardas).
- **No subido**: BASELINE de `except Exception` (regla de la misión).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-21 · CIERRE BG1-BG2 (backend)

- **Base**: último commit de `main` (`d1ac442` — fix D2 keepalive) tras
  `git fetch` + `git reset --hard origin/main` (local estaba 145 commits
  detrás).
- **Alcance**: BG1 (resiliencia Gemini en `gemini_client` / `script_gen` /
  `pipeline_orchestrator`) y BG2 (puerta declarada de blueprint externo en
  `POST /api/pipeline/run`).
- **Cambios**:
  - `backend/services/gemini_client.py`: `_api_status()` clasifica
    404/429/503; `_retry` consciente del error (429 sin reintento en el
    mismo modelo, 503 con esperas `_RETRY_503_WAITS = (5.0, 15.0)`); las
    cadenas de `generate_json`/`generate_text` pasan al siguiente candidato
    ante 404/429/503 y agotada la cadena fallan con el motivo real.
  - `backend/pipeline/script_gen.py`: `record_gemini_error` /
    `describe_gemini_error` / `clear_gemini_error` / `last_gemini_error` —
    registro del último error de Gemini (código y tipo, sin claves, detalle
    saneado por `_sanitize_error`); los 4 generadores limpian el registro al
    iniciar y lo alimentan al degradar.
  - `backend/services/pipeline_orchestrator.py`: `validate_external_blueprint`
    (esquema exacto, límites por campo, control chars fuera, ≤20 KB,
    INVALID_BLUEPRINT ante cualquier caso inválido, sin truncado ante
    max_scenes); `create_run(..., blueprint=None)` valida en la creación;
    `_load` hace backfill de `blueprint_source`/`external_blueprint`; etapa 2
    con blueprint externo NO llama a Gemini (engine `external:<label>`,
    `gemini_model ""`, `blueprint_source "external"`, log.warning claro);
    mensaje `BLUEPRINT_DEMO` honesto: "Gemini falló: <motivo real>" —
    eliminada la sugerencia fija "¿GEMINI_API_KEY inválida?".
  - `backend/main.py`: `/api/pipeline/run` transporta `blueprint`.
  - Tests: nueva batería `tests/test_bg_gemini_errors_and_external_blueprint.py`
    (39 checks), `test_bb5_pipeline_guards.py` actualizado al mensaje nuevo,
    registro en `tests/run_all.py`.
- **Resultados literales**: pytest COMPLETO **914 passed · 0 failed**;
  `python tests/run_all.py` (serial) — **2886 OK · 0 fallos en 67 baterías**,
  sin baterías en rojo. compileall OK; `ruff check backend tools tests
  --select F821,E9,F63,F7,F82` — "All checks passed!". Trinquete P2-2
  `except Exception` intacto (286; los 2 guardas nuevas se eliminaron en
  lugar de subir el baseline).
- **No subido**: BASELINE de `except Exception` (regla de la misión).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).

---

## Sesión 2026-11-22 · CIERRE BI1 (backend)

- **Base**: `a3fd2c8` (BH1-BH2, último commit de `main`) — alineada con
  `git fetch` + `git merge --ff-only origin/main` (local 147 commits detrás
  del remoto; el ancestro local era 259c2a7/INT-093).
- **Alcance**: BI1 — la etapa 3 de `pipeline_orchestrator` derivaba el
  startFrame de `_asset_name_from_file(frame)` (stem del archivo local),
  pero Flow nombra sus assets por el CONTENIDO del prompt (p. ej. "Red apple
  character peeking") y `flow_generate_video` fallaba con "Start frame asset
  … not found in Flow project assets". Además la copia descargada es una
  previsualización reducida (286x512): no hay que volver a subirla.
- **Cambios** (`backend/services/pipeline_orchestrator.py`):
  - `_parse_asset_listing()`: parsea `flow_list_assets` (viñetas "- Nombre",
    líneas planas, "has no images yet", "[]"/"{}", JSON [{"name","id"}] y
    {"assets":[…]}, id inline "- Nombre (id: xyz)") → [(nombre, id|None)]
    sin inventar entradas.
  - `_unique_new_asset()`: diff ANTES/DESPUÉS de generar; exactamente UN
    asset nuevo → ese nombre; si AMBOS listados traen id en todas sus
    entradas, la diferencia de ids desempata duplicados; un excedente cuyo
    nombre ya existía es ambiguo por definición (cero/varios → motivo).
  - `_list_assets()`: `flow_list_assets` parseado; None si el listado falla
    (el caller trata ese caso como ambiguo → respaldo, sin adivinar).
  - `_stage3()` por escena: detección del nombre real; respaldo HONESTO con
    `flow_upload_file` nombre único `f"{run_id}-{scene_id}"` +
    `log.warning` ("se sube la copia local reducida"); subida también
    fallida → error claro `[TOOL_ERROR]` con ambos motivos; nombre guardado
    en `scenes[].start_frame_asset` (campo nuevo en ambas rutas de creación
    de escenas, persistido en state.json). En retry, si Flow aún lista el
    start-frame → NO se regenera la imagen (ahorra créditos): solo video;
    si el asset ya no está o el listado cae → regenera vía diff y
    re-detecta. El ancla de personaje NO se toca; `_asset_name_from_file`
    ya no alimenta el startFrame (se conserva como utilidad documentada).
  - Tests: nueva batería `tests/test_bi1_startframe_flow_assets.py` (13
    checks, doble de proyecto Flow controlable: un asset nuevo/0/varios/
    duplicados/ids, respaldo por subida, subida fallida, retry reutiliza,
    asset desaparecido, listado caído, ancla intacta con secuencia
    estructural); `test_pipeline_orchestrator.py` (INT-023) con proyecto
    Flow simulado — startFrame = nombre Flow, retry sin regenerar imagen
    (55→57 checks); `test_bh_rutas_windows_espacios.py` end-to-end etapa 3
    actualizado a la semántica BI1 (mock con proyecto mínimo, conserva la
    prueba de ruta Windows con espacios en el filePath del ancla);
    registro en `tests/run_all.py` (69 baterías).
- **Resultados literales**: pytest COMPLETO **956 passed · 0 failed**
  (tras instalar `edge-tts` + `google-genai` + `ruff` en el sandbox
  reciclado; los 7 fallos previos de la batería BG eran SOLO por falta de
  `google-genai` — verificados idénticos en la base limpia a3fd2c8 con
  `git stash`); `python tests/run_all.py` (serial, 6 segmentos por el
  límite de 10 min del sandbox) — **2929 OK · 0 fallos en 69 baterías**
  (499+592+750+518+448+122), sin baterías en rojo. compileall OK (exit 0);
  `ruff check backend tools tests --select F821,E9,F63,F7,F82` — "All
  checks passed!". Trinquete P2-2 `except Exception` intacto (sin BASELINE
  subido).
- **No subido**: BASELINE de `except Exception` (regla de la misión).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).
