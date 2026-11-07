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
evidencia 5 preguntas de la convención de nombres:

| id | pregunta | veredicto |
|---|---|---|
| q1_flow_proyecto_nombre | ¿flow_new_project acepta nombre o hay herramienta para renombrar proyecto? | **NOT_DEMONSTRATED** |
| q2_flow_personaje_nombre | ¿se puede crear un personaje con nombre? | **NOT_DEMONSTRATED** |
| q3_notebook_create_titulo | ¿notebook_create acepta título? | **NOT_DEMONSTRATED** |
| q4_notebook_renombrar | ¿existe herramienta para renombrar cuaderno? | **NOT_DEMONSTRATED** |
| q5_source_add_titulo | ¿source_add acepta título? | **NOT_DEMONSTRATED** |

Veredictos posibles: `SOPORTADO` (evidencia en el esquema) /
`NO_SOPORTADO` (hay catálogo real y NO está) / `NOT_DEMONSTRATED`
(sin catálogo real — sin máquina del dueño).

## Versiones de los MCP

| servicio | versión declarada | cómo se verificó |
|---|---|---|
| google-flow (`srz-google-flow-mcp`) | 1.0.1 en `tools/GoogleFlowMCP/package.json` del repo | lectura del repo; **la versión EN EJECUCIÓN se confirma con `server_info` del handshake — por confirmar en la máquina del dueño** |
| notebooklm (`notebooklm-mcp`, paquete `notebooklm-py[browser]`) | pin v0.8.5 (documentado en `services/mcp_manager.py` y `services/nlm_studio.py`) | lectura del repo; **confirmar con `server_info` al ejecutar la sonda** |

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
