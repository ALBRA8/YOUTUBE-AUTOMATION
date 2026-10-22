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
- **No demostrado en este hito:** carga/selección de imagen correcta y binding de su mediaId en request de vídeo por este camino de extensión.
- **Próximo:** captura de red real desde ALBRA si este camino vuelve a ser necesario.

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
- **Herramientas iniciales:** `flow_generate_image`, `flow_upload_file`, `flow_list_assets`, `flow_new_project`.
- **Seguridad operacional:** `FLOW_MCP_ENABLED=0` por defecto; degradación limpia a fallback ante cualquier error.

## INT-007 — Reference / Asset Lineage & Scene Asset Resolver (Gate B / B.2 / B.2R)
- **Estado:** IMPLEMENTADO / PRUEBAS UNITARIAS Y REGRESIÓN PASS / LIVE TEST 2R PASS.
- **Componentes:** `backend/pipeline/asset_resolver.py`, `backend/pipeline/images.py`, `tools/GoogleFlowMCP/src/flow.js`.
- **Mecanismo:** resolución determinista de referencias de escena → subida vía `upload_file()` → desambiguación/rename en Google Flow → inyección de `@mention` → consumo interactivo mediante `mention-chip` → generación real en Flow.
- **Dictamen:** REFERENCE CONSUMPTION PASS.

## INT-008 — Live Video Generation & Start Frame Lineage (Gate C.0)
- **Estado:** DEMOSTRADO EN VIVO / LIVE SMOKE TEST PASS.
- **Componentes:** `tools/GoogleFlowMCP`, Google Flow CDP (`:9333`), selector Start Frame (`Iniciar` → `flow-image-ingredient-chip`).
- **Mecanismo:** activación de modo Fotogramas → selección física del asset en slot `Iniciar` → verificación DOM → generación real con Omni 1.1 Flash → captura y validación binaria de MP4.
- **Evidencia:** MP4 720x1280, 8.00 s, H.264+AAC.
- **Dictamen:** LIVE VIDEO START FRAME PASS.

## INT-009 — Gate C.0 Context Closure
- **Estado:** DOCUMENTADO / C.0 CERRADO.
- **Propósito:** registrar formalmente la demostración de capacidad de video Start Frame antes de exponerla al backend.
- **Regla:** C.0 prueba capacidad física de Flow; no equivale por sí solo a integración del pipeline.

## INT-010 — Gate C.1: Video MCP Pipeline Bridge
- **Estado:** PASS / VALIDACIÓN EN VIVO CONFIRMADA.
- **Documento:** `INT-010_GATE_C1_VIDEO_MCP_PIPELINE_BRIDGE.md`.
- **Resultado:** `flow_generate_video` expuesto por MCP, `generate_video()` en backend, `generate_scene_video()` en pipeline y descarga real de MP4 reconocida por `flow_import.find_flow_videos()`.
- **LIVE:** `_live_video_test_02`, Start Frame `crystal_orb_c1`, MP4 720x1280, 8.00 s.

## INT-011 — Gate C.2: Flow Video ↔ Production Orchestrator
- **Estado:** PASS / LIVE END-TO-END VALIDATION CONFIRMADA.
- **Documento:** `INT-011_GATE_C2_FLOW_VIDEO_ORCHESTRATOR_INTEGRATION.md`.
- **Resultado:** el orquestador normal puede generar videos Flow para escenas pendientes, reutilizar clips existentes de forma idempotente, entregar los clips al ensamblador existente y degradar escenas fallidas a Ken Burns.
- **Feature flag:** `FLOW_MCP_VIDEO_ENABLED=0` por defecto.
- **LIVE:** `live_c2_test_01`, dos escenas; escena 01 reutilizada, escena 02 generada en vivo; ambos clips descubiertos por `flow_import`; video final producido y proyecto en estado `ready`.
- **Observación:** la duración final reportada fue 3.43 s frente a clips individuales de ~8 s; la política temporal/retiming debe considerarse pendiente de validación de producción.
- **Estado Git:** C.2 quedó posteriormente publicado en `origin/main`; el cierre técnico fue registrado fuera del documento inicial.

