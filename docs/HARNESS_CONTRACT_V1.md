# YOUTUBE HARNESS CONTRACT V1 — Arnés especializado audiovisual

**Repo:** ALBRA8/YOUTUBE-AUTOMATION · **Base:** `fa24a2a` (FASE 1 completada) · **Rama:** `harness-v1`
**Mandato:** TRANSFORMACIÓN FINAL — YOUTUBE-AUTOMATION → ARNÉS, AGENTE-GENERAL como primer host.

---

## 1. Principio arquitectónico

> El conocimiento operativo pertenece al puesto/empresa/arnés, no al trabajador que actualmente ocupa el puesto.

```text
                 AGENTE HOST (AGENTE-GENERAL, Hermes, OpenClaw, …)
                     │
                     ▼
              HOST CONTRACT (skill.youtube.* en el host)
                     │
                     ▼
             YOUTUBE HARNESS  ← este documento  (/api/harness/v1)
                     │
       ┌─────────────┼─────────────┐
   knowledge     capabilities    permissions
       └─────────────┼─────────────┘
                     ▼
              EXISTING ENGINE (SIN reescritura)
       pipeline · Flow (jobs/extensión/bridge) · HANDS
```

- El arnés es una **fachada de dominio** (`backend/services/youtube_harness/`): NO mueve los servicios existentes, NO reescribe el motor, NO crea colas ni backends paralelos.
- **Agnóstico del host (§15):** cero imports de `albra_seed`, `agente-general` o cualquier host. Verificación mecánica: `rg -l "albra_seed|agente.general|agente-general" backend/` → vacío.

## 2. Paquete

```text
backend/services/youtube_harness/
    __init__.py      # exports públicos; agnosticidad declarada
    contracts.py     # HarnessRequest / HarnessResult / estados externos (§7-§9)
    capabilities.py  # registro youtube.* (19 operaciones) + riesgo (§13)
    permissions.py   # catálogo de permisos; destructivas con permiso propio
    knowledge.py     # conocimiento estructurado del PUESTO (§10-§12)
    adapter.py       # fachada fina sobre la fábrica existente
    harness.py       # ejecutor + libro de ejecuciones idempotente (kv)
    legacy.py        # puente declarativo cerebro-chat → arnés (VÓRTICE
                     #   retirado en INT-028; hoy services/general_agent.py)
    api.py           # router HTTP /api/harness/v1 (§16-§18)
```

Wiring en `main.py` (2 líneas, junto a los mounts): `app.include_router(harness_api.router)` — hereda `auth_guard`, `csrf_guard` y techo de `Content-Length` por ser middlewares de app. **Sin bypass: cero rutas públicas nuevas.**

## 3. CLASIFICACIÓN OBLIGATORIA (§3)

| Componente | Clase | Nota |
|---|---|---|
| `backend/services/youtube_harness/` (nuevo) | SHARED_CONTRACT | idioma neutro host↔arnés |
| Creative Engine, guion_json, production_json, niches, themes, avatares | KEEP_YOUTUBE | cerebro/dominio intactos |
| orchestrator, pipeline (images/video/tts/subtitles), QA, youtube_publish, scheduler | KEEP_YOUTUBE · DO_NOT_TOUCH estructural | consumidos por el adaptador |
| flow_jobs, execution_contract, flow_adaptation, extensión, bridge, leases/watchdog | KEEP_YOUTUBE · DO_NOT_TOUCH estructural | ídem |
| HANDS V1.0 completo | KEEP_YOUTUBE · DO_NOT_TOUCH | no se mueve ni se reimplementa; el host no conoce sus internos |
| `backend/database.py` | KEEP_YOUTUBE | reutilizado (kv = libro de ejecuciones) |
| `backend/services/general_agent.py` (Agente General, ex-VÓRTICE) | **UNIFICADO (INT-028)** | agent.py RETIRADO y absorbido íntegro; API pública idéntica (plan/execute/M9); comportamiento de `/api/chat` = DO_NOT_TOUCH (tests M9) |
| `/api/chat` + dashboard | DO_NOT_TOUCH | contrato needs_confirm/pending intacto |
| `/api/agent/execute` (A2A) | KEEP_YOUTUBE | puerta previa del Creative Engine; el arnés la complementa, no la reemplaza |
| `/api/harness/v1` (nuevo) | SHARED_CONTRACT | única superficie nueva |
| MCP `/mcp` | KEEP_YOUTUBE | sin cambios |
| skills `skill.youtube.*` en AGENTE-GENERAL | ADAPT_GENERAL | capa de coordinación del host (otro repo) |

## 4. Contrato (§7-§9)

