# SES-2026-11-21-01 — Keepalive D2 cancelado en cualquier salida + batería sobre `_run` real

## Estado
CLOSED / PASS (código + verificación completa en verde). Piloto real NO ejecutado desde el Constructor (ver límite).

## Hecho
1. **Fuga de keepalive corregida en `backend/services/pipeline_orchestrator.py`** (`_run`): la tarea del keepalive D2 (pings `flow_list_assets` durante etapas 0-2) se cancelaba SOLO en la transición a Stage 3; ante fallo de etapa 1/2 (`_fail` + `return`) o excepción de la corrida la tarea sobrevivía como huérfana, pingueando Flow CDP indefinidamente.
   - La cancelación vive ahora en el `finally` de `_run`, junto al single-flight `if self._busy == run_id` — se ejecuta en CUALQUIER salida (fin normal, fallo de etapa 1/2, `PIPELINE_CRASH`, cancelación externa).
   - El bucle se extrajo a método de clase `PipelineOrchestrator._flow_keepalive(run, interval, timeout)` (1.2 del mandato) para poder probarlo sin copiarlo; la cancelación quirúrgica previa a Stage 3 se conserva (el keepalive sigue acotado a etapas 0-2).
2. **Batería reescrita** (`tests/test_be_flow_cdp_stability.py`): el test antiguo `test_d2_keepalive_loop_short_interval` copiaba el loop a mano (no ejercitaba `_run`). Sustituido por 2 tests que ejecutan el `_run` REAL vía la ruta pública (`create_run` → `start_run` → task) con un manager doble (`_ManagerDouble`, registro `(service, tool, t)`) e intervalo corto (`FLOW_KEEPALIVE_INTERVAL=0.05`):
   - (a) `test_d2_keepalive_pings_during_stages_0_2_and_no_survivor_after_stage2_failure`: pings reales ≥2 durante etapas 0-2 y, tras corrida que FALLA en etapa 2 (`BLUEPRINT_FAILED`), `asyncio.all_tasks()` sin NINGUNA tarea `_flow_keepalive` viva + `_busy` liberado.
   - (c) `test_d2_keepalive_no_survivor_after_run_reaches_stage3`: corrida que LLEGA a etapa 3 (blueprint real con 3 escenas vía `build_result` real) → ningún ping dentro de etapa 3 (todos los ts < inicio de Stage 3) y `asyncio.all_tasks()` sin sobrevivientes.
   - Anti-tests vacuos verificado: con el orquestador SIN el fix, el test (a+b) falla exactamente en `assert _surviving_keepalive_tasks() == []`.

## Verificación (2026-11-21, venv del Constructor, Linux)
- `compileall backend tools tests`: rc=0.
- `ruff check backend tools tests --select F821,E9,F63,F7,F82`: All checks passed.
- `pytest tests/ -q` COMPLETO: **875 passed · 0 failed** (tras instalar deps faltantes del entorno: `google-genai`, `edge-tts`, `gradio_client` — fallos previos eran ModuleNotFoundError de entorno, no del código).
- `python3 tests/run_all.py`: **66 baterías · 2847 OK · 0 fallos** (65 herméticas en 6 bloques paralelos `--workers 2` + `test_live_boot.py` en serie; mismo runner oficial, fragmentado solo por el límite de 10 min del sandbox — improvisación declarada).
- Trinquete `tests/test_p2_2_except_ratchet.py`: 2 passed, `BASELINE = 286` INTACTO (no se subió).

## Resultado
- `test_be_flow_cdp_stability.py`: 7/7 (antes 6; -1 test copiado, +2 sobre `_run` real).
- Suite canónica: 66 baterías · 2847 OK · 0 fallos · pytest completo 875/0.

## Límite (honesto)
- El piloto real (PARTE 3: Chrome 9333 visible, backend reiniciado, `POST /api/pipeline/run` con presupuesto de pago) corresponde a Antigravity en la máquina del usuario (regla D-007 de `CONTEXTO YOUTUBE/INDEX.md`). El entorno del Constructor (nube Linux) no tiene Chrome con sesión de Flow/NotebookLM ni la clave Gemini del backend (`backend/.env` local solo TTS; nada escucha en 9333). NO se gastó el intento único de pago.

## Referencia
`SES-2026-11-21-01_KEEPALIVE_ANY_EXIT_Y_BATERIA_RUN_REAL.md` (este documento).
