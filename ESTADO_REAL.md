# ESTADO REAL del sistema — inventario honesto

> **Regla de oro (lección del incidente de 2026-10):** nada se declara
> "terminado" sin una batería de tests que lo respalde en este repo.
> Si no está aquí, no existe. Este documento se actualiza con cada hito.

---

## 1. Incidente registrado

Se llegó a reportar como **terminado** un "FLOW BRIDGE REAL" con: cola SQLite
`flow_jobs` (claim atómico, leases, heartbeat, reintentos), 6 endpoints
`/api/extension/flow/jobs*` (v2.16.2), `extension/bridge.js` y auto-render.
**Nada de eso existía en el repo** (sin commit, sin rama, sin stash).

Consecuencia: batería de humos `tests/test_humos_infra.py` — verifica que
todo lo que declaramos **existe físicamente en el código**, y este documento
mantiene el inventario público.

## 2. Lo que EXISTE hoy (verificado con código + tests)

| Componente | Estado | Verificación |
|---|---|---|
| Adapter Production JSON (parse → validate → ingest) | ✅ real | `test_production_json.py` (76 checks) |
| **P1 Golden Contract**: `video_prompt` del Creative Engine llega **verbatim** al payload de Flow (transformacion/generic + artesano); gana sobre `ai_stages` y sobre plantillas; `duration_target` llega al export | ✅ real | `test_flow_contract_p1.py` (44 checks) |
| Campos del contrato preservados: `image_prompt`, `duration_target`, `initial_state`, `action`, `change`, `final_state`, `audio`, `references`, `casting`, `story_function`, `niche_extra` | ✅ real | `test_flow_contract_p1.py` |
| **Flow Bridge backend**: tabla `flow_jobs` (SCHEMA en `database.py`), claim atómico `BEGIN IMMEDIATE` + `job_token` nonce, lease imagen 8 min / video 15 min, heartbeat, reintentos imagen 3 / video 2 → `dead`, recuperación perezosa de leases expirados, re-enqueue idempotente | ✅ real | `services/flow_jobs.py` + `test_flow_bridge.py` (48 checks) |
| **6 endpoints** `/api/extension/flow/jobs*` (enqueue · next · heartbeat · complete · fail · status) + CORS para la extensión | ✅ real | `main.py` + `test_flow_bridge.py` vía httpx ASGI |
| Validación de assets: PNG/JPEG/WEBP con PIL · MP4 con ffprobe (>0.3s) | ✅ real | `test_flow_bridge.py` |
| Convención de assets: `data/output/<pid>/flow/Escena_NN_flow.png` + `Escena_NN_video_<part>.mp4` | ✅ real | igual que `flow_import.py` |
| Mapeo final escenas (`image_path`) + **auto-render** `orchestrator.start_flow_render` al completar el proyecto | ✅ real | `test_flow_bridge.py` (mock del render) |
| **Extensión**: `extension/bridge.js` (poll → claim → heartbeat → complete/fail), wiring `[bridge v1]` en `background.js`, botón "Puente Backend" en popup, README | ✅ existe · sintaxis verificada (`node --check`) | `test_humos_infra.py` |
| **FIXTURE GOLDEN OFICIAL** `tests/fixtures/GOLDEN_PRODUCTION_JSON_EXECUTION_CONTRACT_V1.0.json` (datos sintéticos con sentinels, NO prompts creativos reales): ejecutable de punta a punta — fixture → ingest REAL con DB → roundtrip meta JSON → script.json (P1 verbatim) → cola → claim → complete → QA | ✅ real | `test_golden_fixture.py` (30 checks) |
| **Video QA** (`services/video_qa.py` + `GET /api/video_qa/{pid}` + tool MCP): QA con ffprobe/PIL por escena (imagen mapeada o cruda en `flow/`, clips con duración/resolución/fps/códec/audio) + render final con reglas duras; **forense de medios**: muestrea frames (25/50/75%) para detectar pantalla negra/azul y mide `max_volume` para detectar audio completamente silencioso (warns, no bloquean); reporta flags error/warn/ok sin reventar | ✅ real | `test_golden_fixture.py` §7 + `test_qa_forensics.py` (30 checks con assets enfermos fabricados) |
| **Métricas/observabilidad** (`services/metrics.py` + `GET /api/metrics` + tool MCP `metricas`): proyectos/jobs/cola Flow por estado, dead por tipo, escenas sin imagen, disco de `data/output` + **v2.19: tasas §28** (producción/pasos/reintentos/QA/publicación — lo no medible queda `null` honesto) + `persist_snapshot()` JSONL (recorte 500) tras cada corrida de pipeline | ✅ real | `test_gobernanza.py` §4 + snapshot puro de agregados |
| **Tools MCP de operación**: `flow_encolar` · `flow_estado` · `video_qa` · `metricas` + **gobernanza v2.19**: `memoria_resumen` · `memoria_consolidar` · `skills_validar` (server 25 tools) | ✅ real | dispatch real en `test_gobernanza.py` §5 + conteo auditado (`test_guion_json.py`, `test_merge_216_pyav.py`) |
| **Concurrencia**: 8 workers en raza sobre BEGIN IMMEDIATE (cero dobles claims, tokens únicos), aislamiento multi-proyecto con filtro pid, token de una sola era (409 tras re-claim), completes paralelos, enqueue en caliente | ✅ real | `test_concurrencia.py` (18 checks) |
| **Chaos**: reinicio REAL de proceso (subprocess reabre la SQLite y reclama), rollback atómico a mitad de escritura, doble complete → 409 sin sobreescribir asset, HTML de Flow → 422 → dead por intentos, dead → re-enqueue limpio, heartbeat/complete sobre estados imposibles, carrera zombie | ✅ real | `test_chaos.py` (28 checks) |
| **Escala (TEST 4 de la misión)**: proyecto de 10 escenas → 19 jobs (última escena solo-imagen por P1), contrato P1 verbatim por job + prompt de ~11KB intacto, orden de claims imágenes→videos, heartbeat/fail-retry/zombie/doble complete a escala, 10/10 escenas mapeadas, auto-render una vez, QA a escala, re-enqueue idempotente | ✅ real | `test_10_escenas.py` (44 checks) |
| **E2E extensión**: `bridge.js` REAL en sandbox VM (stubs Chrome MV3) contra backend mock HTTP con estado — claim→complete con bytes PNG validados, fail, 422→fail con detail, heartbeat true/409 false, cola vacía, backend caído no tumba el bucle, canal popup, anti-duplicado | ✅ real (capa contrato, sin Google Flow real) | `tests/e2e_bridge_mock.js` + `test_bridge_e2e.py` (24 checks Python + 26 en el harness) |
| **Boot vivo + ciclo completo por HTTP real**: uvicorn arrancado de verdad en sandbox aislado — startup, CORS preflight de la extensión, endpoints base, métricas, video QA; y ciclo Flow Bridge de punta a punta por HTTP: enqueue (build_script_json) → claim ordenado → complete con PNG/MP4 reales (PIL/ffprobe) → 409 doble complete → 422 HTML → fail/retry (attempts) → guard de tipo → project_done → **auto-render disparado** → status final → QA "ok" | ✅ real (capa HTTP; render de fondo sin claves TTS en sandbox) | `tests/live_boot_smoke.sh` + `tests/live_cycle_smoke.sh` vía `test_live_boot.py` (33 checks) |
| **PRODUCTION DOCTOR V1.0** (`services/production_doctor/` + CLI + API + MCP): diagnóstico por capas A-I del pipeline completo con evidencia medida; taxonomía de 8 clasificaciones (UNKNOWN → HUMAN INVESTIGATION REQUIRED; Google Flow → EXTERNAL_SERVICE_ERROR); DOCTOR AUDIT/FIX/VERIFY/REPORT; **lista blanca cerrada de 10 reparaciones deterministas** (nunca toca producción creativa — verificado con SHA-256 del `production.json` tras fix); **audit trail** append-only en `data/doctor/audit_trail.jsonl` con antes/después; **REAL FLOW PREFLIGHT** (backend/extensión/bridge/contrato/cola/herramientas → `REAL FLOW PREFLIGHT PASS` o `REAL FLOW BLOCKED` con motivos); revisión del V1.0: **criterio contractual estricto de `video_prompt`** (si el proyecto genera clips, TODA unidad que deba generar video exige `video_prompt` — no basta con que exista al menos uno; solo la última queda exenta por ser SOLO-imagen por diseño; con 0 unidades de video el criterio no aplica) y **EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME CONNECTED** (`P-EXT-RUNTIME`: CONNECTED solo con evidencia real — job claimed con worker y lease vigente; sin evidencia se clasifica `NOT_DEMONSTRATED`/UNKNOWN y NUNCA como PASS, no bloqueante) | ✅ real | `test_production_doctor.py` (54 checks) + `test_doctor_preflight.py` (38 checks); docs: `docs/PRODUCTION_DOCTOR.md` |
| Tools MCP de diagnóstico: `production_doctor` (audit/fix/verify/report) y `real_flow_preflight` (server 25 tools) | ✅ real | dispatch verificado + conteo auditado en `test_guion_json.py` y `test_merge_216_pyav.py` |
| **QA GATE del render (§render/§publishing)**: `_gate_qa_final` en orchestrator — qa_video(final=True) con severidad error → proyecto **FAILED** (nunca ready por mera existencia del archivo); reporte en `meta.qa_final`; degradaciones de `subs_status.json` (subtítulos no quemados) y `music_track.json` suben como warn/registro; `POST /api/publish/{pid}` y el autopublish se **bloquean** si QA final tiene errores | ✅ real | `test_gobernanza.py` §1 + `test_autopublish_generate.py` (45 checks) |
| **Seguridad v2.19 (§30)**: `security.safe_filename` (path traversal/hidden en `/api/import/audio` + tope 50 MB), `validar_url`/`safe_fetch_bytes` anti-SSRF (file://, loopback, privadas, metadata 169.254, credenciales, redirects revalidados) aplicado al plan C de imágenes y al probe del Doctor; **v2.19.1: `allow_private` opt-in solo para el backend PROPIO (default de config) — el probe del Doctor contra 127.0.0.1 vuelve a poder pasar (regresión detectada por clean-room real) y las backend_url externas conservan la guardia estricta; metadata 169.254/0.0.0.0/file:// bloqueadas incluso con allow_private**; `auth_guard` cubre `/mcp` con MASTER_API_KEY; token OAuth con chmod 0600; deadline 30 min en upload; `sanitize_external_text` neutraliza inyección de instrucciones en transcripciones/títulos scrapeados | ✅ real | `test_security_hardening.py` (47 checks) |
| **MemoryDV (§memoria)**: `services/memorydv.py` — memoria aislada del dominio (EPISODIC/SEMANTIC/PROCEDURAL/FACTUAL + candidatos), 18 campos del contrato por registro, storage JSONL en `data/memorydv/` (gitignored), consolidación controlada (observación → patrón → candidato → **validación con regresión obligatoria** → promoción), decaimiento, utility; gancho: cada corrida de pipeline deja episodio y cada `fail()` de la cola deja observación; nunca modifica código ni pipeline (§self-improvement) | ✅ real | `test_memorydv.py` (36 checks) + gancho en `test_gobernanza.py` §3 |
| **Skill Contract + Autonomía (§skills/§26)**: `services/skills.py` — 17 skills mínimas con los 16 campos del contrato, `validate_registry` resuelve targets reales con importlib y verifica regresiones en disco; `services/autonomy.py` — L0 OBSERVE … L5 SELF-IMPROVE con mapa acción→nivel (publicar=L3, doctor fix=L4, self-improve=L5) y `assert_no_bypass` (self-improvement jamás autoriza publishing/seguridad) | ✅ real | `test_skills_autonomia.py` (34 checks) |
| **Contrato A2A (§25)**: `POST /api/agent/execute` — puerta formal para agentes externos (Creative Engine): exige `requester`+`creative_spec`; respuestas honestas `VALIDATION_ERROR` / `REQUIRES_CLARIFICATION` / `ACCEPTED` / `EXECUTING` con {status, production_id, result, evidence, confidence, execution_id, warnings} | ✅ real | wiring auditado en `test_security_hardening.py` §6 + contrato en `main.py` |
| **Cola endurecida (§14-§17)**: `fail()`/`heartbeat()` con UPDATE condicional dentro de BEGIN IMMEDIATE (TOCTOU cerrado: un fail/heartbeat zombi ya no roba el claim del nuevo worker); barrido de leases vencidos con `lease_cycles` (MAX_LEASE_CYCLES=3 → dead: **no reintentar infinitamente**); re-enqueue conserva jobs claimed con lease vigente (trabajo en vuelo no se descarta) | ✅ real | `test_gobernanza.py` §2 + `test_concurrencia.py` + `test_chaos.py` sin regresión |
| **Publicación como máquina de estados (§22)**: publish_state en meta (DRAFT→PUBLISHING→PUBLISHED/FAILED), cada intento = job `kind=publish` (historial), 409 idempotente si ya hay `youtube_id` (nunca doble upload), autopublish omitido si QA final con errores | ✅ real | `test_gobernanza.py` §7 + `test_autopublish_generate.py` |
| Suite canónica | ✅ 21 baterías en `tests/run_all.py` (840 checks) | runner |

## 3. Lo que AÚN NO está demostrado (límites honestos)

- **E2E con Google Flow REAL**: no se ha demostrado una ejecución de punta a
  punta generando assets en labs.google con la extensión instalada en Chrome.
  El contrato backend↔extensión SÍ está probado en la capa navegador
  (`e2e_bridge_mock.js`), pero la inyección en el Slate de Labs, la descarga
  de blobs reales y la subida a un backend vivo requieren corrida manual con
  Chrome + sesión de Google. **No se declara éxito E2E real.**
- **Auto-render real disparado desde el bridge**: probado con mock de
  `start_flow_render`; el render completo (TTS + Ken Burns + mezcla +
  subtítulos) se prueba en las baterías de merge, pero el disparo automático
  con assets reales de Flow aún no se ha corrido de punta a punta.
- **Calidad visual del video final**: el QA mide propiedades técnicas
  (duración, resolución, fps, audio); la calidad creativa sigue siendo
  revisión humana. La distinción TECHNICAL PASS / TECHNICAL FAIL /
  CREATIVE REVIEW REQUIRED queda parcial: `error`/`ok` son técnicos y `warn`
  (forense) es el equivalente de «revisión», pero no hay canal creativo
  separado explícito.
- **Anti-SSRF por resolución**: `validar_url` bloquea esquemas/hosts privados
  y revalida redirects, pero no DNS rebinding (IP cambia entre validar y
  conectar). Para exposición pública, complementar con firewall/egress.
- **Pasos de aprobación de publicación (§22 APPROVED)**: el publish manual
  exige QA final sano + flags, pero no hay un estado APPROVED intermedio con
  aprobador explícito; la fábrica publica solo bajo flags explícitos
  (autopublish/botón) — gateway de aprobación multi-actor pendiente.
- **provider_calls por etapa**: no hay log por-llamada (latencia/coste) de
  proveedores externos; las tasas §28 se computan de los estados persistidos
  (jobs/flow_projects/flow_jobs) y algunas quedan `null` honestas
  (queue_latency, render_time, recovery_rate).
- El fixture Golden usa prompts sintéticos (sentinels CE_SENTINEL_*) por
  diseño de prueba; cuando exista un Production JSON REAL del Creative
  Engine se añade como fixture adicional sin cambiar el contrato.

## 4. Mantenimiento de este documento

1. Cada hito nuevo actualiza la tabla de la sección 2 con su batería.
2. Prohibido marcar ✅ sin test que lo respalde en este repo.
3. Los límites de la sección 3 solo se mueven a la sección 2 con evidencia.
