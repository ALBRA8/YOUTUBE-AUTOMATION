# PRODUCTION DOCTOR V1.0

Capa transversal de **diagnóstico y reparación determinista** para el pipeline
completo de la fábrica:

```
Production JSON → Adapter → Flow Export → Flow Jobs → Extensión →
Google Flow → Asset → Complete → QA → Render
```

El Doctor responde, con evidencia medida (nunca suposiciones): **dónde** ocurrió
el fallo, **cuál es la causa probable**, **qué componente** está afectado, si es
un problema de datos/contrato/ejecución/infraestructura/entorno/servicio
externo, si **puede repararse automáticamente** y si **requiere intervención
humana**.

## Regla fundamental

`DIAGNOSTICAR → EXPLICAR → REPARAR → VALIDAR`. Nunca `ERROR → CAMBIO ARBITRARIO`.

Trabaja SOBRE el código, contratos, tests, logs, estado de jobs, Production
JSON y resultados de QA existentes. No crea backend, worker, API, cola ni
infraestructura de tests paralela.

## Modos

| Modo | Qué hace | CLI | API | MCP |
|------|----------|-----|-----|-----|
| **DOCTOR AUDIT** | Diagnóstico completo de las 9 capas SIN modificar nada | `python3 -m services.production_doctor audit` | `POST /api/production_doctor/audit` | tool `production_doctor {modo:"audit"}` |
| **DOCTOR FIX** | Diagnostica y aplica SOLO reparaciones seguras (lista blanca) + re-audit + tests afectados | `... fix [--no-tests]` | `POST /api/production_doctor/fix` | `{modo:"fix"}` |
| **DOCTOR VERIFY** | Re-ejecuta los checks y las baterías de los componentes afectados; reporta qué cambió | `... verify` | `POST /api/production_doctor/verify` | `{modo:"verify"}` |
| **DOCTOR REPORT** | Informe legible del último estado (o audit fresco) | `... report` | `GET /api/production_doctor/report` | `{modo:"report"}` |
| **REAL FLOW PREFLIGHT** | Barrera antes de una prueba real con Google Flow | `... preflight [--project-id PID]` | `GET /api/production_doctor/preflight?project_id=` | tool `real_flow_preflight` |

Opciones comunes: `--deep` (QA forense pesado con ffprobe por asset),
`--json` (salida completa). Exit codes CLI: `0` limpio/PASS, `1` findings
graves o REAL FLOW BLOCKED, `2` uso incorrecto.

## Capas diagnosticadas (A-I)

| Capa | Nombre | Qué mide | Hallazgos típicos |
|------|--------|----------|-------------------|
| A | INPUT | `production.json` por proyecto | JSON corrupto (`DATA_ERROR`), unidades sin `image_prompt` (`DATA_ERROR`), paridad sequence↔BD (`CONTRACT_VIOLATION`) |
| B | ADAPTER | original vs modelo normalizado | pérdida de `video_prompt`/`duration`/`references`/`continuity` (`CONTRACT_VIOLATION`) |
| C | FLOW_EXPORT | export reconstruido vs creativo | motion ≠ video_prompt verbatim (P1), duración alterada, motion vacío (`CONTRACT_VIOLATION`) |
| D | FLOW_JOBS | estados reales de la cola | lease vencido, claimed sin lease/token, agotado en queued, duplicados, huérfanos, done sin asset, cola incompleta, zombies |
| E | EXTENSION | manifest/host_permissions/archivos/bridge + HTTP | `CONFIG_ERROR` crítica si faltan permisos localhost/127.0.0.1; bridge desalineado (`CONTRACT_VIOLATION`) |
| F | GOOGLE_FLOW | solo evidencia indirecta | dead jobs, generación en curso → `EXTERNAL_SERVICE_ERROR` (nunca causa inventada) |
| G | ASSETS | archivos vs mapping derivado | `image_path` roto (reparable si existe candidato en `flow/`), assets huérfanos |
| H | QA | informe forense de `video_qa` | pantalla negra/azul, audio silencioso (`DATA_ERROR`; modo `--deep`) |
| I | RENDER | ffmpeg/ffprobe/disco/música | `ENVIRONMENT_ERROR` crítico sin ffmpeg/escritura; sin pistas mp3 (`CONFIG_ERROR` warn) |

## Clasificación de errores (regla 5)

Toda incidencia es un **Finding** con: `id, capa, componente, titulo,
clasificacion, severidad, evidencia, causa_probable,
reparacion_disponible, reparacion_accion, validacion_requerida`.

Clasificaciones: `BUG_CONFIRMED` · `CONTRACT_VIOLATION` · `DATA_ERROR` ·
`CONFIG_ERROR` · `ENVIRONMENT_ERROR` · `EXTERNAL_SERVICE_ERROR` ·
`TEST_FAILURE` · `UNKNOWN`.

Si el Doctor no puede determinar la causa → `UNKNOWN` con
**HUMAN INVESTIGATION REQUIRED** (p. ej. job `running` sospechoso visto desde
fuera del proceso del servidor: el Doctor no adivina). Si el problema es de
Google Flow → `EXTERNAL_SERVICE_ERROR`. El Doctor nunca convierte un error
real en un PASS falso ni edita código/tests para "que pase".

## Reparaciones automáticas (lista blanca cerrada, regla 6)

Solo transformaciones **deterministas y de bajo riesgo**, cada una respaldada
por una regla contractual ya existente:

