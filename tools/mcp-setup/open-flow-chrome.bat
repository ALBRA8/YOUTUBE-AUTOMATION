@echo off
rem ═══ INT-022 · Chrome DEDICADO de GoogleFlowMCP con CDP persistente ═══
rem Abre el Chrome de Flow (perfil propio + puerto FLOW_CDP_PORT) para que
rem inicies sesión de Google Flow UNA vez. Deja esta ventana/minimizado:
rem el servidor MCP se acopla por CDP a ESTE Chrome.
setlocal
set "DIR=%~dp0..\GoogleFlowMCP"
where node >nul 2>nul || (echo [ERROR] node no esta en PATH.& pause& exit /b 1)
if not exist "%DIR%\src\mcp.js" (echo [ERROR] No existe %DIR%\src\mcp.js — revisa FLOW_MCP_DIR.& pause& exit /b 1)
echo [INFO] Lanzando Chrome dedicado de Flow (sesion persistente)...
cd /d "%DIR%" && node src/cli.js chrome
pause
