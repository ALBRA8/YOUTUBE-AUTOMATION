@echo off
title Vincular Sesion Google - YouTube Automation
color 0A
cls

echo ====================================================================
echo        VINCULAR SESION GOOGLE (FLOW + NOTEBOOKLM)
echo ====================================================================
echo.

set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

set "PROFILE=%LOCALAPPDATA%\FlowImageChrome"

echo Saneando perfil de Chrome (%PROFILE%)...
if exist "%PROFILE%\Local State.bad" del /f /q "%PROFILE%\Local State.bad" >nul 2>&1
if exist "%PROFILE%\lockfile" del /f /q "%PROFILE%\lockfile" >nul 2>&1
if exist "%PROFILE%\SingletonLock" del /f /q "%PROFILE%\SingletonLock" >nul 2>&1
if exist "%PROFILE%\SingletonCookie" del /f /q "%PROFILE%\SingletonCookie" >nul 2>&1
if exist "%PROFILE%\SingletonSocket" del /f /q "%PROFILE%\SingletonSocket" >nul 2>&1

powershell -NoProfile -Command "$pref = Join-Path $env:LOCALAPPDATA 'FlowImageChrome\Default\Preferences'; if (Test-Path $pref) { try { $json = Get-Content $pref -Raw -Encoding UTF8 | ConvertFrom-Json; if ($json.profile) { $json.profile.exit_type = 'Normal'; $json.profile.exited_cleanly = $true; $json | ConvertTo-Json -Depth 32 -Compress | Set-Content $pref -Encoding UTF8 } } catch {} }" >nul 2>&1

echo [1/2] Abriendo Chrome en MODO SEGURO para inicio de sesion...
echo.
echo     Google bloquea el inicio de sesion si se abre con puertos de depuracion.
echo     Por eso abrimos Chrome normal en tu pantalla:
echo       1. Inicia sesion con tu cuenta de Google en la pestana de Accounts/Flow.
echo       2. Verifica que carguen Flow y NotebookLM.
echo       3. Cuando hayas iniciado sesion, CIERRA la ventana de Chrome.
echo.
echo Abriendo Chrome ahora mismo...

start "" "%CHROME%" --user-data-dir="%PROFILE%" --new-window --no-first-run --no-default-browser-check --disable-session-crashed-bubble --hide-crash-restore-bubble --disable-features=SessionCrashedBubble "https://accounts.google.com/ServiceLogin?continue=https://labs.google/fx/tools/flow" "https://notebooklm.google.com/"

echo.
echo ====================================================================
echo IMPORTANTE: Una vez que hayas iniciado sesion en Google y
echo HAYAS CERRADO la ventana de Chrome, presiona cualquier tecla aqui...
echo ====================================================================
pause >nul

echo.
echo [2/2] Levantando Chrome con el puerto 9333 conectado...
echo Chrome se abrira con tu sesion activa en el puerto 9333.
echo Dejalo abierto o minimizado.
echo.

if exist "%PROFILE%\lockfile" del /f /q "%PROFILE%\lockfile" >nul 2>&1
if exist "%PROFILE%\SingletonLock" del /f /q "%PROFILE%\SingletonLock" >nul 2>&1

powershell -NoProfile -Command "$pref = Join-Path $env:LOCALAPPDATA 'FlowImageChrome\Default\Preferences'; if (Test-Path $pref) { try { $json = Get-Content $pref -Raw -Encoding UTF8 | ConvertFrom-Json; if ($json.profile) { $json.profile.exit_type = 'Normal'; $json.profile.exited_cleanly = $true; $json | ConvertTo-Json -Depth 32 -Compress | Set-Content $pref -Encoding UTF8 } } catch {} }" >nul 2>&1

start "" "%CHROME%" --user-data-dir="%PROFILE%" --remote-debugging-port=9333 --new-window --no-first-run --no-default-browser-check --disable-session-crashed-bubble --hide-crash-restore-bubble --disable-features=SessionCrashedBubble "https://labs.google/fx/tools/flow" "https://notebooklm.google.com/"

echo Esperando 3 segundos a que el puerto 9333 responda...
timeout /t 3 /nobreak >nul

echo.
echo Capturando cookies para NotebookLM MCP...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/mcp/capture-google-session' -Method Post -TimeoutSec 10; Write-Host ('[OK] Sesion capturada exitosamente: ' + $r.cookies + ' cookies.') -ForegroundColor Green } catch { Write-Host '[INFO] Si el panel web esta abierto, pulsa «3. Capturar sesion» en el panel.' -ForegroundColor Yellow }"

echo.
echo ====================================================================
echo                    LISTO - SESION VINCULADA
echo ====================================================================
echo Tu perfil de Google esta autenticado tanto para Flow como para NotebookLM.
echo En el Panel Web (http://127.0.0.1:8000):
echo   - Haz clic en "Refrescar estado"
echo   - Ambos servicios quedaran en VERDE.
echo.
pause