- `POST /api/harness/v1/execute` recibe `HarnessRequest` (contract_version fijo `"1.0"`; `execution_id` lo genera el host, 4-128 chars `[A-Za-z0-9._:-]`; `requester`; `capability == "youtube_automation"`; `operation`; `input/constraints/permissions/resources/deadline/correlation_id/parent_execution_id/metadata` opcionales). Validación ESTRICTA: operación desconocida → **404 estructurado** (nunca silencio); metadata con claves sensibles → 400; permisos desconocidos → BLOCKED.
- Devuelve `HarnessResult` abstracto (nunca filas SQLite): `status/outputs/artifacts/evidence/metrics/warnings/errors/recovery/metadata`.
- **Estados externos:** ACCEPTED QUEUED RUNNING WAITING VERIFYING READY PUBLISHED FAILED RECOVERABLE BLOCKED CANCELLED. Mapeo §9 exacto + `importing/processing→RUNNING`, `publishing→VERIFYING`; `FAILED + evidencia de recuperación → RECOVERABLE`. Los estados internos NO cambian (sin estados inventados).
- **Libro de ejecuciones:** `execution_id` idempotente (replay con `metadata.replayed=true`), persistido en el kv store existente (`harness_exec:*`).

## 5. Operaciones y riesgo (§13)

19 operaciones `youtube.*`: 11 de lectura (LOW), `create/submit_production/cancel/recover` (MEDIUM), `launch/publish` (HIGH, efecto de cola/externo), `delete/cleanup` (**destructivas** → `youtube.destroy`, CRITICAL/HIGH). Publicar exige QA gate + idempotencia (409) — espejo exacto de la ruta existente. Lanzar con `constraints.autopublish=true` requiere además cadenas de publicación configuradas (la política interna no cambia).

## 6. Seguridad (§18)

1. **Transporte:** autenticación maestra existente (X-API-Key/Bearer/cookie/query) + CSRF existente + 413 global. Batería: sin clave → 401 en manifest/execute/health; Origin externo + POST → 403.
2. **Permisos:** el host DECLARA permisos; el arnés exige `required_permission ⊆ declarados` (admin expande). Sin servicio de credenciales en la fábrica, se reutiliza la clave autenticada existente (sin hardcodear secretos); scopes por credencial vía env opcional `HARNESS_ALLOWED_PERMISSIONS` (fail-closed → BLOCKED `PERMISSION_NOT_GRANTED`).
3. **Destructivas:** permiso propio `youtube.destroy`; regla M9 (cero fuzzy, id exacto 12-hex) replicada en `adapter.op_delete`.

## 7. Conocimiento (§10-§12)

`knowledge.py` estructura lifecycle, objetos de dominio, semántica de producción (crear/lanzar/verificar/recuperar/QA/publicar), semántica de seguridad (reglas M9, confirmación host-side, idempotencia de publicación) y taxonomía de errores (VALIDATION/PROVIDER_FAILURE/ASSET_INVALID/WATCHDOG/…). NO es copia de SYSTEM_BRAIN: la identidad de VÓRTICE no migra; los catálogos vivos se consultan por operaciones. Prueba conceptual (§12): `VÓRTICE eliminado + host nuevo + arnés = misma capacidad operacional` — **EJECUTADA en INT-028**: `services/general_agent.py` absorbió a VÓRTICE (mismo contrato de /api/chat, tests M9 verdes) y `legacy.equivalence_report()` documenta el puente (5 acciones cubiertas, el resto es interfaz del trabajador o administración de catálogo fuera del contrato v1).

## 8. Batería y verificación

`tests/test_harness.py` (registrada en `run_all.py`): 55 checks runtime HTTP (ASGI) — manifiesto sin secretos, validación estricta, permisos/scopes, ciclo create→status→replay, validate/submit Production JSON, recursos inexistentes, normalización §9, puente legacy, auth/CSRF heredados sin bypass, health. Regresión completa del repo ejecutada por lotes: 43 baterías · 2040 checks OK · 0 fallos.

## 9. Límites honestos

- El libro de ejecuciones guarda el snapshot del resultado; el seguimiento en vivo de un lanzamiento se hace con `youtube.project_status` (o SSE interna del job) — el arnés no duplica el broker.
- `create` no lanza: crear y lanzar son operaciones separadas (coordinación explícita del host; el chat las encadena).
- `submit_production` con `constraints.launch=true` exige permiso `youtube.production.create` (el launch implícito hereda la política de preflight/CONFIG_* del motor).
- El contrato v1 no expone gestión de plantillas de nicho (crear/borrar) ni publicación programada compleja: administración del puesto, fuera de alcance mínimo.
