"""U1 · Agregador de estado de SOLO LECTURA del «Ecosistema Google».

Qué es: traducción HUMANA y honesta del estado que ya producen
`manager.status()` (lo que sirve /api/mcp/status) y
`manager.google_login_status()` (GET /api/mcp/login-google). NO toca la
lógica de conexión (mcp_manager / GoogleFlowMCP quedan intactos): no
conecta, no lanza procesos, no lee cookies — solo interpreta dict ya
calculados y devuelve un semáforo por pieza con la acción siguiente en
español claro.

Por qué existe: el panel decía «ECOSISTEMA CONECTADO» cuando CUALQUIER
pieza respondía, mientras Flow marcaba «Chrome no responde en el puerto
CDP 9333» y el desplegable de cuaderno aparecía vacío. Aquí el estado
«todo conectado» SOLO es cierto si TODAS las piezas requeridas están ok
(chrome, flow, notebooklm, cuaderno seleccionado).

Hermético y puro: sin red, sin I/O — las funciones reciben dicts y
devuelven dicts. Los endpoints (main.py) juntan los datos.
"""
from __future__ import annotations

_ACCION_CHROME = ("Abre el Chrome del ecosistema: pulsa «Conectar todo» y "
                  "haz login con tu cuenta en la ventana que se abre.")
_ACCION_FLOW = ("Pulsa «Conectar todo» (o «Conectar» en la fila Google "
                "Flow) para levantar el MCP de Flow.")
_ACCION_NBLM = ("Pulsa «Conectar todo» (o «Conectar» en la fila "
                "NotebookLM) para levantar el MCP de NotebookLM.")
_ACCION_CUADERNO_CON_NBLM = ("NotebookLM ya está conectado: pulsa «Listar / "
                             "refrescar notebooks» y elige tu cuaderno en "
                             "el desplegable (se recuerda por nicho).")
_ACCION_CUADERNO_SIN_NBLM = ("Elige el cuaderno después de conectar "
                             "NotebookLM: el desplegable se rellena solo.")
_SIGUIENTE_TODO_OK = ("Todo listo: escribe la idea y lanza «Run Full "
                      "Pipeline».")

# Orden de diagnóstico del siguiente paso: primero lo físico (Chrome),
# luego los MCP y por último la elección de cuaderno.
_ORDEN = ("chrome", "flow", "notebooklm", "cuaderno")


def _estado(servicio: dict | None) -> str:
    return str((servicio or {}).get("state") or "disconnected")


def _piezas_chrome(gsess: dict) -> dict:
    puerto = gsess.get("cdp_port") or 9333
    arriba = bool(gsess.get("chrome_up"))
    return {
        "ok": arriba,
        "detalle": (f"Chrome CDP {puerto} arriba"
                    if arriba else
                    f"Chrome no responde en el puerto CDP {puerto}"),
        "accion_siguiente": "" if arriba else _ACCION_CHROME,
    }


def _pieza_mcp(nombre: str, etiqueta: str, servicio: dict | None,
               accion: str) -> dict:
    estado = _estado(servicio)
    if estado == "connected":
        tools = (servicio or {}).get("tools") or []
        return {"ok": True,
                "detalle": f"{etiqueta} conectado y autenticado"
                           + (f" · {len(tools)} tools" if tools else ""),
                "accion_siguiente": ""}
    detalle = {"auth_required": f"{etiqueta}: sesión Google no válida "
                                "(auth_required)",
               "connecting": f"{etiqueta}: conectando…",
               "error": f"{etiqueta}: error técnico"
               }.get(estado, f"{etiqueta}: no conectado")
    err = str((servicio or {}).get("last_error") or "").strip()
    if err:
        detalle += f" — {err[:120]}"
    return {"ok": False, "detalle": detalle, "accion_siguiente": accion}


def _pieza_cuaderno(notebook_id: str | None, nb_ok: bool) -> dict:
    nid = str(notebook_id or "").strip()
    if nid and nb_ok:
        # ID COMPLETO: recortar el cuaderno activo es dejar al dueño sin
        # saber cuál está elegido (el ID es corto y validado, es seguro).
        return {"ok": True,
                "detalle": f"cuaderno «{nid}» seleccionado",
                "accion_siguiente": ""}
    if not nid and nb_ok:
        return {"ok": False,
                "detalle": "NotebookLM está conectado pero no hay cuaderno "
                           "elegido (el desplegable aparece vacío)",
                "accion_siguiente": _ACCION_CUADERNO_CON_NBLM}
    return {"ok": False,
            "detalle": "sin cuaderno elegido (NotebookLM sin conectar)",
            "accion_siguiente": _ACCION_CUADERNO_SIN_NBLM}


def resumen_ecosistema(services: dict, gsess: dict, *,
                       notebook_id: str | None = None) -> dict:
    """PURO · U1. `services` = lo que /api/mcp/status sirve en su clave
    «services»; `gsess` = lo que GET /api/mcp/login-google (google_login_
    status) devuelve; `notebook_id` = cuaderno vigente (elección de la UI,
    memoria del nicho o NOTEBOOKLM_NOTEBOOK_ID). Devuelve:

        {"piezas": {"chrome": {ok, detalle, accion_siguiente},
                    "flow": …, "notebooklm": …, "cuaderno": …},
         "listo_para_pipeline": bool,     # las 4 piezas ok
         "todo_conectado": bool,          # SOLO con TODAS ok (adiós a la
                                          # mentira del badge)
         "siguiente_paso": str}           # en español claro
    """
    services = services if isinstance(services, dict) else {}
    gsess = gsess if isinstance(gsess, dict) else {}
    chrome = _piezas_chrome(gsess)
    flow = _pieza_mcp("google-flow", "Google Flow",
                      services.get("google-flow"), _ACCION_FLOW)
    nblm = _pieza_mcp("notebooklm", "NotebookLM",
                      services.get("notebooklm"), _ACCION_NBLM)
    cuaderno = _pieza_cuaderno(notebook_id, nblm["ok"])
    piezas = {"chrome": chrome, "flow": flow,
              "notebooklm": nblm, "cuaderno": cuaderno}
    todo_ok = all(piezas[k]["ok"] for k in _ORDEN)
    siguiente = next((piezas[k]["accion_siguiente"] for k in _ORDEN
                      if not piezas[k]["ok"]), _SIGUIENTE_TODO_OK)
    return {"piezas": piezas,
            "listo_para_pipeline": todo_ok,
            "todo_conectado": todo_ok,
            "siguiente_paso": siguiente}
