@echo off
rem ═══ INT-022 · Primera vez: login de Google para NotebookLM MCP ═══
rem Abre un Chromium gestionado por notebooklm-py para que inicies sesión
rem UNA vez. La sesión queda en storage_state.json (0600) y el panel deja
rem de mostrar el badge rojo AUTH_REQUIRED.
where notebooklm >nul 2>nul || (echo [ERROR] notebooklm no esta en PATH.& echo         Instala: uv tool install "notebooklm-py[browser]==0.8.5"& pause& exit /b 1)
echo [INFO] Abriendo navegador para login de Google (cierra la ventana al terminar)...
call notebooklm login
echo [OK] Listo. Vuelve al panel y pulsa "Conectar" en NotebookLM MCP.
pause
