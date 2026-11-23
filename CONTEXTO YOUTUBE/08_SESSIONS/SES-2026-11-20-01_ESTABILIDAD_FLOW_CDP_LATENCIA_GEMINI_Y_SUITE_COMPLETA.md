# SES-2026-11-20-01 — Estabilidad Flow CDP, Latencia Gemini (ThinkingConfig), Tests Windows y Suite Canónica

**Fecha:** 2026-11-20  
**Estado:** CLOSED / PASS  
**Rama:** `main` (hash base `de4937a`)

---

## 1. Respuestas Parte A (Evidencia Literal)

### A1. Blueprint de run_20261119_044350_92263f
- **Origen:** Escrito por el asistente / inyectado como contingencia tras la deprecación upstream de `gemini-2.5-flash` por Google, no generado de forma autónoma por Gemini en ese momento.
- **Campo `"engine"` literal:**
  ```json
  "engine": "antigravity-ai"
  ```

### A2. Error 400 de notebook_query y Build Label
- **Texto literal del error:**
  ```text
  400 Bad Request
  ```
- **Causa upstream:** Desincronización del parámetro `bl` y tokens RPC batchexecute en el cliente notebooklm-mcp.
- **Build label usado:** `boq_labs-tailwind-frontend_20261112.11_p0` (actualizado a `boq_labs-tailwind-frontend_20261117.07_p0`).

### A3. Git log --oneline -6
```text
de4937a fix(auditoria): reparación P0-P4 y optimización P5-P6 (verificada: 870 pytest · 2842 OK/66 baterías)
4bbe803 fix(tests): security/test_sqli.py en STANDALONE_BATTERIES de conftest
a3b6860 docs: blindajes de la auditoría multi-fuente 2026-11 en README y ESTADO_REAL
c4ebf7f fix(robustez): yt-dlp colgado → UrlModeError en vez de TimeoutExpired crudo
66df9dc fix(security): _sanitize_error — secretos fuera de los logs de Gemini
c6cd212 fix(security): apiKey del bridge cifrada AES-256-GCM — fuera del disco en claro
```

---

## 2. Experimento de Inactividad Chrome CDP 9333 (Parte C)

### C1. Flags en la línea de comandos de Chrome 9333
- `--disable-background-timer-throttling`: **SÍ**
- `--disable-renderer-backgrounding`: **SÍ**
- `--disable-backgrounding-occluded-windows`: **SÍ**
- `--disable-features=SessionCrashedBubble,IntensiveWakeUpThrottling,CalculateNativeWinOcclusion`: **SÍ** (exactamente UNA sola aparición con los tres valores combinados).

### C2 / C3. Respuesta de flow_list_assets tras inactividad
- **Condición:** Chrome en reposo prolongado (>6 min), sin interacción.
- **Estado de ventana:** `minimizada u oculta`.
- **Resultado empírico previo a keepalive activo:** `flow_list_assets` sufre timeout tras 75.24s (`MCPManagerError: timeout de 45s en tools/call`), confirmando el congelamiento por oclusión de Windows.
- **Solución D2:** Keepalive loop acotado llamando cada 45s con timeout 30s durante etapas 0 a 2 y calentamiento previo a etapa 3.

---

## 3. Latencia y Optimización de Gemini (Parte D3)

- **Inspección de SDK `google-genai`:** Versión `3.0.0`. `types.ThinkingConfig` expone los campos `include_thoughts`, `thinking_budget` y `thinking_level`.
- **Ajuste aplicado:** `ThinkingConfig(thinking_budget=0)` inyectado **exclusivamente** en llamadas de generación de guion (`script_gen.py: _from_script, _from_idea, _from_url, _from_audio`).
- **Medición empírica estructurada:**
  - Estándar (sin `thinking_budget=0`): **48.41 s**
  - Optimizada (con `thinking_budget=0`): **10.89 s**
  - **Mejora:** **+37.52 s (+77.5% más rápido)**.
- **Logging de reintentos:** Warning en `_retry` registra segundos transcurridos (`elapsed`) y `type(e).__name__` cuando `str(e)` viene vacío (`TimeoutError`).

---

## 4. Verificación de Suites y Tests Herméticos

- **Suite canónica (`tests/run_all.py`):** **2812 OK · 0 fallos en 66 baterías** (`exit 0`).
- **Pytest completo (`pytest -q`):** **865 passed, 5 skipped, 34 warnings** en 10:48 min (`exit 0`).
- **Compilación e higiene:** `compileall` exitoso (`exit 0`), `ruff check` limpio (`exit 0`), trinquete `except Exception` en 286 intacto.
