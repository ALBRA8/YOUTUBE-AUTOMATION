# SESSION INDEX — índice de sesiones de trabajo

> Registro cronológico de sesiones con su alcance, commit y resultados
> literales. Una sesión sin entrada aquí no ocurrió.

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
