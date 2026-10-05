# Tests canónicos · fuente de verdad

Baterías autoejecutables del proyecto. Sin credenciales y sin red externa
(la única excepción es `test_live_boot.py`, que levanta uvicorn en
127.0.0.1 en un sandbox aislado). Viven DENTRO del repo: cada batería
resuelve el backend relativo al propio repositorio (`tests/../backend`),
sin rutas absolutas.

## Qué cubre cada batería

| Batería | Área | Checks |
|---|---|---|
| `test_guion_json.py` | Contrato **legacy guion_json**: spec 2.11, `parse_payload` (fences), `validate` (alias EN, sanitización de image_prompt, límites duros), ingest sin LLM contra la SQLite real de desarrollo, rama del orquestador (por fuente) y dispatch MCP (20 tools). | 42 |
| `test_production_json.py` | **Adapter Production JSON 2.16.1**: spec, `parse_payload`, `validate` estructural (aliases, extras/continuity verbatim), `validate_execution` (nivel 2, unidades bloqueadas), `validate_only` (dry-run) e `ingest` con DB fake (sha256, tts_skip, preflight en meta). | 76 |
| `test_merge_216_pyav.py` | **Merge/integración 2.16.x + fix PyAV**: (A) MCP 2.16.1 auditado por AST sin imports pesados, (B) adapter real con DB fake, (C) fix PyAV por strings de fuente (requirements/tts_step/doctor/main), (D) compatibilidad cruzada Adapter↔pipeline↔MCP. | 51 |
| `test_lanzar_preflight.py` | **Preflight de lanzamiento**: flujo real `submit_production_json` → `lanzar_proyecto` vía `mcp_server._dispatch` (DB fake + `orchestrator._run` grabado). El draft con unidades sin `image_prompt` se acepta pero NO se lanza; no-regresión legacy (sin production.json), JSON corrupto/borrado. | 29 |
| `test_flow_contract_p1.py` | **GOLDEN EXECUTION CONTRACT P1**: el `video_prompt` del Creative Engine llega **verbatim** al payload de Flow (transformación/genérico y artesano), gana sobre `ai_stages` y plantillas, `duration_target` al export, campos del contrato preservados, sanitización no muta. | 44 |
| `test_flow_bridge.py` | **Flow Bridge v1**: motor de cola (`services/flow_jobs.py`) claim atómico/lease/heartbeat/complete/fail, 6 endpoints vía httpx ASGI, validación PIL/ffprobe, mapeo de escenas + auto-render (mock), re-enqueue idempotente. | 48 |
| `test_golden_fixture.py` | **Fixture Golden oficial**: cadena completa con DB REAL — fixture → ingest → roundtrip meta JSON → script.json (P1 verbatim) → cola → claim → complete → Video QA. | 30 |
| `test_concurrencia.py` | **Concurrencia**: raza de 8 workers sobre BEGIN IMMEDIATE (0 dobles claims), aislamiento multi-proyecto, token de una sola era (409 tras re-claim), completes paralelos, enqueue en caliente. | 18 |
| `test_chaos.py` | **Chaos**: reinicio REAL de proceso (subprocess), rollback atómico, doble complete 409, HTML de Flow → 422 → dead, dead → re-enqueue, estados imposibles, carrera zombie. | 28 |
| `test_bridge_e2e.py` | **E2E extensión**: `node --check` en los JS + `bridge.js` REAL en sandbox VM contra backend mock HTTP con estado (claim→complete con bytes validados, 422, heartbeat, backend caído, anti-duplicado). | 24 |
| `test_humos_infra.py` | **Humos anti-fantasma**: todo lo que declaramos existe físicamente en el repo (tabla, endpoints, bridge.js, wiring, CORS, P1, auto-render, runner, ESTADO_REAL). | 51 |
| `test_live_boot.py` | **Boot vivo**: arranca uvicorn REAL en sandbox aislado (`live_boot_smoke.sh`: startup, CORS preflight, endpoints base, métricas, video QA) + **ciclo completo del Flow Bridge por HTTP** (`live_cycle_smoke.sh`: enqueue → claim → complete PNG/MP4 reales → 409/422 → fail/retry → guard de tipo → project_done → auto-render → QA). | 33 |

Total esperado: **474 checks**.

> Nota: `test_lanzar_preflight.py` verifica la barrera de preflight que vive en
> `pipeline/orchestrator.py` (`_preflight_lanzamiento`). Contra un estado sin
> ese cambio (p.ej. un clone anterior a su publicación), la sección E queda en
> rojo por diseño: la batería actúa de detector de la feature.

## Cómo ejecutarlas (clone limpio)

```bash
cd yt_automation_v2
python3 tests/run_all.py                  # las 12 baterías + total; exit != 0 si algo falla

# individual (python3 plano, estilo autoejecutable):
python3 tests/test_production_json.py
bash tests/live_boot_smoke.sh             # boot vivo aislado (opcional, sin pytest)

# opcional con pytest (cada batería = 1 test; live_boot requiere bash+ffmpeg):
python3 -m pytest tests/ -q --ignore=tests/test_live_boot.py
```

Requisitos: `python3 >= 3.10`, `bash`, `curl`, `ffmpeg/ffprobe` (solo para
`test_live_boot.py`) y las dependencias de `backend/requirements.txt`
instaladas (mínimo `fastapi`/`starlette`; las baterías NO importan `av` ni
`faster_whisper` aunque no estén instalados). La primera corrida en un clone
limpio crea el runtime mínimo (`backend/data/`, SQLite, `output/`) al importar
`config`/`database`; todo ello está en `.gitignore`.

## Qué escriben y limpian en disco

- `test_production_json.py`, `test_merge_216_pyav.py`, `test_lanzar_preflight.py`:
  escriben `backend/data/output/<pid>/production.json` (carpeta de proyecto de
  prueba) y la **eliminan al final** de la corrida.
- `test_guion_json.py`: usa la SQLite real de desarrollo
  (`backend/data/yt_automation.db`), crea proyectos de prueba y los **borra al
  final** (`delete_project`).
- `test_live_boot.py`: copia `backend/` a un sandbox temporal (fuera del repo,
  se borra al terminar), usa su PROPIA SQLite vacía y puertos locales
  (127.0.0.1:8765/8766). No toca la DB ni los outputs del desarrollador.
- Ninguna batería deja carpetas de prueba en `backend/data/output/` ni toca
  nada fuera de `backend/data/` y su sandbox temporal.

Notas de aislamiento: cada batería inyecta su propio módulo `database` fake en
`sys.modules` (excepto `test_guion_json.py`, que usa la real) y purga los
módulos de la app al empezar, por lo que también pueden correr en el
mismo proceso (caso pytest). `run_all.py` además las ejecuta en procesos
separados. `test_live_boot.py` corre subprocess `bash` y se excluye del modo
pytest por defecto.
