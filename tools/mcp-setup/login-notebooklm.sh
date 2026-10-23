#!/usr/bin/env bash
# ═══ INT-022 · Primera vez: login de Google para NotebookLM MCP ═══
command -v notebooklm >/dev/null || { echo "[ERROR] notebooklm no está en PATH."; echo "        Instala: uv tool install \"notebooklm-py[browser]\""; exit 1; }
echo "[INFO] Abriendo navegador para login de Google (cierra al terminar)..."
notebooklm login
echo "[OK] Listo. Vuelve al panel y pulsa 'Conectar' en NotebookLM MCP."
