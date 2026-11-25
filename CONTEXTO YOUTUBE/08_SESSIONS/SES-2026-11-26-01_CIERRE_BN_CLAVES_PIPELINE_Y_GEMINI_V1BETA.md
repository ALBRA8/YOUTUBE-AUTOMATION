# SES-2026-11-26-01 · CIERRE BN — claves desconocidas en /api/pipeline/run (422 + sugerencia) y alias Gemini «-latest» por v1beta

- **Base**: `a7dfb9e` (main, árbol limpio). Entorno: clon Linux del sandbox
  (Python 3.12.16), `backend/.venv` recreado desde el lock tras el reciclaje
  del sandbox (`pip install -r backend/requirements-lock.txt` +
  `requirements-dev.txt`) → guardia F1 **33 OK · 0 fallos**.

## BN1 · POST /api/pipeline/run rechaza claves de primer nivel desconocidas con 422

- **Problema**: una clave de primer nivel mal escrita (`external_blueprint`
  en vez de `blueprint`) se **ignoraba en silencio**: `create_run` recibía
  `blueprint=None`, la etapa 2 caía en Gemini y la corrida se gastaba sin
  que el llamador supiera por qué.
- **Arreglo** (`backend/main.py`): whitelist canónica
  `_CLAVES_PIPELINE_RUN = (blueprint, format, idea, max_scenes, nicho_id,
  notebook_id, style)` + `_sugerencia_clave()` (difflib, n=1). Cualquier
  clave desconocida → **HTTP 422** con la clave culpable, la sugerencia
  («¿quisiste decir 'blueprint'?») y el catálogo de claves válidas. La
  validación corre ANTES de tocar el orquestador: `create_run` jamás se
  invoca con un payload inválido.
- **Sugerencias verificadas literalmente** (difflib cutoff 0.6):
  `external_blueprint→blueprint`, `notebook→notebook_id`,
  `formato→format`, `styles→style`, `nicho→nicho_id`,
  `maxscene→max_scenes`; sin falsas sugerencias (`zzzqqq → ''`).
- Las 7 claves válidas siguen aceptándose: corrida externa completa 200 +
  `blueprint_source=external` (regresión en la batería).

## BN2 · La cadena de modelos intenta «gemini-flash-latest» por v1beta

- **Problema (raíz verificada en el SDK instalado)**: google-genai 3.6.1
  construye las URLs con `GOOGLE_AI_API_DEFAULT_VERSION = 'v1'`, pero los
  alias de familia «-latest» **solo están publicados en v1beta** → por v1
  devuelven 404 NOT_FOUND y la cadena BG1/BD-2C descartaba el candidato
  sano (en vivo 2026-11-19: `gemini-flash-latest` 404 por v1 mientras
  `gemini-3.8-flash` devolvía 200 — SES-2026-11-19-02).
- **Arreglo** (`backend/services/gemini_client.py`): `_es_alias_latest()` +
  `_versiones_de_candidato()` — la familia `-latest` se intenta **PRIMERO
  por v1beta** usando **HttpOptions POR REQUEST** (el cliente global no se
  muta; el resto de llamadas no se ve afectado). Solo ante 404 se agota
  también v1 (prueba ambas versiones antes de descartarlo). 429 (cuota) y
  503 (caída) NO prueban la otra versión (misma cuota y mismo backend en
  v1/v1beta) → pasan al siguiente candidato con la política BG1 intacta.
  Los modelos no-alias conservan UN intento con la versión por defecto del
  SDK — el guardia BD 2C (que cuenta intentos literales por candidato)
  queda exactamente igual de cierto.
- **Prueba literal a nivel URL (sin red)**, capturando
  `BaseApiClient._request_once` con el venv real:
  - `https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent`
  - `https://generativelanguage.googleapis.com/v1/models/gemini-3.8-flash:generateContent`
  - `/v1/models/gemini-flash-latest:…` ya NO ocurre nunca.
- No cambia nada de `flow_export._MODEL_CANDIDATES` ni de
  `config.DEFAULT_GEMINI_FALLBACKS`: el alias de la cadena ahora SÍ vive
  (v1beta) en vez de quemarse por v1.

## Batería nueva y gates

- `tests/test_bn_pipeline_keys_y_gemini_v1beta.py`: **13 checks herméticos**
  (BN1: difflib unit, 422 con sugerencia + `create_run` jamás llamado, 422
  con varias claves + catálogo, corrida completa con las 7 claves; BN2:
  versiones unit, v1beta primero, v1beta-404→v1 éxito, alias agotado→
  siguiente candidato, no-alias 1 intento, 429 sin segunda versión y sin
  esperas, alias recordado reusa v1beta, generate_text v1beta, motivo real
  tras agotar ambas versiones). Standalone: «13 OK · 0 fallos» exit 0.
  Registrada en `BATERIAS` → **73 baterías**.
- Regresión directa verde: BD (6) + BG (39) + BM (6) + pipeline_orchestrator
  + bb5 = **61 passed**.
- **Gates finales**: compileall exit 0; ruff F821,E9,F63,F7,F82 «All checks
  passed!»; pytest COMPLETO **983 passed, 2 warnings** (138.75 s); run_all
  `--workers 6` **3016 OK · 0 fallos · 0 SKIP en 73 baterías** (exit 0,
  doble corrida idempotente); npm test GoogleFlowMCP **38/38**;
  `security/test_lock_drift.py` 33 OK · 0 fallos;
  `security/test_auditoria_repairs.py` 46 OK · 0 fallos; import main
  404/415/423 ms; BD real sha256/mtime/size idénticos antes/después
  (9afa69dd9cb924e2… / 1795461897 / 114688 B).
- **Commit**: ver `git log -1` (hash en el cierre de la sesión).
