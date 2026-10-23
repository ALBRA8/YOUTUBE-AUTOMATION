#!/usr/bin/env bash
# ═══ INT-022 · Chrome DEDICADO de GoogleFlowMCP con CDP persistente ═══
DIR="$(cd "$(dirname "$0")/../GoogleFlowMCP" && pwd)"
command -v node >/dev/null || { echo "[ERROR] node no está en PATH."; exit 1; }
[ -f "$DIR/src/mcp.js" ] || { echo "[ERROR] No existe $DIR/src/mcp.js — revisa FLOW_MCP_DIR."; exit 1; }
echo "[INFO] Lanzando Chrome dedicado de Flow (sesión persistente)..."
cd "$DIR" && node src/cli.js chrome
