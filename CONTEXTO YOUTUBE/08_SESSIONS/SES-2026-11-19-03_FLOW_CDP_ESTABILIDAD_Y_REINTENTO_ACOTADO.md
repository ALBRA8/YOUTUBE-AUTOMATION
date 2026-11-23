# SES-2026-11-19-03 · Estabilidad Flow/CDP, Flags de Fondo, Calentamiento y Reintento Acotado (BE)

**Fecha/Hora:** 2026-11-19T06:06:00-05:00  
**Contexto:** Diagnóstico de fallos en Stage 3 por `connectOverCDP: Timeout 30000ms exceeded`, estrangulamiento de fondo en Chrome (CDP port 9333) y diseño de defensas de estabilidad.

---

## 1. Hallazgos del Diagnóstico

1. **Causa raíz del timeout de 30 s en Flow**:
   Cuando Chrome corre en segundo plano o minimizado sin flags de desactivación de throttling, Windows suspende/reduce los temporizadores y renderers de fondo. Al conectar Playwright vía WebSocket (`connectOverCDP`), el timeout de 30 000 ms expira antes del handshake.
2. **Defensas implementadas (D1-D3)**:
   - **D1 (Flags de fondo en Chrome)**: En `backend/services/mcp_manager.py` (~l. 1209), se añadieron `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, y `--disable-backgrounding-occluded-windows`.
   - **D2 (Calentamiento previo a Stage 3)**: En `backend/services/pipeline_orchestrator.py` al iniciar Stage 3, se realiza una llamada real a `flow_list_assets` (hasta 2 intentos). Si ambos fallan, aborta de forma honesta con `FLOW_CDP_SLOW`.
   - **D3 (Excepción acotada a regla AA1)**: Si `flow_generate_image`, `flow_generate_video`, `flow_new_project` o `flow_upload_file` fallan con error conteniendo `"connectOverCDP: Timeout"`, se permite UN reintento precedido de calentamiento y `log.warning`. Cualquier otro error no se reintenta (preservando AA1 contra duplicación/cargos).
3. **Trinquete de `except Exception`**:
   Las capturas usan excepciones tipadas (`mcpm.MCPManagerError`, `RuntimeError`, `OSError`, `TimeoutError`, `asyncio.TimeoutError`), manteniendo la línea base del trinquete intacta en 286.
4. **Batería hermética**:
   `tests/test_be_flow_cdp_stability.py` (5 tests herméticos: D1, D2 success/fail, D3 timeout retry, D3 other error no retry).
5. **Integración en runner**:
   Integrada en `tests/run_all.py` (batería 64).
