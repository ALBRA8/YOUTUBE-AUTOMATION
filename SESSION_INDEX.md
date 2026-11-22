# SESSION INDEX — índice de sesiones de trabajo

> Registro cronológico de sesiones con su alcance, commit y resultados
> literales. Una sesión sin entrada aquí no ocurrió.

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