## INT-012 — HARD E2E: Flow Video → Producción Completa
- **Estado:** FAIL / FALLO LOCALIZADO EN RENDER FINAL DE SUBTÍTULOS.
- **Documento:** `INT-012_HARD_E2E_FLOW_VIDEO_PRODUCTION_PIPELINE.md`.
- **Proyecto:** `_hard_e2e_c2_01`.
- **Resultado:** 4/4 escenas generadas realmente en Google Flow mediante MCP, con Start Frames y referencias independientes; cuatro MP4 válidos descargados e ingeridos; ensamblado y mezcla de audio completados.
- **Punto de fallo:** `backend/pipeline/video.py`, `burn_subtitles`, `_run_ffmpeg(..., timeout=900)`; `subprocess.TimeoutExpired` después de 900 s durante `libass` + `libx264 -preset medium`.
- **Final observado:** archivo final de ~45.8 MB, 19.733 s, H.264 + AAC, con subtítulos Hormozi y audio mezclado, pero el supervisor declaró la ejecución `failed` por timeout.
- **Idempotencia Run 2:** no ejecutada porque Run 1 terminó por timeout.
- **Limpieza:** `.flow.lock` liberado y sin procesos/locks huérfanos reportados.
- **Dictamen:** el primer fallo de esta prueba dura está en el render final FFmpeg, no en GoogleFlowMCP/Google Flow/Start Frame/referencias/import/ensamblado.

## INT-013 — Preparación de Arnés AGENTE-GENERAL
- **Estado:** PREPARACIÓN / ANÁLISIS ARQUITECTÓNICO — SIN MIGRACIÓN EJECUTADA.
- **Documento:** `INT-013_AGENT_GENERAL_HARNESS_MIGRATION_PREPARATION.md`.
- **Resultado:** frontera agente/arnés definida, AgentAdapter diseñado, skills/knowledge mapeados, plan P0–P5 y superficies protegidas registrados.

## INT-014 — Integración AGENTE-GENERAL ↔ Harness V1 (P1 + P1.5 + P2)
- **Estado:** P1 PASS / P1.5 INTEGRADO LOCAL (push pendiente de credencial) / P2 PASS / P3 NO INICIADO.
- **Documento:** `INT-014_AGENTE_GENERAL_HARNESS_P1_P2.md`.
- **Resultado P1:** conexión fría real demostrada — host (cliente/tool/skill reales) → HTTP Bearer → `/api/harness/v1` → operaciones LOW read-only → HarnessResult válido; 272 checks verdes; fail-closed en 6 vectores; cero modificaciones de código.
- **Resultado P1.5:** merge `--no-ff` de `feature/youtube-harness` (`b5b7220`) sobre `origin/main` (`5f277b3`) → commit `9bb3870` local; cero conflictos; no-regresión probada por comparación con worktree de control; push a GitHub bloqueado por PAT inválido para escritura (BLOCKED BY AUTH).
- **Resultado P2:** ciclo operativo sin launch demostrado con motor real (45 checks, 0 fallos): descubrimiento, secuencia read controlada (7 operaciones LOW por las tres capas del host), contrato completo, 5 límites negativos BLOCKED, idempotencia del libro verificada (replay `metadata.replayed=True`), `projects=0/jobs=0/flow_jobs=0` antes=después, sin vídeo/render/publicación.
- **Gobernanza:** 9/9 skills host con riesgo coherente con la operación del arnés; HITL único en `publish`; política del host es adición al PolicyEngine del seed.
- **Entrada P3:** matriz de capacidades (17 internas / 19 operaciones / 9 skills host) con estado VERIFIED/MISSING/DIVERGENT/N-A incluida en el documento.
