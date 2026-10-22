# INT-014 — INTEGRACIÓN AGENTE-GENERAL ↔ HARNESS V1 (P1 CONEXIÓN FRÍA + P1.5 PUBLICACIÓN + P2 CICLO SIN LAUNCH)

**Fecha:** 2026-10-22
**Estado:** P1 PASS / P1.5 INTEGRADO (push pendiente de credencial) / P2 PASS / P3 NO INICIADO
**Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`
**Branch:** `main`
**HEAD del arnés verificado:** `3e15beb02fbed3dbcab8f52bd4d979201695166f`
**HEAD de AGENTE-GENERAL (origin/main):** `5f277b3574e36745884d2d0cfe745a45dc3b7b44`
**Commit de integración (local, verificado):** `9bb3870` = merge `--no-ff` de `feature/youtube-harness` (`b5b7220`) sobre `origin/main` (`5f277b3`); cero solapamiento de archivos, cero conflictos, historial preservado.

---

## 1. Estado anterior

Tras P0 (`MIGRATION_ANALYSIS.md`, INT-013) la migración estaba documentada pero sin ejecutar: el harness V1 existía en el motor (`/api/harness/v1`, 19 operaciones, permisos fail-closed) y la especialización consumidora del host existía solo como rama local `feature/youtube-harness` (`b5b7220`, 8 archivos, 1.047 líneas) no publicada en GitHub. No había ninguna conexión demostrada en vivo: los componentes eran hallazgos REPORTED, no VERIFIED.

## 2. Publicación de la especialización (P1.5)

- **Verificación previa:** `origin/main` = `5f277b3` (sin cambios respecto al informe P1); la rama remota `feature/youtube-harness` no existe; `b5b7220` añade exactamente 8 archivos (cliente, tool, 9 skills, políticas, instalador, docs, 15 tests) todos de la especialización; `origin/main` toca 15 archivos con cero solapamiento → merge limpio garantizado.
- **Integración:** merge `--no-ff` (sin squash destructivo) ejecutado en worktree aislado → commit `9bb3870`. Working tree limpio tras el merge. El working tree original del host (con 93 modificaciones locales pre-existentes del 2026-10-18) no fue tocado.
- **Validación post-integración:** `pytest tests/unit/test_youtube_specialization.py` sobre el main fusionado → 15 passed. Suite completa `tests/unit/` del host: 18 failed / 461 passed / 4 skipped en el main fusionado vs 18 failed / 446 passed / 4 skipped en main puro (`5f277b3`, worktree de control) — **los 18 fallos son idénticos y pre-existentes** (tests de proveedores dependientes de entorno sin claves); el merge añade 15 tests nuevos, todos en verde. No-regresión demostrada por comparación directa.
- **Bloqueo de publicación:** el push a GitHub falló con `Invalid username or token` — el PAT histórico está muerto para escritura (el `ls-remote` exitoso era lectura anónima: los repos son públicos). Clasificación: **BLOCKED BY AUTH**. La integración está lista; publicarla requiere un PAT nuevo con `contents:write` y es un solo comando (`git push` del merge `9bb3870` y de la rama `feature/youtube-harness`).

## 3. Commit resultante

`9bb3870` "merge: feature/youtube-harness → main — especialización consumidora del YouTube Harness (primer host, Harness Contract V1)" — padres `5f277b3` + `b5b7220`. Trazabilidad completa: la rama original queda preservada como ancestro y como ref publicable.

## 4. Pruebas ejecutadas (motor, `main` @ `3e15beb`)

| Batería | Resultado | Tiempo |
|---|---|---|
| `tests/test_harness.py` | 55 OK · 0 fallos | ~1 s |
| `tests/test_execution_contract.py` | 77 OK · 0 fallos | ~1 s |
| `tests/test_execution_transport.py` | 54 OK · 0 fallos | ~1 s |
| `tests/security/test_config_security.py` | 16 OK · 0 fallos | <1 s |
| `tests/security/test_csrf.py` | 10 OK · 0 fallos | <1 s |
| `tests/security/test_docs_auth.py` | 12 OK · 0 fallos | <1 s |
| Host: `pytest tests/unit/test_youtube_specialization.py` | 15 passed | ~2 s |
| Host: suite completa `tests/unit/` (no-regresión) | 461 passed · 18 failed pre-existentes idénticos a main puro · 4 skipped | ~12 s |

Comando motor: `python3 tests/<batería>.py` (scripts auto-ejecutables). Comando host: `python3 -m pytest tests/unit/test_youtube_specialization.py -q`.

## 5. Ciclo P2 (conexión fría → ciclo operativo)

Cadena demostrada con motor real (uvicorn, HTTP TCP real, DB aislada temporal, clave maestra efímera solo en memoria — sin mocks de transporte):

```text
intención/operación del host
    ↓
