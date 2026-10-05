# Tests canónicos · fuente de verdad

Baterías autoejecutables del proyecto. Sin servidor, sin red, sin credenciales.
Viven DENTRO del repo: cada batería resuelve el backend relativo al propio
repositorio (`tests/../backend`), sin rutas absolutas.

## Qué cubre cada batería

| Batería | Área | Checks |
|---|---|---|
| `test_guion_json.py` | Contrato **legacy guion_json**: spec 2.11, `parse_payload` (fences), `validate` (alias EN, sanitización de image_prompt, límites duros), ingest sin LLM contra la SQLite real de desarrollo, rama del orquestador (por fuente) y dispatch MCP (16 tools). | 42 |
| `test_production_json.py` | **Adapter Production JSON 2.16.1**: spec, `parse_payload`, `validate` estructural (aliases, extras/continuity verbatim), `validate_execution` (nivel 2, unidades bloqueadas), `validate_only` (dry-run) e `ingest` con DB fake (sha256, tts_skip, preflight en meta). | 76 |
| `test_merge_216_pyav.py` | **Merge/integración 2.16.x + fix PyAV**: (A) MCP 2.16.1 auditado por AST sin imports pesados, (B) adapter real con DB fake, (C) fix PyAV por strings de fuente (requirements/tts_step/doctor/main), (D) compatibilidad cruzada Adapter↔pipeline↔MCP. | 51 |
| `test_lanzar_preflight.py` | **Preflight de lanzamiento**: flujo real `submit_production_json` → `lanzar_proyecto` vía `mcp_server._dispatch` (DB fake + `orchestrator._run` grabado). El draft con unidades sin `image_prompt` se acepta pero NO se lanza; no-regresión legacy (sin production.json), JSON corrupto/borrado. | 29 |

Total esperado: **198 checks**.

> Nota: `test_lanzar_preflight.py` verifica la barrera de preflight que vive en
> `pipeline/orchestrator.py` (`_preflight_lanzamiento`). Contra un estado sin
> ese cambio (p.ej. un clone anterior a su publicación), la sección E queda en
> rojo por diseño: la batería actúa de detector de la feature.

## Cómo ejecutarlas (clone limpio)

```bash
cd yt_automation_v2
python3 tests/run_all.py                  # las 4 baterías + total; exit != 0 si algo falla

# individual (python3 plano, estilo autoejecutable):
python3 tests/test_production_json.py

# opcional con pytest (cada batería = 1 test):
python3 -m pytest tests/ -q
```

Requisitos: `python3 >= 3.10` y las dependencias de `backend/requirements.txt`
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
- Ninguna batería deja carpetas de prueba en `backend/data/output/` ni toca
  nada fuera de `backend/data/`. No arrancan servidor ni hacen llamadas de red.

Notas de aislamiento: cada batería inyecta su propio módulo `database` fake en
`sys.modules` (excepto `test_guion_json.py`, que usa la real) y purga los
módulos de la app al empezar, por lo que también pueden correr las 4 en el
mismo proceso (caso pytest). `run_all.py` además las ejecuta en procesos
separados.
