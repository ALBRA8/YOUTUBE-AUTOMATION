# SES-2026-11-19-02 — Cadena de Fallback Gemini, Build Label en Vivo y Filtrado Específico de Cookies

- **Fecha:** 2026-11-19
- **Estado:** CLOSED / PASS
- **Área:** Backend / Modelos LLM / MCP NotebookLM / Pipeline Orchestrator

## 1. Contexto y Objetivos
Durante el piloto de pipeline, el Stage 2 falló con `404 NOT_FOUND` porque Google deprecó el modelo `gemini-2.5-flash` para nuevos proyectos de AI Studio (indicando explícitamente `This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash`). Asimismo, se detectó una discrepancia en el build label de NotebookLM (`boq_labs-tailwind-frontend_20261112.11_p0` vs `boq_labs-tailwind-frontend_20261117.07_p0`) y contaminación de cookies de otros dominios en `auth.json`.

## 2. Trabajo Realizado
1. **Parte 1 — Sondas en Vivo (S1-S5):**
   - S1: Sonda a `GET /v1/models` listando candidatos con "flash".
   - S2: Verificación de llamadas `generateContent`: `gemini-3.8-flash` devolvió HTTP 200 OK de inmediato, mientras que `gemini-2.5-flash`, `gemini-2.5-flash-lite` y `gemini-flash-latest` devolvieron 404 NOT_FOUND.
   - S3: Configuración de `GEMINI_TEXT_MODEL=gemini-3.8-flash` en `backend/.env`.
   - S4: Extracción en vivo del build label activo de Google NotebookLM (`boq_labs-tailwind-frontend_20261117.07_p0`).
   - S5: Prueba con build label vivo y respaldo de `auth.json`.

2. **Parte 2 — Implementación de Código:**
   - **2A (`mcp_manager.py`):** `_cdp_fetch_cookies_raw` usa `Network.getCookies` con `urls=[BASE_URL]`, descartando hosts ajenos (`accounts.google.com`) y desduplicando cookies dando prioridad al host más específico (`notebook.google.com` > `.google.com`).
   - **2B (`mcp_manager.py`, `config.py`):** Derivación de build label en vivo desde el HTML/DOM de la pestaña activa en cada conexión (`_live_bl`), alineando defaults únicos y estableciendo la precedencia: `_live_bl` > `os.environ["NOTEBOOKLM_BL"]` > `config.NOTEBOOKLM_BL`.
   - **2C (`gemini_client.py`, `script_gen.py`, `pipeline_orchestrator.py`):** Cadena de modelos fallback con `GEMINI_TEXT_MODEL_FALLBACKS` (por defecto `gemini-flash-latest,gemini-3.8-flash,gemini-2.5-flash`). Ante `404 NOT_FOUND`, se omite el reintento backoff en el mismo modelo y se prueba el siguiente candidato de la cadena, recordando en memoria del proceso el primero funcional. Registro de `run["gemini_model"]` y `run["engine"]`.

3. **Verificación y Suites:**
   - Batería hermética `tests/test_bd_gemini_models_and_bl.py` (6 tests).
   - Integrada en `tests/run_all.py` elevando el inventario canónico a 63 baterías.
   - Trinquete de excepciones `test_p2_2_except_ratchet.py` en 286 (0 regresiones).
   - Integridad documental `test_p3_3_docs_integrity.py` validada (3/3).
