#!/usr/bin/env python3
"""FIXTURE de tests — Servidor MCP stdio FALSO para baterías de INT-022.

Habla JSON-RPC 2.0 delimitado por saltos de línea (mismo framing que los
servidores reales). Cero red, cero navegadores, cero dependencias.

Modos (variables de entorno):
  FAKE_MCP_MODE      flow | nblm            (define el catálogo de tools)
  FAKE_MCP_FAIL_AUTH 1 → las tools de sesión devuelven error de autenticación
  FAKE_MCP_SLOW_MS   N → la tool 'slow' duerme N ms antes de responder
"""
import json
import os
import sys
import time

MODE = os.environ.get("FAKE_MCP_MODE", "flow")
FAIL_AUTH = os.environ.get("FAKE_MCP_FAIL_AUTH", "0") == "1"
SLOW_MS = int(os.environ.get("FAKE_MCP_SLOW_MS", "0"))

TOOLS = {
    "flow": [
        {"name": "flow_list_assets", "description": "Lista activos del proyecto Flow"},
        {"name": "flow_generate_image", "description": "Genera imágenes"},
        {"name": "flow_new_project", "description": "Crea proyecto"},
        {"name": "echo", "description": "Devuelve los argumentos recibidos (json)"},
    ],
    "nblm": [
        {"name": "list_notebooks", "description": "Lista notebooks del usuario"},
        {"name": "add_notebook_source", "description": "Agrega una fuente al notebook"},
        {"name": "echo", "description": "Devuelve los argumentos recibidos (json)"},
        {"name": "slow", "description": "Responde tras FAKE_MCP_SLOW_MS"},
    ],
}


def out(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def content(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}], "isError": False}}


def main() -> None:
    sys.stderr.write(f"fake-mcp[{MODE}] listo (fail_auth={FAIL_AUTH})\n")
    sys.stderr.flush()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        rid = msg.get("id")
        if method == "initialize":
            out({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"fake-{MODE}", "version": "0.0.0"}}})
        elif method == "notifications/initialized":
            pass  # notificación: sin respuesta
        elif method == "tools/list":
            out({"jsonrpc": "2.0", "id": rid,
                 "result": {"tools": TOOLS["nblm" if MODE == "nblm" else "flow"]}})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            args = (msg.get("params") or {}).get("arguments") or {}
            if name == "slow":
                time.sleep(SLOW_MS / 1000.0)
                out({"jsonrpc": "2.0", "id": rid, **content(f"slow ok ({SLOW_MS}ms)")})
            elif name == "echo":
                out({"jsonrpc": "2.0", "id": rid,
                     **content(json.dumps(args, ensure_ascii=False, sort_keys=True))})
            elif FAIL_AUTH:
                if MODE == "flow":
                    # mismo texto real de GoogleFlowMCP ante sesión caída
                    out({"jsonrpc": "2.0", "id": rid, "result": {
                        "content": [{"type": "text", "text": "Not signed in to Google"}],
                        "isError": True}})
                else:
                    out({"jsonrpc": "2.0", "id": rid, "error": {
                        "code": -32000, "message": "auth required: cookies expired "
                                                   "(run notebooklm login)"}})
            elif MODE == "flow":
                out({"jsonrpc": "2.0", "id": rid,
                     **content("- asset1.png\n- asset2.png" if name == "flow_list_assets"
                               else f"{name} ok")})
            else:
                out({"jsonrpc": "2.0", "id": rid,
                     **content("notebooks: n1, n2" if name == "list_notebooks"
                               else f"{name} ok")})


if __name__ == "__main__":
    main()
