@echo off
setlocal enabledelayedexpansion
title Vincular Sesion Google Unificada - YouTube Automation
color 0A

echo ====================================================================
echo        VINCULAR SESION GOOGLE (PERFIL UNIFICADO MCP)
echo ====================================================================
echo.

set "BASE_DIR=%~dp0..\.."
set "PROFILE=%BASE_DIR%\backend\data\google_profile_global"

set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
    echo [ERROR] No se encontro Google Chrome en la maquina.
    echo Instala Google Chrome oficial y vuelve a ejecutar este script.
    pause
    exit /b 1
)

echo [1/3] Abriendo Chrome en MODO LIMPIO para inicio de sesion seguro...
echo.
echo     Google bloquea el inicio de sesion si se abre directamente con
echo     puertos de depuracion (CDP). Por eso primero abrimos Chrome normal
echo     para que te loguees SIN bloqueos de seguridad de Google.
echo.
echo     Acciones en el navegador:
echo       1. Inicia sesion con tu cuenta de Google en la pestana de Accounts.
echo       2. Verifica que cargue Google Flow (flow.google.com).
echo       3. Verifica que cargue NotebookLM (notebooklm.google.com).
echo       4. Una vez logueado, CIERRA COMPLETAMENTE la ventana de Chrome.
echo.
echo Abriendo Chrome...

start "" "%CHROME%" --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check "https://accounts.google.com/" "https://flow.google.com/" "https://notebooklm.google.com/"

echo.
echo ====================================================================
echo IMPORTANTE: Una vez que hayas completado el login en Google y
echo HAYAS CERRADO la ventana de Chrome que se acaba de abrir,
echo presiona cualquier tecla aqui para continuar con el Paso 2...
echo ====================================================================
pause >nul

echo.
echo [2/3] Levantando Chrome en MODO CDP (Puerto 9333)...
echo Chrome se abrira ahora con tu sesion activa y el puerto CDP conectado.
echo NO CIERRES esa ventana de Chrome (puedes minimizarla).
echo.

start "" "%CHROME%" --user-data-dir="%PROFILE%" --remote-debugging-port=9333 --no-first-run --no-default-browser-check "https://flow.google.com/" "https://notebooklm.google.com/"

echo Esperando 3 segundos a que el puerto CDP 9333 responda...
timeout /t 3 /nobreak >nul

echo.
echo [3/3] Capturando cookies para NotebookLM MCP...
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/mcp/capture-google-session' -Method Post -TimeoutSec 10; Write-Host ('[OK] Sesion capturada exitosamente: ' + $r.cookies + ' cookies.') -ForegroundColor Green } catch { Write-Host '[AVISO] El backend aun no captura automaticamente, pulsa «Capturar sesion» en el panel web.' -ForegroundColor Yellow }"

echo.
echo ====================================================================
echo                    LISTO - SESION VINCULADA
echo ====================================================================
echo Tu perfil de Google esta autenticado tanto para Flow como para NotebookLM.
echo En el Panel Web (http://127.0.0.1:8000), pestana MCP:
echo   - Veras ambos servicios listos para usar
echo   - Deja la ventana de Chrome de Flow abierta o minimizada
echo.
pause
