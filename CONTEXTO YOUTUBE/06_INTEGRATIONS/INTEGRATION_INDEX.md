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
- **Estado:** P1 PASS / P1.5 PUBLICADO (PR #67 → merge `3afa77f` en main, CI 5/5) / P2 PASS / P3 PASS (ver INT-015).
- **Documento:** `INT-014_AGENTE_GENERAL_HARNESS_P1_P2.md`.
- **Resultado P1:** conexión fría real demostrada — host (cliente/tool/skill reales) → HTTP Bearer → `/api/harness/v1` → operaciones LOW read-only → HarnessResult válido; 272 checks verdes; fail-closed en 6 vectores; cero modificaciones de código.
- **Resultado P1.5:** merge `--no-ff` de `feature/youtube-harness` (`b5b7220`) sobre `origin/main` (`5f277b3`) → commit `9bb3870` local; cero conflictos; no-regresión probada por comparación con worktree de control; push a GitHub bloqueado por PAT inválido para escritura (BLOCKED BY AUTH).
- **Resultado P2:** ciclo operativo sin launch demostrado con motor real (45 checks, 0 fallos): descubrimiento, secuencia read controlada (7 operaciones LOW por las tres capas del host), contrato completo, 5 límites negativos BLOCKED, idempotencia del libro verificada (replay `metadata.replayed=True`), `projects=0/jobs=0/flow_jobs=0` antes=después, sin vídeo/render/publicación.
- **Gobernanza:** 9/9 skills host con riesgo coherente con la operación del arnés; HITL único en `publish`; política del host es adición al PolicyEngine del seed.
- **Entrada P3:** matriz de capacidades (17 internas / 19 operaciones / 9 skills host) con estado VERIFIED/MISSING/DIVERGENT/N-A incluida en el documento.

## INT-015 — P3: Matriz Definitiva de Capacidades AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION
- **Estado:** P3 — PASS / MATRIZ DEFINITIVA CON EVIDENCIA / CERO CAMBIOS FUNCIONALES.
- **Documento:** `INT-015_P3_CAPABILITY_MATRIX.md`.
- **Resultado:** matriz definitiva (bloques A–H, ~35 capacidades) con owner, implementación interna, operación de arnés, skill host, permiso, riesgo, HITL, tests, estado y acción por fila — verificada contra el código real (file:line), no contra informes previos.
- **Correcciones factuales:** riesgos reales 11 LOW/4 MEDIUM/3 HIGH/1 CRITICAL (delete=CRITICAL); `youtube.admin` expande permisos del arnés (no scopes Google; Google real = 2 scopes); `cleanup_failed` excluida del contrato v1 por diseño; policy/grants/firewall del host son datos declarativos no adoptados por runtime (enforcement real 100% arnés).
- **Gaps con veredicto:** `validate_production` y `system_status` → únicas skills host nuevas propuestas (P3-B); catálogos nichos/estilos/avatares = contexto interno sin skill; `ANALYZE_FAILURE` DIVERGENT (falta scope por-proyecto, v1.1); `RETRY` VERIFIED en motor (attempts/leases) y FUTURE como op (sin checkpoints por paso); `cancel`/`delete`/`cleanup` sin skill host deliberadamente.
- **Hallazgos nuevos:** G-01 bug de envelope (publish exitoso reporta FAILED); G-02 `doctor fix` muta bajo RISK_LOW/read; G-03 launch HIGH sin HITL host (decisión consciente); G-04 delete sin guard de published; G-05..G-12 menores (ledger sin TTL, replay sin comparar cuerpo, env no documentada, etc.).
- **Tests P3:** YT-AUT 17/17 suites PASS (610 checks, 0 fallos); AG-G especialización 15 passed; unit completa 18 failed/461 passed/4 skipped con los 18 pre-existentes idénticos al baseline.
- **Publicación:** PR #67 (merge `3afa77f`, especialización en GitHub main); `12e02ca` (INT-014) publicado; INT-015 + índices en commit docs de P3.


## INT-016 — Cierre P3-B: correcciones quirúrgicas y skills host
- **Estado:** P3-B — PASS según informe de ejecución; publicación de código pendiente de verificación.
- **Documento:** `INT-016_P3B_QUIRURGICAS_CIERRE.md`.
- **PB-01 / G-01:** causa raíz en `op_publish` (faltaba `external_status`) y `_final_status` (fallback `or FAILED`). Fix mínimo reportado; estado canónico `PUBLISHED` reutilizado; fallo auténtico `FAILED` + `PROVIDER_FAILURE` + `recovery` preservado. 10 checks de regresión con fixtures, sin producción.
- **PB-02:** añadidas `skill.youtube.validate` y `skill.youtube.system_status`, LOW/`youtube.read`, sin endpoints nuevos. HITL sigue exclusivo de `publish`.
- **PB-04:** `HARNESS_ALLOWED_PERMISSIONS` documentada.
- **Pendiente:** PB-03/G-02 no implementado (afecta al contrato v1; exige autorización explícita). PB-05 fuera de alcance. G-13 documentado; seed intacto.
- **Tests reportados:** YT-AUT 620/620 (17/17 suites); AG-G especialización 22/22; los 18 fallos de la suite unitaria completa de AG-G son preexistentes e idénticos al baseline.
- **Commits locales reportados:** YT-AUT `a552b3d` + `56be4b9`, rama `p3b-g01-publish-envelope`; AG-G `8859b4b`, rama `p3b-skills-host`. El informe indicó BLOCKED BY AUTH; verificar refs remotos antes de declarar publicados.
- **Seguridad/límites:** no reutilizar el PAT expuesto; revocarlo/rotarlo y usar credencial de mínimo privilegio. No se ejecutó producción, Flow LIVE, render ni publicación real.

## INT-017 — P3-B: Ejecución Quirúrgica G-01 + Skills Host Justificadas (informe técnico)
- **Estado:** P3-B — PASS / PB-01 + PB-02 + PB-04 EJECUTADOS / PB-03 PENDIENTE DE AUTORIZACIÓN / PB-05 FUERA DE ALCANCE.
- **Documento:** `INT-017_P3B_EJECUCION_QUIRURGICA.md` (renumerado desde INT-016: el número quedó ocupado en `main` por el cierre `INT-016_P3B_QUIRURGICAS_CIERRE.md`).
- **PB-01 (G-01 corregido):** `op_publish` devuelve ahora `external_status=PUBLISHED` (estado canónico §9 ya existente) — un publish exitoso ya no se reporta `FAILED`; el fallo auténtico sigue `FAILED`+`errors[]`+`recoverable`. 10 checks de regresión (fixtures, sin producción). Sin cambios en harness.py, permisos, HITL ni máquina de estados.
- **PB-02 (11 skills host):** añadidas `skill.youtube.validate` (→ `youtube.validate_production`) y `skill.youtube.system_status` (→ `youtube.system_status`), ambas LOW/idempotentes/`youtube.read`, con políticas ALLOW-lectura, grants y snapshot actualizados; HITL sigue exclusivo de publish. Tests positivos/negativos/permisos: especialización 22 passed.
- **PB-04 (G-08 cerrado):** `HARNESS_ALLOWED_PERMISSIONS` documentada en `backend/.env.example`.
- **PB-03 (G-02):** definición completa registrada (separar `doctor fix` en op MEDIUM con `youtube.production.launch` o documentar excepción + declarar `ejecutar_tests`); NO implementado — toca clasificación del contrato compartido v1 y exige autorización explícita.
- **Hallazgo nuevo G-13:** metadata declarativa de skills host (`harness_permissions`) no persistida por `SkillContract` del seed (pydantic extra=ignore); mitigado con verificación funcional (`youtube.read` ejercido en el cuerpo HTTP); sin tocar el seed.
- **Tests P3-B:** YT-AUT 17/17 suites PASS (620/620 checks; +10 en harness); AG-G especialización 22 passed; unit completa 18 failed/468 passed/4 skipped con DIFF DE FAILED VACÍO vs `main` de control (mismos 18 pre-existentes, 0 regresiones).
- **Superficies protegidas:** diff total 6 archivos (3 por repo), todos autorizados; production_json/contract/flow_jobs/orquestador/FFmpeg/Flow/HANDS/security/`agent.py`/VÓRTICE/`albra_seed` intactos.
- **Publicación:** COMPLETADA 2026-10-23 — AG-G `p3b-skills-host` (`8859b4b`) → PR #68 (CI 5/5 SUCCESS) → merge `69c79da` en `main` (ruleset, sin bypass); YT-AUT `p3b-g01-publish-envelope` rebaseada sobre `4394f3b` → `5e31cb3` (fix G-01) + `1c384b1` (docs) → push directo a `main` (`4394f3b..1c384b1`). Detalle completo en INT-017 §9.


## INT-018 — Evaluación externa: Agnes Video Generator
- **Estado:** EVALUACIÓN INICIAL COMPLETADA / REFERENCIA SELECTIVA; NO INTEGRAR DIRECTAMENTE.
- **Documento:** `INT-018_AGNES_VIDEO_GENERATOR_EVALUATION.md` (renumerado desde INT-017: número ocupado por el informe técnico P3-B).
- **Repo:** https://github.com/lcy362/agnes-video-generator
- **Ideas potencialmente útiles:** checkpoints y reanudación por escena; productos intermedios de pipeline; taxonomía de keyframes/transiciones/referencias; recuperación de cues de subtítulos; validación de artefactos finales; skills operativas separadas para uso/diagnóstico/contribución.
- **Frontera:** no reemplaza YOUTUBE-AUTOMATION, Production JSON, GoogleFlowMCP ni los jobs/leases/retries/asset lineage existentes; no justifica un nuevo agente audiovisual.
- **Evidencia/alcance:** revisión documental y selectiva de código público; no se clonó ni ejecutó, no se corrieron sus tests ni se verificó generación real.
- **Licencia observada:** MIT; verificar licencia del commit y dependencias antes de copiar código.

## INT-019 — Comparación dirigida basada en código: Agnes ↔ YOUTUBE-AUTOMATION
- **Estado:** COMPLETADA / SOLO LECTURA / SIN IMPORTACIÓN DE CÓDIGO.
- **Documento:** `INT-019_AGNES_COMPARACION_DIRIGIDA.md`.
- **Método:** Agnes clonado en research/ (commit `05d1b2e`, MIT verificado); 6 áreas comparadas con anclas archivo:línea de ambos repos.
- **Veredicto:** capacidades clave YA EXISTEN en YOUTUBE-AUTOMATION; 3 ideas adaptables registradas (R1 QA-ASR del final, R2 preflight libass, R3 conocimiento cue-cache); 7 descartes con motivo; decisión D-008.
- **Frontera:** no importa código, no crea agentes, no sustituye orquestador/Flow/jobs.

## INT-020 — Corrección INT-012: burn_subtitles resiliente
- **Estado:** IMPLEMENTADO / 16/16 checks nuevos / suites relacionadas en verde / **PUBLICADO** (`30535f2..f176103` → `origin/main`, 2026-10-23).
- **Documento:** `INT-020_RENDER_BURN_TIMEOUT_FIX.md`.
- **Causa raíz:** `video.py::burn_subtitles` con `-preset medium` (inconsistente con el módulo) y `TimeoutExpired` sin capturar → tumbaba el pipeline completo (incidente `_hard_e2e_c2_01`).
- **Fix:** `-preset veryfast` + timeout capturado que degrada por el camino honesto existente (`subs_status.json` burned=false → QA warn). Timeout 900 s intacto; sin cambios de contrato ni permisos.
- **Tests:** `tests/test_burn_subtitles_resilience.py` (16) registrada en `run_all.py`; autopublish/flow_mcp_video/gobernanza/qa_forensics re-ejecutadas OK; suite canónica completa re-ejecutada al cierre.
- **Pendiente honesto:** re-run real 4K del HARD E2E (Chrome + sesión del usuario → Antigravity); idempotencia Run 2 de INT-012 sin ejecutar.

## INT-021 — Tipografía de impacto + contraste dinámico de subtítulos (estilo Shorts)
- **Estado:** IMPLEMENTADO — VALIDACIÓN VISUAL REAL PENDIENTE (Antigravity, Windows real).
- **Documento:** `INT-021_TIPOGRAFIA_IMPACTO_CONTRASTE_DINAMICO.md`.
- **Componentes:** `backend/pipeline/typography.py` (NUEVO: luminancia WCAG 2.x, paleta por bandas con contrato doble >= 4.5:1, línea `Style:` ASS, brillo vía signalstats YAVG con fallback 0.5), `backend/data/fonts/Montserrat-ExtraBold.ttf` + `OFL.txt` (NUEVOS, SIL OFL 1.1), `subtitles.py` (SHORTS_HEADER + estilo `shorts`), `video.py` (medición de brillo + fontsdir condicional), defaults a `shorts` en `main.py` / `agent.py` / `adapter.py` / `app.js`.
- **Límite:** libass resuelve el `fontsdir` por familia ID1 — Fontname `Montserrat ExtraBold` (pedir `Montserrat` degrada en silencio a la fuente default; A/B de MD5 congelado en batería S8); estilos legacy byte-idénticos (contrato protegido por test); sin validación visual HARD E2E en la máquina del usuario; cambios aún sin commitear (commit previsto por el integrador).

| INT-022 | MCP Connection Manager — cliente MCP persistente en el backend + panel (badges/toggles/notebookId/Test Pipeline) para GoogleFlowMCP y notebooklm-mcp | `services/mcp_manager.py` · `/api/mcp/*` · `static/app.js renderMCP` · `tools/mcp-setup/` | IMPLEMENTADO — VALIDACIÓN REAL CON SESIÓN GOOGLE PENDIENTE · Doc: [INT-022](INT-022_MCP_CONNECTION_MANAGER.md) |
| INT-023 | Pipeline Orchestrator — handoff de producción NotebookLM → Agente → Google Flow: pre-flight gatekeeper (aborta sin gastar tokens), Stage 1 contexto vía mcp_manager, Stage 2 blueprint con el motor existente (agent.py/script_gen intactos), Stage 3 despacho por escena con personaje consistente @{ref}, PARTIAL_FAILURES + retry quirúrgico, progreso [1/3]→[3/3] (X/Y) en el panel | `services/pipeline_orchestrator.py` · `/api/pipeline/*` · `static/app.js pipeRun/pipeApply` · `.env.example §INT-023` | IMPLEMENTADO — batería 55/55, regresión verde; validación real con sesiones Google pendiente · Doc: [INT-023](INT-023_PIPELINE_ORCHESTRATOR.md) |
