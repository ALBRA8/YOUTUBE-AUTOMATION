# INT-093 · Sonda de capacidades MCP — nombres de proyecto/character/cuaderno

**Fecha:** 2026-11-07 (creación de la sonda y de esta nota)
**Estado:** NOT_DEMONSTRATED — ninguna pregunta está respondida con
evidencia real todavía: la sonda no puede alcanzar ninguno de los dos MCP
desde el sandbox del constructor (requiere la máquina del dueño con
`notebooklm-mcp` instalado y Chrome/node para GoogleFlowMCP).

## Qué es

`tools/sonda_capacidades_nombres.py` — sonda **SOLO LECTURA** que se
conecta a los dos MCP del repo por la vía única (`services.mcp_manager`,
transporte stdio JSON-RPC), lista las herramientas con su `inputSchema`
(`tools_catalog`, método público nuevo de `mcp_manager`) y responde con
evidencia 7 preguntas de la convención de nombres y destino:

| id | pregunta | veredicto |
|---|---|---|
| q1_flow_proyecto_nombre | ¿flow_new_project acepta nombre o hay herramienta para renombrar proyecto? | **NOT_DEMONSTRATED** |
| q2_flow_personaje_nombre | ¿se puede crear un personaje con nombre? | **NOT_DEMONSTRATED** |
| q3_notebook_create_titulo | ¿notebook_create acepta título? | **NOT_DEMONSTRATED** |
| q4_notebook_renombrar | ¿existe herramienta para renombrar cuaderno? | **NOT_DEMONSTRATED** |
| q5_source_add_titulo | ¿source_add acepta título? | **NOT_DEMONSTRATED** |
| q6_flow_generacion_destino (Q2) | ¿flow_generate_image / flow_generate_video / flow_upload_file aceptan un identificador de proyecto o destino? | **NOT_DEMONSTRATED** |
| q7_flow_new_project_cambia_activo (Q2) | ¿flow_new_project cambia el proyecto ACTIVO sobre el que generan las demás herramientas? | **NOT_DEMONSTRATED** |

Veredictos posibles: `SOPORTADO` (evidencia en el esquema) /
`NO_SOPORTADO` (hay catálogo real y NO está) / `NOT_DEMONSTRATED`
(sin catálogo real — sin máquina del dueño).

Reglas de veredicto de las preguntas Q2 (documentadas en el propio
código, `analizar_tools`):

- **q6**: SOPORTADO solo si TODAS las herramientas de generación
  presentes (flow_generate_image / flow_generate_video /
  flow_upload_file) exponen en su esquema una propiedad de
  proyecto/destino (project_id, destino, folder, workspace…); si una
  sola no la expone → NO_SOPORTADO con el detalle de cuál; sin
  herramientas de generación en el catálogo → NOT_DEMONSTRATED.
- **q7**: es CONDUCTA, no esquema: solo hay veredicto con evidencia
  explícita en la DESCRIPCIÓN de flow_new_project (declara que cambia
  el proyecto activo → SOPORTADO; declara que NO lo cambia →
  NO_SOPORTADO); descripción muda → NOT_DEMONSTRATED. Mientras q7 no
  sea SOPORTADO, Q3 NO dirige la generación al proyecto creado: el id
  se registra y la limitación queda escrita.

## Versiones de los MCP

| servicio | versión declarada | cómo se verificó |
|---|---|---|
| google-flow (`srz-google-flow-mcp`) | 1.0.1 en `tools/GoogleFlowMCP/package.json` del repo | lectura del repo; **la versión EN EJECUCIÓN se confirma con `server_info` del handshake — por confirmar en la máquina del dueño** |
| notebooklm (`notebooklm-mcp-server`) | **v0.1.15 real** (comandos `notebooklm-mcp` y `notebooklm-mcp-auth`; `uv tool list` en la máquina del dueño) | dato del dueño (U6, 2026-11-07) + PyPI JSON `pypi.org/pypi/notebooklm-mcp-server/json` (última = 0.1.15). **OJO: la versión que llega en `server_info` (p. ej. 2.14.5) es la del FRAMEWORK FastMCP, no la del paquete — no usarla como versión del paquete.** El pin histórico `notebooklm-py[browser]==0.8.5` de INT-069 se refería al upstream ANTERIOR: el servidor realmente instalado es otro paquete |

