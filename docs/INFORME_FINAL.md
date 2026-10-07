# INFORME FINAL — YOUTUBE-AUTOMATION · Finalización (PROMPT 07)

> Fecha: 2026-10-07 · Alcance: endurecimiento y cierre de brechas sobre la
> arquitectura existente. **Sin reconstrucciones**: AUDIT → VALIDATE → ADAPT.
> Principio rector: no declarar nada sin batería que lo respalde.

---

## A. ESTADO

**READY WITH LIMITATIONS** — producción de videos desde Creative Production
JSON completamente operativa y endurecida (cola, QA, seguridad, gobernanza).
Las limitaciones son honestas y están inventariadas en §O y en
`ESTADO_REAL.md §3`; la principal: el E2E con Google Flow real (Chrome +
sesión del usuario) sigue sin demostrarse y el sistema **no lo finge**.

## B. CAPACIDADES EXISTENTES (lo que YA funcionaba y se preservó)

- Pipeline completo CREATIVE SPEC → SCRIPT → IMAGE → TTS → VIDEO → SUBTITLES
  → MUSIC → RENDER → QA con gates anti-degradación (`_gate_imagenes_reales`,
  `_gate_voz_real`) y contratos P1 (video_prompt verbatim).
- Cola `flow_jobs`: claim atómico `BEGIN IMMEDIATE` + `job_token`, leases
  (imagen 8 min / video 15 min), heartbeat, reintentos (3/2) → `dead`,
  recuperación perezosa, re-enqueue idempotente. Probada en raza (8 workers),
  caos (reinicio real de proceso) y escala (10 escenas / 19 jobs).
- Video QA técnico + forense de medios (negro/azul/silencio, warn no bloqueante).
- PRODUCTION DOCTOR V1.0: capas A-I, taxonomía de 8 clases, lista blanca de
  10 reparaciones, audit trail JSONL, REAL FLOW PREFLIGHT con criterio
  estricto de `video_prompt` y `STRUCTURAL READY ≠ RUNTIME CONNECTED`
  (NOT_DEMONSTRATED, nunca PASS).
- Extensión Chrome (bridge MV3), MCP (JSON-RPC 2.0), métricas, backups,
  preflight de lanzamiento del Adapter, biblioteca, scheduler fábrica.

## C. CAMBIOS REALIZADOS (v2.19)

| # | Cambio | Archivo(s) |
|---|---|---|
| 1 | **QA gate del render** (`_gate_qa_final`): `qa_video(final=True)` con error → proyecto **FAILED** antes de `ready`; reporte en `meta.qa_final`; degradaciones de `subs_status.json`/`music_track.json` registradas (antes silenciosas) | `pipeline/orchestrator.py`, `pipeline/video.py` |
| 2 | **Anti-SSRF**: `validar_url`/`safe_fetch_bytes` (esquema, hosts privados/loopback/metadata, credenciales, redirects revalidados) en plan C de imágenes y probe del Doctor | `security.py`, `pipeline/images.py`, `production_doctor/layers.py` |
| 3 | **Path traversal** cerrado en `/api/import/audio` (`safe_filename` + uuid + tope 50 MB) | `security.py`, `main.py` |
| 4 | **Auth `/mcp`** bajo MASTER_API_KEY (antes el MCP quedaba fuera del guard) | `main.py` |
| 5 | **Anti-inyección de instrucciones**: `sanitize_external_text` aplicado a transcripciones URL y títulos scrapeados de trends | `pipeline/sanitizer.py`, `script_gen.py`, `trend_research.py` |
| 6 | **TOCTOU cerrado**: `fail()`/`heartbeat()` con UPDATE condicional por token dentro de `BEGIN IMMEDIATE` | `services/flow_jobs.py` |
| 7 | **Anti zombie-loop**: barrido de leases con `lease_cycles` (MAX=3 → dead); pérdida de lease no consume attempts | `flow_jobs.py`, `database.py` (migración) |
| 8 | **Re-enqueue seguro**: conserva claimed con lease vigente (no descarta trabajo en vuelo) | `flow_jobs.py` |
| 9 | **MemoryDV** (§memoria): memoria aislada del dominio, 18 campos del contrato, consolidación con validación+regresión obligatoria para promover; ganchos episódicos en pipeline y cola | `services/memorydv.py` (nuevo) |
| 10 | **Skill Contract** (§skills): 17 skills con 16 campos, targets reales verificados por importlib, regresiones mapeadas | `services/skills.py` (nuevo) |
| 11 | **Autonomía L0-L5** (§26): mapa acción→nivel (publicar=L3, doctor-fix=L4, self-improve=L5), `assert_no_bypass` | `services/autonomy.py` (nuevo) |
| 12 | **Contrato A2A** (§25): `POST /api/agent/execute` con VALIDATION_ERROR / REQUIRES_CLARIFICATION honestos | `main.py` |
| 13 | **Publishing** (§16/§22): 409 idempotente, publish_state (PUBLISHING→PUBLISHED/FAILED), job `kind=publish` por intento, autopublish omitido con QA en error, deadline 30 min, token chmod 0600 | `main.py`, `orchestrator.py`, `youtube_publish.py` |
| 14 | **Métricas §28**: tasas (producción/pasos/reintentos/QA/publish) + persist JSONL tras cada corrida; no medibles = null honestas | `services/metrics.py`, `orchestrator.py` |
| 15 | **Doctor fixes**: capa H leía claves inexistentes (`imagenes/videos` → `scenes`), preflight ahora persiste su informe, reparaciones que revientan ya NO marcan `reparado` (expuso y corrigió un SQL roto LATENTE en `deaden_exhausted_queued`), CLI `--capas` implementado | `production_doctor/*` |
| 16 | **Timeout Gemini** por intento (§17); **disclosure** del motor de guion (`script_engine` en meta) | `gemini_client.py`, `orchestrator.py` |
| 17 | **MCP de gobernanza**: `memoria_resumen`, `memoria_consolidar`, `skills_validar` (25 tools) | `services/mcp_server.py` |
| 18 | **Cobertura recuperada**: `test_autopublish_generate.py` (571 líneas huérfanas) cableada al runner con final MP4 real | `tests/run_all.py`, `tests/test_autopublish_generate.py` |
| 19 | **4 baterías nuevas**: seguridad (47), gobernanza (28), MemoryDV (36), skills+autonomía (34) | `tests/` |

