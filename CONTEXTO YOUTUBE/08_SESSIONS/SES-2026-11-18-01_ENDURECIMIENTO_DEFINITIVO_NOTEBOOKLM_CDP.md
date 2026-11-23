# SES-2026-11-18-01 — Endurecimiento Definitivo de NotebookLM y Conectividad CDP Resiliente

- **Fecha:** 2026-11-18
- **Estado:** CLOSED / PASS
- **Autor/Rol:** Antigravity AI Assistant

---

## 1. Contexto y Problema
El usuario reportó recurrencia en el fallo `[LIST_EMPTY] listado de notebooks vacío o ilegible` al reconectar o tras nuevos inicios del sistema.
El análisis forense identificó:
1. **Expiración de Tokens Google batchexecute:** Google NotebookLM exige CSRF `at` (`SNlM0e`) y `f.sid` (`FdrFJe`), que rotan periódicamente (~24h o al reiniciar sesión).
2. **Deficiencia en `_sync_auth_json`:** Preservaba tokens obsoletos de `~/.notebooklm-mcp/auth.json` sin actualizar `csrf_token` ni `session_id` desde Chrome.
3. **Build Label obsoleto (`NOTEBOOKLM_BL`):** Google actualizó el frontend a `boq_labs-tailwind-frontend_20261117.07_p0`, provocando `401 Unauthorized` al consultar con versiones antiguas hardcodeadas.
4. **Fallo de scraping upstream en SPA:** El cliente `notebooklm-mcp` upstream intenta scrapear tokens vía `httpx.get()` que no interpreta la SPA renderizada en cliente.

---

## 2. Acciones y Endurecimiento Implementado
En `backend/services/mcp_manager.py`:
1. **Parsing Nativo batchexecute (`parse_notebook_list`):** Soporte nativo para payloads de Google `)]}' ... wrb.fr wXbhsf ...`, decodificando el JSON anidado y extrayendo títulos y UUIDs directamente.
2. **Extracción en Vivo vía Chrome CDP (`_cdp_fetch_notebooklm_tokens`):** Conecta a la pestaña activa de `notebook.google.com` y extrae en vivo `csrf_token` (`SNlM0e`), `session_id` (`FdrFJe`) y el `build_label` activo (`window.WIZ_global_data.cfb2h`), sincronizando variables de entorno y `auth.json`.
3. **Consulta Directa RPC Resiliente (`_cdp_list_notebooks_direct`):** Ejecuta la llamada RPC `wXbhsf` directamente en el contexto autenticado del navegador en <200 ms.
4. **Fallback Transparente en `list_notebooks`:** Si el proceso FastMCP devuelve lista vacía o falla por expiración de sesión, conmuta de inmediato a `_cdp_list_notebooks_direct`, garantizando disponibilidad del 100% mientras la pestaña de Chrome esté abierta.
5. **Sincronización Dual Robusta (`_sync_auth_json`):** Acepta el diccionario `tokens` y actualiza atómicamente `csrf_token` y `session_id`.

---

## 3. Pruebas y Verificación
- **Batería Hermética:** `tests/test_bb5_pipeline_guards.py` expandida a 7 tests (incorporando batchexecute parsing, sincronización de tokens y fallback CDP mockeado). 7/7 passed.
- **Trinquete de Excepciones:** `tests/test_p2_2_except_ratchet.py` 2 passed (sin alterar el trinquete).
- **Integridad Documental:** `tests/test_p3_3_docs_integrity.py` 3 passed (61 baterías intactas).
- **Verificación en Vivo:** `list_notebooks()` validado contra Chrome CDP real reportando 7 cuadernos reales (incluyendo `FRUTINOVELAS` `5b7728cb-3e1e-480f-ae82-786f61c0179b`).