## Cómo cerrar los veredictos (máquina del dueño)

```bash
python tools/sonda_capacidades_nombres.py --salida sonda_nombres.json
```

- Actualizar la tabla de arriba con los veredictos reales, la fecha y el
  `server_info` (versión) de cada MCP.
- La sonda NUNCA crea nada. Creaciones de prueba solo con
  `--crear-prueba --confirmo "SI CREAR"` (el dueño decide explícitamente).

## Por qué importa (decisión del dueño ya tomada)

Los nombres que Flow/NotebookLM acepten determinan la convención
`FRUTINOVELAS · S003 · Título` (registro local en
`data/output/<pid>/registro.json`, un cuaderno por nicho, un proyecto de
Flow por historia). Si la sonda demuestra `NO_SOPORTADO` para pasar el
nombre a Flow, el nombre vive SOLO en el registro local y la limitación
queda anotada — jamás se simula que Flow lo recibió.

## Nota de hermeticidad

Los tests `tests/test_sonda_capacidades.py` (15) son herméticos y usan
DOBLES de catálogo: ningún test arranca Flow, NotebookLM, Chrome ni
subprocess de MCP. El análisis de esquemas es una función pura.

## ACTUALIZACIÓN U6 (2026-11-07) · paquete real y catálogo de notebooklm-mcp-server v0.1.15

Dato del dueño (y confirmado en PyPI): el MCP de NotebookLM instalado en
su máquina es **`notebooklm-mcp-server` v0.1.15**, con comandos
**`notebooklm-mcp`** y **`notebooklm-mcp-auth`** (`uv tool list` lo
confirma). La instalación correcta es
`uv tool install notebooklm-mcp-server` (NO «uv tool install
notebooklm-py[browser]», texto antiguo del panel ya corregido).

Catálogo REAL de la v0.1.15 según la documentación del paquete (PyPI,
31 tools declaradas; tabla pública con 27 nombres):

`notebook_list, notebook_create, notebook_get, notebook_describe,
source_describe, source_get_content, notebook_rename, chat_configure,
notebook_delete, notebook_add_url, notebook_add_text,
notebook_add_drive, notebook_query, source_list_drive,
source_sync_drive, source_delete, research_start, research_status,
research_import, audio_overview_create, video_overview_create,
infographic_create, slide_deck_create, studio_status, studio_delete,
refresh_auth, save_auth_tokens`

### Cotejo: herramientas que NUESTRO código llama vs el catálogo real

| nombre llamado | dónde | ¿está en v0.1.15? | efecto |
|---|---|---|---|
| `notebook_list` | mcp_manager (probe + listado) | ✅ | OK |
| `notebook_create` | mcp_manager (`_NO_NOTEBOOK_TOOLS`), nlm_studio | ✅ | OK |
| `studio_status` | nlm_studio | ✅ | OK |
| `list_notebooks` | mcp_manager (alias de reserva en `_LIST_NOTEBOOK_TOOLS`) | ❌ | inofensivo: solo se intenta si `notebook_list` no existe |
| `chat_ask` | pipeline_orchestrator (DEFAULT de `NOTEBOOKLM_CONTEXT_TOOL`) | ❌ | **REAL: en v0.1.15 la tool de contexto es `notebook_query`** — sin `NOTEBOOKLM_CONTEXT_TOOL=notebook_query` el paso [1/3] fallará con TOOL_UNKNOWN en la máquina del dueño |
| `source_add` | nlm_studio | ❌ | legado del upstream viejo (notebooklm-py 0.8.5); en v0.1.15 son `notebook_add_url/_text/_drive` |
| `studio_generate` | nlm_studio | ❌ | ídem; en v0.1.15 son `audio/video_overview_create`, `infographic_create`, `slide_deck_create` |
| `studio_download` | nlm_studio | ❌ | ídem (no existe en el catálogo) |

El cotejo está fijado como trinquete en
`tests/test_u6_catalogo_contrato.py` (usa este nombre y versión reales):
si el código empieza a llamar otra tool ausente del catálogo, el test
falla y obliga a documentarla aquí. La recomendación de migración de
`chat_ask → notebook_query` y de las tools de nlm_studio queda como
decisión del dueño (SIGUIENTE), no se cambia comportamiento en U6.