## D. COMPONENTES PRESERVADOS (no tocados)

Contratos P1 y Golden Fixture · `production_json.py` (política del Adapter) ·
prompts y Production JSON creativos · semántica de estados de `flow_jobs` ·
extensión Chrome (solo lectura) · Doctor V1.0 (arquitectura intacta, fixes
puntuales) · start.sh/start.bat · manifest 2.2.0 de la extensión · patrones
herméticos de la suite existente.

## E. PROBLEMAS REALES ENCONTRADOS DURANTE LA AUDITORÍA

1. **Path traversal crítico** en upload de audio (escritura arbitraria).
2. **SSRF total** (aceptaba `file://` y metadata 169.254.169.254).
3. **QA no bloqueaba nada**: renders inválidos llegaban a ready/publish.
4. **TOCTOU** en fail/heartbeat (robo de claim → trabajo Flow duplicado).
5. **Zombie-loop infinito** (lease expirado sin contador → reciclaje eterno).
6. **SQL roto latente** en `deaden_exhausted_queued` (SQLite no concatena
   literales adyacentes) — enmascarado por un flag `reparado` deshonesto.
7. **Cobertura huérfana**: batería de autopublish fuera del runner.
8. **Doctor capa H ciega** (claves de dict incorrectas → hallazgos perdidos).
9. **MCP sin auth** incluso con clave maestra; publish duplicable; sin
   estados de publicación; token OAuth sin permisos 0600; upload sin deadline.
10. **Versiones incoherentes** (2.18.0 ×6, 2.2.0, «v2.0») — unificadas en 2.19.0.

## F. TESTS (resultados exactos)

`python3 tests/run_all.py` → **TOTAL: 830 OK · 0 fallos en 21 baterías**.
Basal previo: 640 OK / 16 baterías → **+190 checks, +5 baterías, 0 regresiones**.
Detalles por batería en `tests/README.md` (tabla completa).

## G. E2E (resultados exactos)

- Cadena completa mock: `test_golden_fixture.py` 30/30 (fixture → ingest →
  export P1 → cola → claim → complete → QA) y `test_10_escenas.py` 44/44
  (escala + fail/retry + zombie + idempotencia).
- **E2E HTTP real**: `test_live_boot.py` 33/33 — uvicorn real en sandbox:
  ciclo enqueue → claim → complete (PNG/MP4 reales validados) → 409/422 →
  fail/retry → project_done → auto-render → QA "ok".
- Recuperación y crash: `test_chaos.py` 28/28 (reinicio real de proceso,
  rollback, zombie), `test_concurrencia.py` 18/18.
- Duplicados → idempotencia: doble complete 409, re-enqueue created=0,
  publish 409 con youtube_id previo (nuevo).