| Reparación | Regla que la respalda |
|------------|----------------------|
| `recover_expired_leases` | `flow_jobs.recover_expired()` (existente) |
| `requeue_invalid_claimed` | `claim_next` siempre pone lease+token |
| `deaden_exhausted_queued` | `fail()` manda a dead al agotar |
| `dedupe_flow_jobs` | `enqueue_project` idempotente (1 job por clave) |
| `delete_orphan_jobs` | integridad referencial con `projects` |
| `rebuild_asset_mapping` | `flow_jobs._apply_assets_to_scenes` (existente) |
| `rebuild_job_queue` | `enqueue_project` idempotente (conserva done) |
| `ensure_directories` | rutas canónicas de `config.py` |
| `cleanup_tmp` | temporales conocidos `*.tmp`/`*.part` >1h |
| `fail_zombie_pipeline_jobs` | criterio `orchestrator._zombie_job` (solo in-process) |

**PROHIBIDO y fuera de la lista para siempre**: tocar `production.json`,
prompts creativos, `video_prompt`, `duration_target`, continuidad, referencias,
Niche Blueprints, el comportamiento de Google Flow o los contratos. La batería
de tests verifica con SHA-256 que lo creativo queda byte-a-byte intacto tras
un `fix`.

## REAL FLOW PREFLIGHT (regla 8)

Comprueba (bloqueante, determinístico): herramientas (ffmpeg/ffprobe/PIL) ·
directorios canónicos escribibles · **backend disponible** (`/api/health`) ·
**bridge** (`BRIDGE_API_BASE` real apuntando a `/api/extension/flow/jobs` y las
4 rutas) · por proyecto: existe, tiene escenas, sin pipeline activo que
interfiera, `production.json` parseable, `image_prompt` en todas las unidades,
**`video_prompt` en TODAS las unidades que generan clip** (criterio
contractual explícito: si el proyecto genera clips — 2+ unidades —, NINGUNA
unidad que deba generar video puede carecer de `video_prompt`; NO basta con
que exista al menos uno. La única exenta es la última unidad, SOLO-imagen por
diseño del export `build_script_json` — escena i = Imagen i + Video i; la
última es solo imagen —; con 0 unidades de video el criterio no aplica),
payload Flow reconstruible en seco, cola limpia (sin dead/lease vencido/claim
inválido/agotados), jobs creados.

### EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME CONNECTED

Dos conceptos separados, reportados por separado en el informe
(`extension_structural`, `extension_runtime`, `extension_runtime_evidence`):

- **STRUCTURAL READY** — checks `P-EXT-MANIFEST`, `P-EXT-HOST-PERMISSIONS`,
  `P-EXT-ARCHIVOS`, `P-BRIDGE`: la extensión está completa y alineada EN
  DISCO (manifest MV3, permisos, archivos, rutas del bridge). Es
  verificable determinísticamente → PASS/FAIL normal, y agrupa en
  `extension_structural: READY | NOT_READY`.
- **RUNTIME CONNECTED** — check `P-EXT-RUNTIME`: que Chrome con la extensión
  esté AHORA conectado al backend. El backend NO puede observar Chrome: la
  única evidencia válida es un job `claimed` con `worker` y lease VIGENTE
  (el lease se renueva por heartbeat y expira con worker muerto — mecanismo
  de liveness del propio contrato). Con evidencia → `estado: PASS` y
  `extension_runtime: CONNECTED` citando worker/job/lease. Sin evidencia →
  `estado: NOT_DEMONSTRATED` (≈ UNKNOWN), `ok: false`, `bloqueante: false`:
  **nunca se reporta como PASS ni se inventa conexión**. Un lease vencido no
  es evidencia (worker muerto); el operador confirma Chrome+extensión
  activos antes de gastar la prueba. Solo los checks bloqueantes fijan el
  veredicto: un no-demostrado se reporta pero no lo falsifica.

Si falla un requisito determinístico **NO ejecutar Google Flow**. El veredicto
es exactamente:

- `REAL FLOW PREFLIGHT PASS`
- `REAL FLOW BLOCKED` + lista exacta de motivos

El preflight **nunca ejecuta Flow ni repara nada** (reparar = DOCTOR FIX).

## Audit trail (regla 10)

Toda reparación queda en `backend/data/doctor/audit_trail.jsonl` (append-only)
con: `timestamp, finding_id, diagnostico, archivo_afectado, funcion_afectada,
cambio, motivo, test_ejecutado, resultado_antes, resultado_despues, modo`.
El último informe completo vive en `backend/data/doctor/last_report.json`.

## Integración con tests (regla 7)

- `TESTS_POR_COMPONENTE` mapea componente → baterías canónicas del repo
  (`tests/run_all.py`); DOCTOR FIX/VERIFY las re-ejecuta en su propio proceso,
  igual que `run_all.py`. No hay segunda infraestructura de tests.
- Ciclo completo: `AUDIT → TESTS → DIAGNÓSTICO → FIX → TESTS nuevamente`,
  reportando exactamente qué cambió.
- Baterías propias del Doctor (también en `run_all.py`):
  `tests/test_production_doctor.py` (54 checks) y
  `tests/test_doctor_preflight.py` (38 checks).

## Ubicación del código

```
backend/services/production_doctor/
  __init__.py    API pública: audit/fix/verify/report/preflight/run_mode
  core.py        taxonomía (Clasificacion), Finding, DoctorReport, AuditTrail
  layers.py      capas A-I (solo lectura, evidencia medida)
  repairs.py     SAFE_REPAIRS: lista blanca cerrada de reparaciones
  preflight.py   REAL FLOW PREFLIGHT
  __main__.py    CLI
```

Nota de diseño: la función pública `production_doctor.preflight()` y el
submódulo `production_doctor/preflight.py` comparten nombre; el submódulo se
accede vía `sys.modules["services.production_doctor.preflight"]` (así lo hace
su batería de tests).
