# INT-017 — P3-B: Ejecución Quirúrgica — G-01 + Skills Host Justificadas

**Misión:** P3-B (PB-01/PB-02/PB-04) · **Fecha:** 2026-10-23 · **Dictamen:** P3-B — PASS
**Repositorios:** YOUTUBE-AUTOMATION (p1-work, rama `p3b-g01-publish-envelope`) · AGENTE-GENERAL (ag-integration, rama `p3b-skills-host`)
**Base:** `main` `a3ac4a0` (YT-AUT) y `main` `3afa77f` (AG-G), ambos verificados contra `origin` por fetch anónimo.

---

## 1. Estado inicial verificado (no confiar en informes previos)

- YT-AUT: local `main` = `origin/main` = `a3ac4a0` (INT-015). Working tree limpio antes de actuar.
- AG-G: local `main` = `origin/main` = `3afa77f` (merge PR #67). Worktree de usuario (`feature/youtube-harness`, 93 mods pre-existentes) **intacto**.
- PB-02 confirmado en código real ANTES de implementar: `build_youtube_skills` (skills.py) registraba 9 skills; **ninguna** llamaba a `youtube.system_status` ni `youtube.validate_production` (`skill.youtube.status` → project_status/list_projects; `skill.youtube.doctor` → flow_preflight/production_doctor). No existían bajo otro nombre ni abstracción.

## 2. PB-01 — G-01: publish exitoso reportaba envelope FAILED

### Causa raíz (auditada capa por capa)

Recorrido completo de publicación: `skill.youtube.publish` (host) → `client.execute` → `POST /api/harness/v1/execute` → `harness.execute` → `_dispatch` → `op_publish` → `_final_status` → envelope → host.

- `adapter.py:438-439` (pre-parche): `op_publish` en éxito devolvía `{project_id, job_id, youtube_id, url}` **sin** `external_status`.
- `harness.py:164-165`: para `youtube.publish`, `_final_status` resuelve `out.get("external_status") or FAILED`.
- Resultado del defecto: envelope `status="FAILED"` con `errors=[]` para una subida real exitosa (la BD sí quedaba `published`+`PUBLISHED`+`youtube_id`). Evidencia de reproducción del mecanismo: `Harness._final_status("youtube.publish", {...sin external_status})` → `FAILED`.
- El fallo auténtico usa el camino opuesto y ya correcto: `op_publish` lanza `AdapterError("PROVIDER_FAILURE", recoverable=True)` → `harness.execute` lo convierte en `FAILED` **con** `errors[]` y `recovery.recoverable=True`. Ruta no tocada.
- La ruta no tenía cobertura de tests (publish solo se verificaba como existencia en el registro).

### Cambio mínimo aplicado (2 líneas + comentario)

`backend/services/youtube_harness/adapter.py`:
1. Import: añadido `PUBLISHED` a `from .contracts import ...` (estado canónico ya existente, `contracts.py:36` y `EXTERNAL_STATES:42-45` — **no** se crean estados nuevos ni segundo contrato).
2. Retorno de éxito de `op_publish`: añadido `"external_status": PUBLISHED`.

No se modificó: `harness.py`, máquina de estados, permisos, HITL, riesgo de `publish` (HIGH), ni el vocabulario del contrato.

### Contrato antes/después

| Envelope de `youtube.publish` | Antes | Después |
|---|---|---|
| Éxito real | `status=FAILED`, `errors=[]` (mentiroso) | `status=PUBLISHED`, `errors=[]`, `outputs.external_status=PUBLISHED` |
| Fallo auténtico | `FAILED` + `errors[0].code=PROVIDER_FAILURE` + `recovery.recoverable` | sin cambio |
| Ya publicado (idempotencia) | `FAILED` + `CONFLICT` | sin cambio |
| Ledger (replay mismo execution_id) | guardaba el envelope (mentiroso) | guarda el envelope honesto (`metadata.replayed=True`) |

### Pruebas de regresión añadidas (YT-AUT, `tests/test_harness.py` §11)

10 checks nuevos, todos con fixtures locales (upload simulado, sin red, sin YouTube, sin producción):
éxito→`PUBLISHED` sin errors; outputs con `youtube_id`+`url`+`external_status`; BD `published`+`youtube_id`; replay del ledger conserva el éxito; re-publish→`CONFLICT`; fallo auténtico→`FAILED`+`PROVIDER_FAILURE`+`recoverable`; BD no publica en fallo; éxito y fallo distinguibles por envelope.

## 3. PB-02 — Dos skills host justificadas (read-only)

Confirmada la no-existencia (§1), se añadieron siguiendo el patrón existente (`_mk_contract` + `_handler`), reutilizando operaciones y contratos existentes del arnés — **cero endpoints nuevos**:

| Skill | Operación arnés | Riesgo | Permiso skill (convención seed) | Permiso arnés ejercido | Idempotente |
|---|---|---|---|---|---|
| `skill.youtube.validate` | `youtube.validate_production` (LOW) | LOW | `skill.youtube.validate.execute` | `youtube.read` | sí |
| `skill.youtube.system_status` | `youtube.system_status` (LOW) | LOW | `skill.youtube.system_status.execute` | `youtube.read` | sí |

- **Entradas/salidas/errores** (documentadas también en el manifest del arnés, sin cambios):
  - `validate`: input `production_json` (obligatorio, validado por `input_schema` de la skill ANTES de salir hacia el arnés); output `harness_status`+`outputs{valid, outcome, errors[], warnings[], normalizations[], unidades}`; errores: `BLOCKED`+`VALIDATION` (payload roto), `PERMISSION_MISSING` (sin `youtube.read`). No crea recursos.
  - `system_status`: input `{}`; output `harness_status`+`outputs{harness, providers{nvidia,gemini,whisper,youtube_publish}, counters}`; errores: `PERMISSION_MISSING`.
- **Políticas** (`policies.py`): ambas añadidas a `_SKILL_ACTIONS` y `_READ_SKILLS` → reglas ALLOW-LOW con permiso requerido, grants RBAC y `policy_snapshot.read_only` actualizados automáticamente. HITL sigue siendo exclusivo de `skill.youtube.publish` (verificado en test).
- Los catálogos de nichos/estilos/avatares **permanecen como contexto interno** (sin skills), conforme a INT-015.
- `RETRY_FAILED_STEP` **no** se convirtió en operación nueva (fuera de alcance; INT-015 la marca como capacidad existente en el motor y futura como operación expuesta).

## 4. PB-04 — Documentación de `HARNESS_ALLOWED_PERMISSIONS`

`backend/.env.example`: nuevo bloque que documenta la variable (catalogo de permisos, semántica fail-closed `BLOCKED`, ejemplo de credencial solo-lectura). Solo documentación; G-08 cerrado.

## 5. PB-03 y PB-05 — definidos, NO implementados

- **PB-03** (G-02: `production_doctor action=fix` muta bajo RISK_LOW/`youtube.read` y `ejecutar_tests` no está declarado en `input_fields`): toca la **clasificación del contrato compartido v1** (`capabilities.py` → cambiaría el manifiesto de 19 operaciones y requeriría coordinación host/arnés). INT-015 exige autorización explícita. Cambio mínimo definido: separar `doctor fix` en operación MEDIUM con permiso `youtube.production.launch` (o documentar la excepción y declarar `ejecutar_tests`); contratos afectados: `capabilities.py`, `adapter.py`, `tests/test_gobernanza.py` (fija 19 ops), manifest y matriz INT-015. **Estado: PENDIENTE DE AUTORIZACIÓN (no implementado).**
- **PB-05** (HITL host para `launch`): decisión de gobernanza fuera del alcance de esta misión. No implementado.

## 6. Hallazgo nuevo registrado (G-13, fuera de alcance)

`_mk_contract` (skills.py del host) pasa `metadata={"harness_permissions": ...}` a `SkillContract`, pero el modelo pydantic del seed (`albra_seed/core/base.py::Skill`) no define ese campo y con `extra=ignore` lo descarta silenciosamente: la auditoría declarativa de permisos de arnés por skill **no se persiste** hoy. No se tocó el seed (superficie protegida). Mitigado en esta misión con verificación **funcional**: test `test_skills_pb02_ejercen_youtube_read_ante_el_arnes` (el doble del contrato responde `BLOCKED PERMISSION_MISSING` si la skill no declara `youtube.read` en el cuerpo HTTP). Propuesta futura: campo declarativo en el seed o en el validador.

## 7. Tests y validación (comandos y conteos reales)

- YT-AUT (`python3 tests/…` sobre rama P3-B): **17/17 suites PASS — 620/620 checks, 0 fallos** (harness 65 [55+10], contract 77, transport 54, security 154, prod_doctor 54, prod_json 76, qa_forensics 30, doc_preflight 48, gobernanza 28, skills_auton 34).
- AG-G (`python3 -m pytest tests/unit/test_youtube_specialization.py`): **22 passed** (15 previos + 7 nuevos).
- AG-G unit completa: `18 failed / 468 passed / 4 skipped` — comparación por diff exacto de la lista FAILED contra worktree de control de `main` limpio: **DIFF VACÍO → mismos 18 pre-existentes (proveedores sin claves: audio_transcribe, nvidia_provider, ollama), 0 fallos nuevos, 0 regresiones** (461+7=468 passed).
- HITL/permisos de publicación re-verificados: regla REQUIRE_HITL exclusiva de publish; `youtube.publish` sigue HIGH; destructivas siguen `youtube.destroy`; `system_status`/`validate` BLOCKED sin `youtube.read` (doble fiel del contrato).
- Sin publicación real, sin generación de vídeos, sin pruebas LIVE de Flow, sin producción (mandato §6).

## 8. Superficies protegidas verificadas

Diff total vs `main`:
- YT-AUT (3 archivos, +100/−3): `backend/services/youtube_harness/adapter.py` (G-01, autorizado por la misión), `tests/test_harness.py`, `backend/.env.example`.
- AG-G (3 archivos, +212/−13): `src/albra_specialization/youtube/{skills,policies}.py`, `tests/unit/test_youtube_specialization.py`.

Production JSON y `guion_json`, execution contract, `flow_jobs`, orquestador, `pipeline/video.py` y FFmpeg, Flow export/import, `asset_resolver`, `flow_mcp_client`/GoogleFlowMCP, F5/F5.1 y F2, HANDS y memorydv, security/database, `agent.py` y `/api/chat`, VÓRTICE, `albra_seed`: **cero modificaciones**.

## 9. Estado Git y publicación

- Commits preparados en ramas locales `p3b-g01-publish-envelope` (YT-AUT) y `p3b-skills-host` (AG-G) — ver §commits del informe P3-B.
- **Publicación GitHub: BLOCKED BY AUTH** — no hay credencial con `contents:write` autorizada en esta sesión (el PAT que circuló por el chat se considera comprometido; prohibido reutilizarlo, mandato §5). No se intentó ninguna publicación; no se fingió push. Ruta de publicación cuando exista credencial: AG-G vía rama+PR (ruleset *Protección Main - Clean Room* exige checks); YT-AUT admite push directo a main.