YoutubeHarnessClient (env YOUTUBE_HARNESS_URL / YOUTUBE_HARNESS_API_KEY, Bearer)
    ↓
YoutubeHarnessTool (youtube_harness_execute)
    ↓
skill.youtube.* (9 skills de coordinación)
    ↓
POST/GET /api/harness/v1/*
    ↓
HarnessRequest → authorize (permisos ⊇ requeridos, scopes de credencial)
    ↓
operación LOW read-only → HarnessResult → libro de ejecuciones (kv)
```

Secuencia ejecutada (45 checks, 0 fallos — driver del ciclo, no versionado en el repo): health autenticada; manifiesto (19 operaciones, 4 niveles de riesgo, destructivas `cleanup`+`delete`); `youtube.system_status` por las tres capas del host (skill → tool → cliente); `list_projects`/`list_niches`/`list_styles`/`list_avatars`; `production_doctor action=audit` (inspección sin fix); `validate_production` con el ejemplo canónico del propio motor (`production_json.spec([])["ejemplo"]`) → `valid: true, ACCEPTED, unidades:1` sin crear nada, y con payload roto → `BLOCKED` + código `VALIDATION` estructurado.

## 6. Permisos

Mecanismo real confirmado (VERIFIED): host usa `YOUTUBE_HARNESS_URL` + `YOUTUBE_HARNESS_API_KEY` → header `Authorization: Bearer` → `auth_guard` del motor acepta X-API-Key/Bearer/cookie/query contra `MASTER_API_KEY` (comparación en tiempo constante). El resultado declara `permissions`; el arnés verifica permiso requerido ⊆ declarado ⊆ scopes de credencial (`HARNESS_ALLOWED_PERMISSIONS` opcional). Denegaciones → estado `BLOCKED` dentro del contrato, nunca silencio.

## 7. Límites (pruebas negativas)

1. `launch` sin permisos → `BLOCKED/PERMISSION_MISSING`. 2. `launch` con solo `youtube.read` → `BLOCKED`. 3. Operación desconocida → 404 estructurado `OPERATION_UNKNOWN` + hint al manifiesto. 4. Credencial válida con scope insuficiente (`HARNESS_ALLOWED_PERMISSIONS=youtube.read` + `youtube.publish` declarado) → `BLOCKED/PERMISSION_NOT_GRANTED`. 5. Sin credencial → 401. Adicional: `delete` (destructiva) con solo read → `BLOCKED`.

## 8. Producción

**NO SE EJECUTÓ PRODUCCIÓN.** `projects=0`, `jobs=0`, `flow_jobs=0` antes=después (verificado por SQL directo sobre la DB aislada); cero ficheros de salida (sin vídeo/render); únicamente operaciones LOW (`system_status`, `list_projects`, `list_niches`, `list_styles`, `list_avatars`, `production_doctor audit`, `validate_production`). Sin `launch`, `submit_production`, `publish`, `create`, `cancel`, `recover`, `delete`, `cleanup`. Superficies protegidas intactas (0 diffs de contenido en ambos repos durante P1/P1.5/P2).

## 9. Idempotencia

El libro de ejecuciones es idempotente por `execution_id` (`harness.py`: replay con `metadata.replayed=True`). VERIFIED en vivo: mismo `execution_id` ×2 en `system_status` → 2ª respuesta es replay idéntico (status/outputs/errors) y recuperable vía `GET /executions/{id}`; id inexistente → 404. **Límite documentado:** la idempotencia de operaciones que crean recursos reales (`create`/`submit_production` no-idempotentes; `publish` idempotente pero HIGH+HITL) NO se probó para no violar la no-mutación de P2.

## 10. Matriz de capacidades (entrada de P3)

Leyenda de estado: VERIFIED = comprobado en vivo/código; MISSING = hueco real; DIVERGENT = parcialmente cubierto; N/A = no aplica a esta frontera.

| Skill interna (motor) | Operación harness | Skill host | Test | Estado |
|---|---|---|---|---|
| RUN_VIDEO_QA | `youtube.video_qa` | `skill.youtube.qa` | test_harness · test_youtube_specialization | VERIFIED |
| RUN_FLOW_PREFLIGHT | `youtube.flow_preflight` | `skill.youtube.doctor` (rama preflight) | test_harness | VERIFIED |
| QUEUE_PRODUCTION | `youtube.launch` + `youtube.submit_production` | `skill.youtube.launch` + `skill.youtube.submit_production` | test_harness · spec | VERIFIED (op; ejecución HIGH fuera de P2) |
| RECOVER_PRODUCTION | `youtube.recover` | `skill.youtube.recover` | test_harness · spec | VERIFIED (op) |
| PUBLISH_VIDEO | `youtube.publish` (HITL) | `skill.youtube.publish` (HITL) | test_harness · spec | VERIFIED (op; ejecución fuera de P2) |
| ANALYZE_PRODUCTION_FAILURE | `youtube.production_doctor` (audit/report) | `skill.youtube.doctor` | test_harness | DIVERGENT (análisis cubierto; sin op de análisis dedicada) |
| RETRY_FAILED_STEP | — | — | — | MISSING (sin op `retry`) |
| CREATE_SCRIPT | (interno del pipeline; expuesto vía `create`+`launch`) | `skill.youtube.create` | test_harness · spec | VERIFIED como coordinación |
| PREPARE_IMAGE_PROMPT / GENERATE_IMAGE / GENERATE_TTS / GENERATE_VIDEO / GENERATE_SUBTITLES / ASSEMBLE_VIDEO / ADD_MUSIC / RENDER_VIDEO / VALIDATE_ASSET | (pasos internos del orquestador/Flow — no exponibles sin violar la frontera del motor) | — | baterías de pipeline existentes | N/A (dominio del motor) |
| — (catálogo) | `youtube.list_projects` / `youtube.project_status` / `youtube.flow_status` | `skill.youtube.status` / `skill.youtube.flow_status` | test_harness · spec | VERIFIED |
| — (catálogo) | `youtube.list_niches` / `youtube.list_styles` / `youtube.list_avatars` / `youtube.system_status` | **sin skill host dedicada** | test_harness | MISSING (skills host para catálogos/salud) |
| — (contrato) | `youtube.validate_production` | **sin skill host** (solo tool crudo) | test_harness | MISSING (skill host `validate`) |
| — (mantenimiento) | `youtube.cleanup` / `youtube.cancel` / `youtube.delete` | **sin skill host** | test_harness | MISSING (gobernar antes de exponer: HIGH/destructivas) |

Gaps P3 confirmados (persisten los reportados en P0 y se precisa la lista): skills host para nichos/estilos/avatares/system_status; skill `validate`; op/skill `retry`; decisión sobre `cleanup_failed` (no existe como op — `cleanup` es liberación de disco); alineación de `ANALYZE_PRODUCTION_FAILURE` (hoy cubierta parcialmente por `production_doctor`).

## 11. Gobernanza (L0–L5 ↔ permisos ↔ riesgo ↔ HITL)

VERIFIED alineada, sin brecha bloqueante: 9/9 skills host tienen riesgo coherente con la operación del arnés que invocan (LOW↔LOW, MEDIUM↔MEDIUM, HIGH↔HIGH); las 4 skills de lectura (`status/qa/flow_status/doctor`) → reglas ALLOW con riesgo LOW; `publish` (HIGH, efecto externo) → única regla REQUIRE_HITL con `autonomy_required=L4_EXECUTE_SENSITIVE`; tool externo con rate-limit 60/min y dry-run disponible; el arnés aplica además su propia frontera (catálogo cerrado de permisos `youtube.*` + scopes de credencial + destructivas con `youtube.destroy`). La política del host es ADICIÓN (datos para el PolicyEngine del seed), no sustitución.

## 12. Riesgos encontrados

1. **Publicación pendiente (BLOCKED BY AUTH):** el merge `9bb3870` solo existe localmente hasta disponer de un PAT con `contents:write`. Mientras tanto, GitHub no refleja la especialización.
2. Fallos pre-existentes (18) en `tests/unit/` del host por dependencias de entorno (proveedores sin claves en el sandbox) — no introducidos por la integración; revisar fuera de esta misión.
3. Divergencia residual 3 superficies (17 skills internas / 19 operaciones / 9 skills host) — matriz en §10 como entrada de P3.
4. La conexión demostrada usa DB aislada; el arranque en producción real debe hacerse con `MASTER_API_KEY` definida (modo sin clave queda abierto por diseño).

## 13. Siguiente fase propuesta

**P3 — gaps v1.1 + tests cruzados** (no iniciada): cerrar los MISSING de §10 con el mínimo contrato nuevo, y añadir tests cruzados skills↔operaciones para evitar divergencia de las tres superficies. Antes: publicar `9bb3870` (requiere credencial). No corresponde aquí ejecutar P3.