## H. CLEAN-ROOM (resultado exacto)

`git archive HEAD yt_automation_v2` → árbol fresco (sin DB, sin `.env`, sin
cachés, sin outputs) → `python3 tests/run_all.py` →
**TOTAL: 830 OK · 0 fallos en 21 baterías** (incluye boot vivo HTTP real).
Hallazgo del clean-room: aserciones de coherencia de versión detectaron el
bump 2.19.0 → corregidas (la batería hizo su trabajo de detector).

## I. GOOGLE FLOW (3 estados separados)

| Estado | Valor | Evidencia |
|---|---|---|
| INTEGRATION IMPLEMENTED | ✅ | bridge.js + flow_jobs + 6 endpoints + auto-render |
| PREFLIGHT VERIFIED | ✅ (mecánico) | REAL FLOW PREFLIGHT: `P-*` PASS + `extension_runtime: NOT_DEMONSTRATED` cuando no hay lease vivo (nunca PASS sin evidencia) |
| REAL EXECUTION VERIFIED | ❌ NO demostrado | requiere Chrome + sesión Google del usuario; el sistema no lo finge (`ESTADO_REAL.md §3`) |

## J. MEMORYDV (estado real)

Implementado y aislado al dominio (`services/memorydv.py`): 4 tipos + candidatos,
18 campos del contrato, consolidación §9 (observación → patrón ≥3 → candidato →
validación → promoción con regresión obligatoria), decay/utility, ganchos
episódicos reales (pipeline y cola). 36 checks. **No modifica código ni
pipeline** (§11): la promoción solo produce memoria verificada.

## K. SKILLS (estado real)

`services/skills.py`: las 17 skills mínimas del contrato con los 16 campos,
cada una vinculada a su función real (`validate_registry` lo prueba por
importlib y verifica que las regresiones existen en disco) + diferenciación
TOOL/SKILL/MEMORY/KNOWLEDGE/FEEDBACK/LEARNING/SELF-IMPROVEMENT. 34 checks.
`success_rate` comienza en 0 con `origin="registrar_on_first_use"` (honesto:
se medirá con `mark_validated`).

## L. DOCTOR (estado real)

PRODUCTION DOCTOR V1.0 intacto en arquitectura; fixes de honestidad y alcance:
capa H ve los hallazgos por escena, preflight persiste informe, reparaciones
fallidas no se marcan reparadas (expuso SQL roto latente, ya corregido),
`--capas` en CLI, `audit(capas=…)` en API. 54 + 38 checks.

## M. SELF-IMPROVEMENT (estado real)

Controlado: las observaciones consolidan en MemoryDV → candidatos → promoción
que **exige regresión en disco** y jamás toca pipeline/código/providers/
security/publishing. Autonomía L5 solo para promoción de memoria y con
`assert_no_bypass` (self-improvement no autoriza publishing ni seguridad).

## N. PUBLISHING (estado real)

QA gate obligatorio (render con errores no publica), 409 idempotente,
publish_state + historial de intentos (job `kind=publish`), autopublish
omitido con QA en error, deadline de upload, token 0600. Límite honesto:
no hay estado APPROVED con aprobador multi-actor (§O).

## O. LIMITACIONES (solo las reales)

1. E2E Google Flow real pendiente (manual, Chrome + sesión del usuario).
2. Sin DNS-rebinding guard (complementar con firewall si se expone a internet).
3. Sin gateway de aprobación APPROVED multi-actor para publishing.
4. Sin provider_calls por llamada (latencia/coste por proveedor); tasas no
   medibles quedan `null`.
5. TECHNICAL PASS/FAIL vs CREATIVE REVIEW: el canal creativo explícito no
   existe (warn forense ≈ revisión humana).
6. MASTER_API_KEY es todo-o-nada (sin roles por nivel L0-L5 en la API).

---

**Definición de Done (§37)**: AUDIT ✅ · PIPELINE ✅ · QUEUE ✅ ·
LEASE/RECOVERY ✅ · RETRY ✅ · IDEMPOTENCY ✅ · VIDEO QA ✅ · DOCTOR ✅ ·
SECURITY ✅ · MEMORYDV ✅ · SKILLS ✅ · PROVIDER ✅ (adaptación mínima +
honestidad de estados) · OBSERVABILITY ✅ (con nulls honestos) · TESTS ✅
(830/21) · E2E ✅ (mock + HTTP real) · CLEAN-ROOM ✅ (830/21 fresco) ·
REGRESSION ✅ (0 fallos). Con la salvedad honesta de REAL EXECUTION (Google
Flow) y las limitaciones §O.
