# INT-015 — P3: Matriz Definitiva de Capacidades AGENTE-GENERAL ↔ YOUTUBE-AUTOMATION

- **Estado:** P3-A COMPLETADO — AUDITORÍA + MATRIZ + GAP ANALYSIS + GOBERNANZA / DICTAMEN: **P3 — PASS**
- **Fecha:** 2026-10-22
- **Base de código auditada:** YOUTUBE-AUTOMATION `main` @ `12e02ca` · AGENTE-GENERAL `main` @ `3afa77f` (especialización ya integrada vía PR #67)
- **Modo:** P3-A (auditar → matriz → gap analysis → arquitectura → priorización). **Cero cambios funcionales.** Propuestas de implementación reservadas a P3-B con autorización arquitectónica (§10).
- **Documento anterior:** INT-014 (P1/P1.5/P2 + matriz preliminar). Este documento la convierte en **matriz definitiva con evidencia del código real**.

---

## 1. Estado inicial

Al comenzar P3 el estado verificado era: P1 — PASS (conexión fría, 272 checks); P1.5 — integración local completa con publicación pendiente de credencial; P2 — PASS (45/45, ciclo sin launch). La publicación pendiente quedó **resuelta durante esta misión**: el PAT proporcionado resultó válido (cuenta `ALBRA8`, scopes `repo, workflow`), la rama `feature/youtube-harness` (`b5b7220`) y la rama de integración (`9bb3870`) fueron publicadas, el ruleset *Protección Main - Clean Room* exigió la vía PR + CI, y el PR #67 pasó 5/5 checks (Python 3.10/3.11/3.12 + dashboard build + Windows) antes del merge `3afa77f`. En YOUTUBE-AUTOMATION (sin rulesets) el commit de documentación `12e02ca` se publicó directamente. Por tanto, la matriz definitiva se audita sobre la base ya publicada: la especialización del host (8 archivos, +1047 líneas) y el arnés V1 conviven en `main` de sus respectivos repositorios.

La entrada P3 era la matriz preliminar de INT-014 §10 (17 skills internas × 19 operaciones × 9 skills host con estados preliminares VERIFIED/MISSING/DIVERGENT/N-A). Esa matriz **no se dio por buena**: cada fila se re-verificó contra el código real mediante tres auditorías paralelas de solo lectura (arnés, host, gaps) y la verificación directa de los hechos disputados. El resultado corrige hechos que los informes previos daban por asentados (§5) y añade hallazgos nuevos (§7).

## 2. Metodología

Tres reglas gobernaron la auditoría. **Primera: auditar el estado real antes de tocar nada** — se ejecutó `git ls-remote` contra ambos remotos, se verificó la no-existencia remota de `feature/youtube-harness` antes de publicarla, y se leyó el código directamente en lugar de confiar en SHAs históricos o informes previos. **Segunda: toda afirmación con evidencia `archivo:línea`** — las tres auditorías (p3-a arnés en `backend/services/youtube_harness/`; p3-b host en `src/albra_specialization/youtube/` + sistemas del seed; p3-c gaps en `production_doctor/`, `flow_jobs.py`, `orchestrator.py`, `agent.py`) produjeron mapas verificables, y los puntos en que los auditores discreparon (nivel de riesgo de `cleanup`, bug del envelope de `publish`) se resolvieron leyendo el código directamente. **Tercera: no asumir que MISSING = implementar** — cada gap se clasificó primero (VERIFIED/DIVERGENT/MISSING/NOT_NEEDED/BLOCKED/FUTURE) y después se decidió acción; ninguna implementación se ejecutó en P3-A.

El ciclo completo fue: estado git real → auditorías profundas de código → verificación directa de disputas → batería completa de tests (§13) → matriz definitiva (§3) → gap analysis (§4–§6) → gobernanza (§8) → decisiones y propuestas (§9–§10). Las superficies protegidas (§12) no fueron tocadas en ningún momento y no se generó vídeo, render, publicación ni tráfico real a YouTube.

## 3. Matriz completa

Leyenda de Estado: **VERIFIED** (verificada con evidencia y test) · **DIVERGENT** (existe pero con desviación semántica o de enforcement) · **MISSING** (ausente realmente) · **NOT_NEEDED** (no debe existir como skill del host) · **FUTURE** (posible en contrato v1.1+). Leyenda HITL: el único REQUIRE_HITL del sistema es `publish` (host, L4). "Sin skill" significa que la operación es alcanzable desde el host solo por la tool cruda `youtube_harness_execute`.

### 3.A Descubrimiento y observabilidad

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Health del arnés | YT-AUT | `youtube_harness/api.py:106-125` | `GET /health` | — (transporte) | auth_guard | LOW | No | harness (§10) | VERIFIED | Mantener |
| A2 | Manifiesto (descubrimiento) | YT-AUT | `api.py:41-68` + `capabilities.py:164-172` + `knowledge.py:215-226` | `GET /manifest[?knowledge=true]` | — (cliente `client.py:87-105`) | auth_guard | LOW | No | harness (sin secretos) | VERIFIED | Mantener |
| A3 | Listar proyectos | YT-AUT | `adapter.py:108-116` → `db.list_projects` + abstract | `youtube.list_projects` | `skill.youtube.status` (compuesta) | `youtube.read` | LOW | No | harness+p2 | VERIFIED | Mantener |
| A4 | Estado de proyecto | YT-AUT | `adapter.py:119-138` → `db.get_project`+escenas+flow_jobs | `youtube.project_status` | `skill.youtube.status` (compuesta) | `youtube.read` | LOW | No | harness (normalización) | VERIFIED | Mantener |
| A5 | Estado Flow (cola) | YT-AUT | `adapter.py:182-199` → `flow_jobs.status_for_project` (flow_jobs.py:1028-1035) | `youtube.flow_status` | `skill.youtube.flow_status` | `youtube.read` | LOW | No | harness+p2 | VERIFIED | Mantener |

Justificación: el bloque de observabilidad está completo y con tests; el host lo consume por sus skills compuestas (`status`, `flow_status`, `doctor`) que ya cubren varias operaciones cada una — no hace falta una skill por operación.

### 3.B Validación y diagnóstico

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | Validar Production JSON (sin crear) | YT-AUT | `adapter.py:239-257` → `production_json.parse_payload+validate` (production_json.py:188,214) | `youtube.validate_production` | **sin skill** | `youtube.read` | LOW | No | harness+p2 (BLOCKED en inválido) | VERIFIED (op) / MISSING (skill) | **P3-B: crear skill host `validate`** |
| B2 | Preflight pre-Flow | YT-AUT | `adapter.py:202-210` → `production_doctor.preflight` (preflight.py:50-427) | `youtube.flow_preflight` | `skill.youtube.doctor` (rama preflight, skills.py:209-211) | `youtube.read` | LOW | No | harness+doc_preflight 48 | VERIFIED | Mantener |
| B3 | Doctor de producción (sistema A–I) | YT-AUT | `adapter.py:213-236` → `production_doctor.audit/fix/verify/report` (production_doctor/__init__.py:44,105,188,217) | `youtube.production_doctor` | `skill.youtube.doctor` (audit/fix/verify/report) | `youtube.read` | LOW **(⚠ fix muta: G-02)** | No | harness+prod_doctor 54 | DIVERGENT (riesgo) | Mantener + **P3-B: alinear riesgo** |
| B4 | QA forense de vídeo | YT-AUT | `adapter.py:260-267` → `video_qa.qa_project` (video_qa.py:274) | `youtube.video_qa` | `skill.youtube.qa` | `youtube.read` | LOW | No | harness+qa_forensics 30 | VERIFIED | Mantener |
| B5 | Salud del sistema (proveedores) | YT-AUT | `adapter.py:161-179` (contadores + `available()` nvidia/gemini/whisper/youtube_publish) | `youtube.system_status` | **sin skill** | `youtube.read` | LOW | No | harness+p2 | VERIFIED (op) / MISSING (skill) | **P3-B: crear skill host `system_status`** (salud pre-launch) |
| B6 | Root-cause de UNA producción fallida | YT-AUT | no existe op dedicada; composición: `project_status` (error adapter.py:90) + `flow_status` + `production_doctor` audit + `video_qa` | — | — | — | — | — | — | DIVERGENT | **FUTURE v1.1** (ver §4.1) |

### 3.C Creación e ingesta

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | Crear proyecto (idea/nicho) | YT-AUT | `adapter.py:272-313` → `db.create_project(mode="idea", meta.via="harness")` | `youtube.create` | `skill.youtube.create` | `youtube.production.create` | MEDIUM | No | harness (ciclo) | VERIFIED | Mantener |
| C2 | Ingerir Production JSON | YT-AUT | `adapter.py:330-348` → `prod_svc.ingest` (production_json.py:649-732; preflight bloqueante si launch) | `youtube.submit_production` | `skill.youtube.submit_production` | `youtube.production.create` | MEDIUM | No | harness+p2 | VERIFIED | Mantener |
| C3 | Guion (scripting) | YT-AUT | `pipeline/script_gen.from_idea` (skill interna CREATE_SCRIPT, services/skills.py:64-66) | vía `launch` | — (interna) | n/a | interno | No | prod_json 76 | VERIFIED | Mantener interno |

### 3.D Producción (pipeline) y ciclo de vida

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 | Lanzar producción | YT-AUT | `adapter.py:351-361` → `orchestrator.start_pipeline` (orchestrator.py:270-293: zombie-check, preflight, job, task) | `youtube.launch` | `skill.youtube.launch` | `youtube.production.launch` | HIGH | **No** (G-03) | harness (RUNNING) | VERIFIED | Mantener (HITL opcional → §10) |
| D2 | Cancelar (lógico) | YT-AUT | `adapter.py:364-380` → `orchestrator.cancel_job` (orchestrator.py:181-189); deja proyecto `failed` (orchestrator.py:801-807) | `youtube.cancel` | **sin skill** | `youtube.production.launch` | MEDIUM | No | harness (CONFLICT 2ª) | VERIFIED (op) / MISSING (skill) | Mantener sin skill (ver §6) |
| D3 | Recuperar leases/zombies | YT-AUT | `adapter.py:383-388` → `flow_jobs.recover_expired` (flow_jobs.py:245-262, MAX_LEASE_CYCLES=3) | `youtube.recover` (idempotente) | `skill.youtube.recover` | `youtube.production.launch` | MEDIUM | No | harness+p2 | VERIFIED | Mantener |
| D4 | Reintentar paso fallido | YT-AUT | motor: `flow_jobs.fail` re-encola (flow_jobs.py:638-737; attempts imagen 3/vídeo 2) + `requeue_for_adaptation` (flow_jobs.py:805-832); pipeline **sin checkpoints por paso** (orchestrator.py:521-818, una tarea asyncio) | — (no existe op) | — | — | — | — | chaos/10_escenas (motor) | VERIFIED (motor) / **FUTURE** (op) | **NO implementar** (§4.2) |
| D5 | Generación de assets (imágenes/TTS/vídeo Flow) | YT-AUT | `pipeline/images.generate_all`, `tts_step.synthesize_scenes`, `flow_jobs.enqueue_project` | vía `launch` (granularidad correcta) | — (skills internas) | n/a | interno | No | suites pipeline | VERIFIED | Mantener interno |
| D6 | Render/FFmpeg | YT-AUT | `pipeline/video.py` (**superficie protegida**) | vía `launch` | — (interna) | n/a | interno | No | suites pipeline | N.A. | NO TOCAR (§12) |
| D7 | Liberar disco (intermedios) | YT-AUT | `adapter.py:457-463` → `video.cleanup_intermediates` (video.py:351-375, guard: solo si MP4 final existe) | `youtube.cleanup` | **sin skill** | `youtube.destroy` | HIGH | No | harness (destructivas) | VERIFIED (op) | Mantener sin skill host (§6); guard correcto |
| D8 | Idempotencia de requests | YT-AUT | ledger kv `harness_exec:<execution_id>` (harness.py:25-57), replay `metadata.replayed=True` (harness.py:77-84) | transversal | — | n/a | transversal | No | harness+p2 (replay) | VERIFIED (G-07/G-08 menores) | Mantener |

### 3.E Publicación

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | Publicar en YouTube | YT-AUT | `adapter.py:393-439` (espejo de main.py:1343-1388) → `youtube_publish.upload` (youtube_publish.py:85-129, subida REAL resumable, 2 scopes Google) | `youtube.publish` | `skill.youtube.publish` | `youtube.publish` | HIGH | **SÍ** (única: host L4_EXECUTE_SENSITIVE, policies.py:43-53) | harness (existencia) | VERIFIED **+ bug G-01** | Mantener + **P3-B: parche G-01** |

### 3.F Destructivas

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | Borrar proyecto | YT-AUT | `adapter.py:442-454`: pid 12-hex (security.py:171-180), cancela job activo, `shutil.rmtree` + purga projects/scenes/jobs/flow_jobs (database.py:308-316) | `youtube.delete` | **sin skill** | `youtube.destroy` | **CRITICAL** | No (G-04) | harness (NOT_FOUND 2ª) | VERIFIED | Mantener sin skill host; diques: permiso propio + `HARNESS_ALLOWED_PERMISSIONS` |
| F2 | Limpieza masiva de fallidos | YT-AUT (VÓRTICE legacy) | `agent.py:460-478` (tope 100, borra carpeta+filas por cada failed) — **excluida del contrato v1 a propósito** (legacy.py:30-32) | — | — | — | — | No | — | NOT_NEEDED | No exponer en el arnés |

### 3.G Contexto interno (catálogos)

| # | Capacidad | Owner | Implementación interna | Op arnés | Skill host | Permiso arnés | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | Catálogo de nichos | YT-AUT | `niches.py:127` (data/niches.json, RLock) | `youtube.list_niches` | **sin skill** | `youtube.read` | LOW | No | harness+p2 | VERIFIED (op) | Contexto interno — **sin skill por simetría** (§6); CRUD nichos NOT_NEEDED |
| G2 | Catálogo de estilos | YT-AUT | `themes.STYLES` hardcodeado (themes.py:22) | `youtube.list_styles` | **sin skill** | `youtube.read` | LOW | No | harness+p2 | VERIFIED (op) | Ídem G1 |
| G3 | Catálogo de avatares | YT-AUT | `db.list_avatars()` (adapter.py:155-158); CRUD en main.py:456-578 | `youtube.list_avatars` | **sin skill** | `youtube.read` | LOW | No | harness+p2 | VERIFIED (op) | Ídem G1; CRUD avatares = dashboard |

### 3.H Infraestructura del host

| # | Capacidad | Owner | Implementación interna | equivalente | Skill host | Permiso host | Risk | HITL | Tests | Estado | Acción |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | Tool transportadora | AG-G | `tools.py:66-111` (`youtube_harness_execute`, is_external, dry-run, timeout 180s, retry 1) | — | base de las 9 | `tool.youtube_harness.execute` (declarativo) | MEDIUM | vía policy | p1+p2+spec 15 | VERIFIED | Mantener |
| H2 | Cliente HTTP | AG-G | `client.py` (Bearer, env `YOUTUBE_HARNESS_URL/API_KEY`, timeout 120s, lazy httpx, errores tipados) | — | — | — | — | — | p1+p2 | VERIFIED | Mantener |
| H3 | Policies host (9 reglas) | AG-G | `policies.py:37-76` (1 REQUIRE_HITL publish + 4 read + 4 mutación) | — | — | — | — | publish | spec 15 | DIVERGENT (D-02: datos no adoptados por runtime) | Mantener; adopción = fase futura |
| H4 | Firewall 60/min | AG-G | `policies.py:83-93` (declarativo; `firewall/firewall.py` no lee `rule.rate_limit`) | — | — | — | — | — | — | DIVERGENT (D-03) | Documentar; enforcement real = arnés |
| H5 | Grants rol `operator` | AG-G | `policies.py:97-104` (rol inexistente en `security/roles.py:64-73`; KeyError sobre registry default) | — | — | — | — | — | — | DIVERGENT (D-04) | Documentar; requerirá bootstrap de roles |
| H6 | Escalera L0–L5 | AG-G | `core/types.py:131-141` + `autonomy/levels.py:61-92` (DEFAULT-DENY L5 en desconocidos) | — | — | — | — | — | test_autonomy | DIVERGENT (D-05: decorativa, sin puente efectivo) | Mantener; puente = fase futura |

**Recuento de cobertura real:** 9 skills host → 11 de 19 operaciones (las compuestas `status` y `doctor` cubren 4 operaciones entre ambas). **8 operaciones sin skill host**: `list_niches`, `list_styles`, `list_avatars`, `system_status`, `validate_production`, `cancel`, `delete`, `cleanup`. De ellas, solo 2 justifican skill nueva en P3-B (`validate_production`, `system_status`); 3 son contexto interno sin necesidad de skill (G1–G3); y 3 destructivas/cancelación se dejan deliberadamente sin skill host (§6, §8).

## 4. Gaps auditados en profundidad

### 4.1 ANALYZE_…FAILURE — DIVERGENT confirmado, con matiz fino

P2 clasificó esta capacidad como DIVERGENT y P3 lo confirma con la causa exacta. La capacidad de análisis **existe** y está expuesta por cuatro operaciones LOW del arnés (`youtube.production_doctor` audit de 9 capas del sistema con taxonomía de hallazgos, `youtube.flow_preflight` barrera bloqueante pre-gasto, `youtube.validate_production` validación de payload sin crear nada, `youtube.video_qa` forense del MP4), además de la skill compuesta host `skill.youtube.doctor`. Lo que no existe es la operación con el sesgo semántico que implica el nombre `ANALYZE_PRODUCTION_FAILURE` (binding interno `services/skills.py:594-596` → `layers.auditar_capas`): **un análisis root-cause de UNA producción fallida, acotado a un `project_id`**, que devuelva causa probable y reparación sugerida para ese proyecto. Hoy lo más cercano es la composición `project_status` (campo `error`, adapter.py:90) + `flow_status` (intentos/estados por job) + `production_doctor` audit (alcance = sistema entero, layers.py audita todos los proyectos/cola/extensión) + `recover`. **Conclusión: no es un hueco de capacidad sino de alcance (scoping) y de nombre.** No se crea skill nueva: la brecha real se cierra en contrato v1.1 con un parámetro de scope por-proyecto en `production_doctor` o una op `analyze_failure(project_id)`, y requiere decisión arquitectónica (ver FUTURE en §11).

Hallazgo colateral de esta auditoría (G-02): `youtube.production_doctor` con `action=fix` aplica reparaciones reales (lista blanca cerrada de 10 reparaciones, repairs.py:287-333: recover_expired_leases, rebuild_job_queue, fail_zombie_pipeline_jobs…) bajo clasificación `RISK_LOW` y permiso `youtube.read` (capabilities.py:83-87), y acepta un input funcional (`ejecutar_tests`) que no está declarado en `input_fields` (adapter.py:222-230). Una operación "de lectura" que muta estado y puede ejecutar baterías de tests en subprocess es una asimetría de riesgo real, aunque el daño potencial esté acotado por la lista blanca.

### 4.2 RETRY_FAILED_STEP — VERIFIED en el motor, FUTURE como operación

Investigación profunda del motor: el retry **ya existe internamente a nivel de asset Flow** y es persistido por job — `flow_jobs.fail` re-encola con `attempts+1` hasta máximos por tipo (imagen 3, vídeo 2, flow_jobs.py:19-20, 638-737), los errores CONFIG_*/ASSET_INVALID son terminales sin reintento (665-691), la re-encola está cerrada contra TOCTOU con token+lease, y existe además `requeue_for_adaptation` (un intento extra vía Flow Adaptation, flow_jobs.py:805-832) y `recover_expired` como la operación `youtube.recover` ya expuesta. El binding interno del registro de skills (`RETRY_FAILED_STEP` → `services.flow_jobs.fail`, skills.py:529-531) describe correctamente ese mecanismo del motor.

A nivel de pipeline orquestado **no hay reintentos ni checkpoints por paso**: los pasos (scripting→images→tts→align→render→subtitles) corren en una única tarea asyncio por job (orchestrator.py:521-818) y el estado del paso se persiste solo como columnas gruesas (`step/progress/message` en jobs, `status` en projects vía `_emit`). "Reintentar UN paso" exigiría checkpointing nuevo — es decir, tocar el orquestador, superficie protegida (§12). El reintento de facto hoy es `youtube.launch` de nuevo: el zombie-check falla el job fantasma y relanza limpio (orchestrator.py:205-215, 274-279), reutilizando imágenes ya en disco (images.py:420-432), TTS por hash de texto y clips Flow existentes — pero en modos idea/url/audio **regenera el guion con coste LLM** (orchestrator.py:607-610). El guard anti-doble-launch (devuelve el mismo job_id mientras haya job activo, 280-281) evita doble render. **Clasificación final: VERIFIED como mecanismo interno del motor · MISSING como op/skill host · FUTURE como operación de contrato (v1.1) · NOT_NEEDED si se acepta la composición status→doctor fix→launch.** Riesgos de exponerlo sin checkpointing: gasto LLM no controlado, estados inconsistentes, duplicación de jobs — por eso NO se implementa en P3.

### 4.3 Las cinco capacidades dudosas — veredicto individual

- **`list_niches`**: op arnés LOW ya expuesta (capabilities.py:68-69). Los datos son `data/niches.json` con RLock (niches.py:115-135). El CRUD de nichos (`create/delete_template`) fue excluido del contrato deliberadamente (legacy.py:24-28) y vive en el dashboard (main.py:975-1006). **Veredicto: contexto interno de producción, no skill del host.** El host necesita leer el catálogo para elegir nicho al crear, y eso ya lo cubre la op; una skill `list_niches` sería simetría estética.
- **`list_styles`**: `themes.STYLES` es un catálogo hardcodeado en memoria que solo afecta prompts de imagen (themes.py:5-22). **Veredicto: contexto interno; misma conclusión.**
- **`list_avatars`**: lectura del CRUD de avatares de la DB; el avatar entra al pipeline vía `project.avatar_id` (orchestrator.py:536-543). **Veredicto: contexto interno; crear avatares desde el host no aporta al contrato v1.**
- **`system_status`**: expone contadores + disponibilidad de proveedores (adapter.py:161-179). **Veredicto: SÍ merece skill host** — es la comprobación de salud natural antes de `launch` (junto a `flow_preflight`), es barata, read-only y se alinea con el patrón existente. Candidato P3-B (PB-02).
- **`validate_production`**: validación estricta del payload sin crear nada (adapter.py:239-257; BLOCKED con `errors[0].code=VALIDATION` si es inválido). **Veredicto: SÍ merece skill host** — es la pieza que falta al flujo seguro completo del host (validar → submit → lanzar). Fue ejercitada en P2 por la capa de cliente crudo; como skill cierra el ciclo. Candidato P3-B (PB-02).

Regla aplicada (mandato §6): **no se crean skills por simetría estética** — solo las dos que el flujo operativo real del host necesita (validar y comprobar salud antes de gastar).

### 4.4 cancel / cleanup / delete — auditoría de destructivas

- **`youtube.cancel` (MEDIUM, permiso `youtube.production.launch`)**: cancelación **lógica** — flag cooperativo + cancelación de la Task asyncio (orchestrator.py:181-189); no destruye nada físico; los assets parciales se reutilizan al relanzar. Matices verificados: un job no cancelable → CONFLICT (adapter.py:369-372); el proyecto queda en estado `failed` con error "Cancelado" (orchestrator.py:801-807), no `cancelled` (D-06). El permiso es coherente con "quién puede lanzar puede parar".
- **`youtube.cleanup` (HIGH, permiso propio `youtube.destroy`, destructive)**: borra SOLO intermedios regenerables del proyecto (clips pre-concat, vídeo silente, concat.txt) **y solo si el MP4 final existe** (video.py:351-375 con guard en 368); conserva final, imágenes, Flow y TTS; segunda llamada devuelve freed=0 (idempotente en efecto). Correcta y acotada; no necesita skill host.
- **`youtube.delete` (CRITICAL, permiso propio `youtube.destroy`, destructive)**: eliminación **física e irreversible** — `shutil.rmtree` de la carpeta de salida completa + purga dura de `projects/scenes/jobs/flow_jobs` (database.py:308-316; la purga de flow_jobs evita jobs huérfanos reclamables por la extensión). Mitigaciones verificadas: project_id exacto 12-hex con `validate_project_id` (security.py:171-180) y contención estricta de ruta (security.py:183-202), cancelación del job activo antes de borrar, `evidence[]` adjunta al resultado, permiso propio que no se otorga por defecto y restringible vía `HARNESS_ALLOWED_PERMISSIONS`. Riesgos residuales documentados: sin guard de estado `published` (borrar un proyecto publicado elimina el rastro local de un vídeo vivo en YouTube — G-04/G-12), y los backups solo cubren DB+token+.env, no los MP4 (backup.py:24-25).
- **`cleanup_failed` (VÓRTICE, `agent.py:460-478`)**: operación masiva (tope 100 proyectos failed más recientes, borra carpeta+filas por cada uno) que fue **excluida del contrato v1 a propósito** (legacy.py:30-32, least privilege). **Veredicto: NOT_NEEDED en el arnés** — si algún día se necesita equivalente, será una op acotada por proyecto, no masiva.

## 5. Divergencias (correcciones a la matriz preliminar de P2)

- **D-01 — Riesgos reales ≠ "11 LOW / 4 MEDIUM / 4 HIGH"**: la distribución real del manifest es **11 LOW / 4 MEDIUM / 3 HIGH / 1 CRITICAL** (`delete` es el único CRITICAL; `cleanup` es HIGH; capabilities.py:108-144). El tratamiento contractual correcto ya existe: las dos destructivas exigen permiso propio `youtube.destroy`.
- **D-02 — La policy host es dato, no enforcement**: las 9 reglas de `policies.py` y los grants no son adoptados por ningún runtime vivo (ni `runtime/agent.py` ni `runtime/loop.py` consumen el SkillRegistry ni registran esas reglas). El enforcement real de la frontera es **100% del arnés** (fail-closed de permisos + auth). No es una brecha de seguridad (el dique fuerte funciona), pero la matriz no debe describir al host como si ya aplicara esas reglas en runtime.
- **D-03 — Rate-limit 60/min declarativo**: `FirewallRule.rate_limit` se declara en `policies.py:90-91` pero el firewall nunca lee ese campo; el rate limiting solo opera con un `RateLimiter` inyectado (firewall.py:110,174-180). El arnés, además, no tiene rate-limit server-side propio.
- **D-04 — Rol `operator` inexistente**: aplicar `recommended_grants()` sobre un RoleRegistry default lanzaría KeyError (roles.py:64-73, permissions.py:97-98). Los grants son aspiracionales hasta que exista bootstrap de roles.
- **D-05 — L0–L5 decorativa**: la escalera existe (`core/types.py:131-141`, matrix DEFAULT-DENY en `autonomy/levels.py`) pero solo se consulta si se inyecta `autonomy_manager` al PolicyEngine y nadie lo hace; no hay puente efectivo con las policies de la especialización. La regla publish declara L4 (policies.py:49) de forma documental.
- **D-06 — `cancel` deja el proyecto en `failed`**: el contrato normalizaría `cancelled→CANCELLED` (contracts.py:65) pero el motor escribe `failed` con error "Cancelado" (orchestrator.py:801-807). Divergencia semántica menor, honesta si se documenta.
- **D-07 — Las 17 skills internas son declarativas**: viven en `services/skills.py` (registro con binding importlib validado) pero **nadie las ejecuta** — el adapter llama a las funciones del motor directamente. La correspondencia skills↔operaciones es semántica, no de ejecución.
- **D-08 — Corrección menor de scopes**: `youtube.admin` expande a los otros 5 permisos del arnés (permissions.py:43-46), **no** a 5 scopes de Google; los scopes Google reales del uploader son 2 (`youtube.upload`, `youtube.readonly`, youtube_publish.py:17-18).

## 6. Capacidades que NO deben existir como skill del host

Por deliberación arquitectónica de P3 (mandato §1.5 y §6): **`list_niches`/`list_styles`/`list_avatars` como skills** (son contexto interno; la lectura ya está expuesta como op LOW y las skills añadirían superficie sin valor); **CRUD de nichos/avatares/estilos en el arnés** (es administración del puesto, vive en el dashboard); **`cleanup_failed` masiva** (excluida del contrato por diseño); **doctor de infraestructura** (`doctor.py` es sondas de stack para el dashboard; lo intercammbio m2m ya lo cubre `system_status` y `/health`); **skill `delete`/`cleanup` host** (exponerlas como skills cómodas sin HITL ampliaría la superficie destructiva; el acceso por tool cruda con permiso `youtube.destroy` restringible es el dique correcto hoy); **`cancel` como skill** (operación de control del ciclo de lanzamiento; quien tenga permiso de launch puede usar la tool; una skill sin HITL no añadiría protección). Esta sección responde directamente al punto 5 del objetivo de la misión: estas capacidades no deben tener skill del host en P3.

## 7. Riesgos (hallazgos nuevos, numerados)

- **G-01 (contrato, alto interés): publish exitoso devuelve envelope `FAILED`.** `harness.py:164-165` resuelve el status de publish como `out.get("external_status") or FAILED`, pero `op_publish` en éxito devuelve `{project_id, job_id, youtube_id, url}` **sin** `external_status` (adapter.py:438-439). Un publish que realmente subió el vídeo reportaría `status=FAILED` (sin `errors[]`). Ruta nunca ejercitada por tests (publish solo verificado como existencia). La BD sí queda `published`+PUBLISHED. Parche trivial en P3-B (PB-01).
- **G-02 (gobernanza): `production_doctor action=fix` muta bajo RISK_LOW/`youtube.read`** y acepta input no declarado (`ejecutar_tests`). Asimetría de riesgo (§4.1).
- **G-03 (gobernanza, decisión consciente): `launch` HIGH sin HITL en el host.** El comentario de `policies.py:68-70` delega la frontera al arnés. Riesgo real de gasto (LLM/imágenes/TTS/Flow). Mantener con justificación documentada; HITL opcional futura (PB-05).
- **G-04 (gobernanza): `delete` CRITICAL sin HITL host y sin guard de estado `published`** (borra el rastro local de un vídeo publicado). Diques actuales: permiso propio + restricción por env + id exacto. No ampliar en P3.
- **G-05 (infra): ledger sin TTL ni purga** (crecimiento indefinido de la tabla `kv`, harness.py:25-48).
- **G-06 (contrato): replay no compara cuerpo** — mismo `execution_id` con otro body devuelve el resultado viejo (harness.py:77-84). Convención de host: execution_id único por intento (ya así funciona en client.py:41-43).
- **G-07 (infra): 400/404/permisos-BLOCKED no quedan en el ledger** (no hay replay de rechazos) — correcto para evitar replay de errores, documentado para que el host no espere replay ahí.
- **G-08 (docs): `HARNESS_ALLOWED_PERMISSIONS` no está en `backend/.env.example`** (solo MASTER_API_KEY y GOOGLE_REDIRECT_URI).
- **G-09 (contrato, menor): `artifacts[]` nunca se llena y `resources` no se usa** en el despacho (contracts.py:256, 142).
- **G-10 (semántica, menor): estado interno `flow_video` escrito a projects.status** (orchestrator.py:687,695) no está en el mapa del contrato → se normaliza a WAITING (honesto, no inventado).
- **G-11 (infra): sin rate-limit server-side en el arnés** — el límite 60/min vive solo (y de forma declarativa) en el host (D-03).
- **G-12 (riesgo residual): backups no cubren MP4** (backup.py:24-25) — relevante combinado con G-04: delete es lo único que destruye medios finales.

## 8. Gobernanza — coherencia de la cadena completa

Cadena auditada por capacidad: L0–L5 → host policy → host skill → harness operation → permission/scope → risk → HITL → execution contract. Resultados:

1. **Sin escaladas de privilegio detectadas.** Toda operación destructiva (delete/cleanup) exige permiso propio `youtube.destroy` que ninguna skill host declara y que no se obtiene por `youtube.production.*`; `youtube.admin` solo expande permisos del propio arnés (permissions.py:43-46) y ninguna skill host lo usa. Declarar permisos de más en el request no otorga nada (permissions.py:21-22) y `HARNESS_ALLOWED_PERMISSIONS` acota por credencial de forma fail-closed.
2. **Sin bypass de policy detectado.** La única operación con efecto externo (publish) es la única con REQUIRE_HITL + L4 en el host; en el arnés la cadena auth_guard (hmac tiempo-constante) → validación estricta → permisos fail-closed → risk/evidence se aplica a todo request sin rutas públicas (ni `/health` ni `/manifest` son públicas, security.py:24-26). La cadena del agente (policy→firewall→approval, runtime/agent.py:632-673) nunca auto-aprueba y existe fail-closed por dispatch durable.
3. **Ninguna operación HIGH/CRITICAL expuesta como LOW.** Riesgo y permiso son coherentes en las 19 operaciones salvo la asimetría G-02 (fix bajo read), ya documentada como propuesta PB-03.
4. **Duplicación de seguridad: no hay segundo sistema.** La especialización host aporta datos de política y un tool externo con dry-run; el enforcement vivo es el arnés. Recomendación respetada del mandato: no crear un segundo sistema de seguridad; cuando el host adopte las reglas en runtime (fase futura), será la misma cadena policy→firewall→approval del seed aplicada a las skills youtube.*.
5. **Inconsistencias host↔arnés registradas como D-02..D-05** (enforcement vs datos): no son brechas de seguridad sino asimetrías de adopción, y la matriz las deja descritas para que ninguna auditoría futura las interprete como protección activa donde hoy es declarativa.

## 9. Decisiones de P3

- **DEC-P3-01 — Vía de publicación respetando el ruleset**: PR + CI en lugar de forzar bypass admin (el ruleset no tiene bypass actors y se decidió no debilitarlo). Resultado: PR #67, 5/5 checks, merge `3afa77f`.
- **DEC-P3-02 — Cero implementación en P3-A**: los gaps reales se propusieron como PB-01..PB-05 (§10) sin ejecutar ninguno, conforme al mandato ("si hay duda: REPORT + STOP").
- **DEC-P3-03 — Skills nuevas propuestas solo para `validate_production` y `system_status`**: criterio = necesidad del flujo operativo real del host, no simetría.
- **DEC-P3-04 — Destructivas sin skill host**: se documentan los diques existentes (permiso propio, env de scopes, id exacto, evidence[]) como suficientes para P3; exponerlas cómodas sin HITL se rechaza.
- **DEC-P3-05 — Correcciones factuales integradas en la documentación** (D-01..D-08): la matriz de INT-014 queda reemplazada por esta versión definitiva; no se borra documentación histórica.

## 10. Propuesta P3-B (requiere autorización arquitectónica; NADA implementado en P3)

| ID | Cambio | Dónde | Tamaño | Riesgo | Justificación |
|---|---|---|---|---|---|
| PB-01 | Añadir `"external_status": "PUBLISHED"` al retorno de `op_publish` en éxito (+ test del envelope) | `youtube_harness/adapter.py:438-439` (+ tests/test_harness.py) | ~3 líneas + test | Muy bajo; corrige bug G-01; no cambia permisos ni superficie | Contracto honesto: éxito debe leerse como éxito |
| PB-02 | Dos skills host read-only: `skill.youtube.validate` (→ `youtube.validate_production`) y `skill.youtube.system_status` (→ `youtube.system_status`) | `src/albra_specialization/youtube/skills.py` + policies + test | ~60 líneas + tests | Bajo; read-only, patrón existente | Cierra el flujo seguro del host: salud→validar→submit→launch |
| PB-03 | Alinear riesgo de `production_doctor action=fix`: separar en op MEDIUM con permiso `youtube.production.launch` (o documentar la excepción y declarar `ejecutar_tests` en input_fields) | `youtube_harness/capabilities.py` + `adapter.py` | media | Bajo-medio (toca clasificación del contrato) | Elimina asimetría G-02 |
| PB-04 | Documentar `HARNESS_ALLOWED_PERMISSIONS` en `backend/.env.example` | `.env.example` | 2 líneas | Nulo | G-08 |
| PB-05 (opcional) | HITL host para `launch` (regla REQUIRE_HITL análoga a publish) — decisión de política, no de código | `policies.py` | ~10 líneas | Bajo | G-03: launch gasta; public ya tiene HITL |

Criterio del mandato §13 aplicado: PB-01 y PB-04 son "pequeño + claramente necesario + no destructivo + compatible + testeable + sin superficies protegidas"; PB-02 igual (todo en la especialización host). PB-03 toca la clasificación del contrato compartido → requiere autorización explícita. PB-05 es decisión de gobernanza. **Ninguno se ejecutó en esta misión.**

**EJECUCIÓN P3-B (2026-10-23, ver INT-017):** PB-01 ✅ EJECUTADO (G-01 corregido + 10 checks de regresión; harness 65 OK) · PB-02 ✅ EJECUTADO (11 skills host, 7 tests nuevos, 22 passed) · PB-04 ✅ EJECUTADO (G-08 cerrado) · PB-03 ⏸ PENDIENTE DE AUTORIZACIÓN (definición completa en INT-016 §5) · PB-05 ⏸ FUERA DE ALCANCE. Hallazgo nuevo registrado en P3-B: **G-13** (metadata declarativa de skills host no persistida por SkillContract del seed; verificado funcionalmente, sin tocar el seed).

## 11. Elementos explícitamente postergados (FUTURE / fuera de P3)

- Op `analyze_failure(project_id)` o scope por proyecto en `production_doctor` (v1.1).
- Op `retry` de pipeline (exige checkpointing por paso — orquestador protegido; hoy basta la composición status→doctor→launch).
- Skills host para `cancel`/`delete`/`cleanup` (y cualquier HITL para ellas: decisión arquitectónica posterior).
- Adopción en runtime de las reglas/grants/firewall del host + bootstrap del rol `operator` (D-02/D-04).
- Puente efectivo L0–L5 ↔ policies de la especialización (D-05).
- TTL/purga del ledger (G-05) y validación de cuerpo en replay (G-06).
- Rate-limit server-side en el arnés (G-11).
- A2A sobre el arnés; cierre de VÓRTICE; conexión HANDS; Google Flow/GoogleFlowMCP; reparación del timeout 900s; pruebas LIVE; generación/render/publicación real.

## 12. Superficies protegidas — confirmación

`production_json`, `guion_json`, execution contract, `flow_jobs`, orchestrator, `pipeline/video.py`, FFmpeg, Flow export/import, asset resolver, `flow_mcp_client`, GoogleFlowMCP, F5/F5.1, F2, HANDS, memorydv, security/database, `agent.py`, `/api/chat`, VÓRTICE: **sin modificaciones** en P3 (cero cambios de código en ambos repos; los diffs publicados son la especialización ya validada en P1.5 y documentación). Las únicas escrituras de esta misión: documentación INT-015 + índices (YT-AUT), worklog e informes fuera de los repos, y los pushes descritos en §14. Si P3-B se autoriza, PB-01/PB-03 tocarían `youtube_harness/` (contrato compartido, NO es superficie protegida pero exige autorización por ser contrato v1) y PB-02 tocaría solo la especialización del host.

## 13. Tests

Comando y entorno: `bash scripts/p3_tests_ytaut.sh` y `bash scripts/p3_tests_agg.sh` (logs en `scripts/p3_test_logs/`, Python 3.12.15 `/home/z/.venv`). YOUTUBE-AUTOMATION @ `12e02ca` — 17/17 suites PASS, **610 checks, 0 fallos, 0 skip**: harness 55 · execution contract 77 · execution transport 54 · security 154 (config 16, csrf 10, docs_auth 12, input_limits 14, job_identity 19, project_isolation 23, project_path 33, ssrf 27) · production_doctor 54 · production_json 76 · qa_forensics 30 · doctor_preflight 48 · gobernanza 28 · skills_autonomia 34. AGENTE-GENERAL @ `3afa77f` — especialización **15 passed** (0.40s); suite unit completa **18 failed / 461 passed / 4 skipped**, con los 18 fallos **idénticos al baseline pre-existente** de P1.5 (audio_transcribe CORS/dev-auth ×9, nvidia_provider sin clave ×8, ollama sin configurar ×1) — 0 fallos nuevos, 0 relacionados con YouTube. Clasificación: los 18 = pre-existentes ambientales (proveedores sin claves del entorno), no introducidos ni agravados por P3.

## 14. Commits

- **AGENTE-GENERAL**: `b5b7220` (feature/youtube-harness, existente) → publicado a `origin/feature/youtube-harness`; `9bb3870` (merge --no-ff sobre 5f277b3) → publicado a `origin/integration/youtube-harness`; **PR #67** (CI 5/5) → **merge `3afa77f` en origin/main**. Sincronización local: `main` 9b28990→3afa77f (ff). Sin commits nuevos de código en P3.
- **YOUTUBE-AUTOMATION**: `12e02ca` (INT-014) publicado a origin/main (ff 3e15beb→12e02ca); **commit de P3**: INT-015 + índices (SHA en el mensaje final del informe; docs only).
- **Regla de credenciales cumplida**: el PAT se usó transitoriamente vía credential helper en memoria; no se escribió en ningún archivo, repo, log ni documentación; se recomienda su rotación al cierre de la sesión.
