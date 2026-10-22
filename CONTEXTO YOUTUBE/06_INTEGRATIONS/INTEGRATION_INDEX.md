# INTEGRATION INDEX

## INT-001 — AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION
- **Estado:** frontera arquitectónica vigente.
- **Cuerpo central:** identidad, coordinación e infraestructura transversal.
- **Especialización:** producción audiovisual, Flow Bridge, QA, publicación.
- **Regla:** no duplicar infraestructura ni mover Google Flow al cuerpo central.

## INT-002 — Backend Flow Bridge ↔ Chrome extension
- **Estado:** código/tests reportados como reales dentro de sus alcances.
- **Componentes:** jobs SQLite, claim/lease/heartbeat/retry, endpoints `/api/extension/flow/jobs*`, `extension/bridge.js` y wiring en `background.js`.
- **Límite:** mocks/HTTP no prueban binding visual de Flow.

## INT-003 — Chrome extension ↔ Google Flow
- **Estado:** PARTIAL / REAL EXECUTION NOT DEMONSTRATED.
- **Observado:** inyección UI de prompt, reporte de envío, polling/descarga y observabilidad de respuestas/notificaciones.
- **No demostrado:** carga/selección de imagen correcta y binding de su mediaId en request de vídeo.
- **Próximo:** captura de red real desde ALBRA.

## INT-004 — Start Frame Meta AI
- **Estado:** existe `readStartFrame` y `injectMetaScene`.
- **Límite:** proveedor/camino separado; no extrapolar a Google Flow.

## INT-005 — HANDS / Flow Operator
- **Estado:** HANDS estructuralmente implementado según inventario; conexión física/Flow real marcada OFF/NOT CONNECTED según configuración.

## INT-006 — GoogleFlowMCP (Browser Automation vía Playwright/CDP y Puente Local)
- **Estado:** PUENTE LOCAL IMPLEMENTADO / PRUEBAS AISLADAS PASS / LIVE TEST 1 PASS.
- **Ubicación:** `tools/GoogleFlowMCP`
- **Componentes:** `backend/services/flow_mcp_client.py`, `backend/config.py`, `backend/pipeline/images.py`.
- **Mecanismo:** MCP Server stdio JSON-RPC 2.0 + Playwright-core conectándose a Chrome dedicado vía CDP (puerto 9333).
- **Herramientas expuestas:** `flow_generate_image`, `flow_upload_file`, `flow_list_assets`, `flow_new_project`.
- **Seguridad operacional:** `FLOW_MCP_ENABLED=0` por defecto; degradación limpia a fallback ante cualquier error.

## INT-007 — Reference / Asset Lineage & Scene Asset Resolver (Gate B / B.2 / B.2R)
- **Estado:** IMPLEMENTADO / PRUEBAS UNITARIAS Y REGRESIÓN PASS / LIVE TEST 2R PASS REPORTADO / GATE B.2R CLOSED.
- **Componentes:** `backend/pipeline/asset_resolver.py`, `backend/pipeline/images.py`, `tools/GoogleFlowMCP/src/flow.js`.
- **Mecanismo:** Resolución determinista de referencias de escena (`scene.references` / `meta.production_unit.references`) → subida vía `upload_file()` → desambiguación y fix de rename en Google Flow → inyección de `@mention` → consumo interactivo (`mention-chip`) en ProseMirror → generación real en Flow.
- **Dictamen:** REFERENCE CONSUMPTION PASS reportado.

## INT-008 — Gate B.3 / Release Closure
- **Estado:** **PASS / CLOSED**.
- **Commit:** `02b66454d09af65684de86639b751c31cd4b2030`.
- **Push:** `78868a4..02b6645 main -> main`.
- **Verificación:** `HEAD == origin/main`; árbol limpio.
- **Regla:** Gate B.2R ya no es trabajo pendiente. El siguiente trabajo debe abrir un nuevo alcance/Gate independiente.
- **Documento:** `INT-008_GATE_B3_CLOSURE.md`.

## INT-009 — Gate C.0 / LIVE Video Smoke Test
- **Estado:** **PASS / CLOSED**.
- **Objetivo:** demostrar imagen real → asset real → Start Frame real → Google Flow → video real → descarga → validación.
- **Resultado:** generación real de video en Google Flow con Start Frame confirmado y MP4 H.264/AAC válido recuperado localmente.
- **Evidencia principal:** `backend/data/output/_live_video_test_01/video_01.mp4`, 5,344,832 bytes, 8.00 s, 720x1280, 9:16, 24 fps, `.flow.lock` liberado.
- **Start Frame:** `crystal_orb` / Media ID `f7057dfd-9eb5-415b-b4da-5edb16871292` seleccionado mediante el modo nativo `Fotogramas` de Google Flow.
- **Documento:** `INT-009_GATE_C0_LIVE_VIDEO_SMOKE_TEST.md`.
- **Próximo:** Gate C.1 — intento LIVE directo de producción de video desde YOUTUBE-AUTOMATION, sin auditoría preventiva amplia; si falla, micro-auditar únicamente el punto de fallo.
