@echo off
REM ============================================================
REM  ALBRA - START - experiencia "npm run dev" en un solo golpe
REM ------------------------------------------------------------
REM  Doble click en start.bat (o `start.bat` en una terminal) y
REM  TODO queda corriendo:
REM    [1/5] Localiza Python (py -3 / python / python3)
REM    [2/5] Crea backend\.venv solo la primera vez
REM    [3/5] Instala dependencias SOLO si requirements.txt cambio,
REM          con progreso visible (nunca parece congelado)
REM    [4/5] Respeta HOST y PORT de backend\.env
REM    [5/5] uvicorn con HOT-RELOAD en PRIMER PLANO (logs vivos)
REM          + abre el navegador cuando /api/health responde
REM  El servidor vive en ESTA ventana: Ctrl+C para detener todo.
REM ------------------------------------------------------------
REM  Flags opcionales:
REM    start.bat --no-browser   no abre el dashboard automaticamente
REM    start.bat --fresh        fuerza reinstalar dependencias
REM ============================================================
setlocal EnableExtensions
chcp 65001 >nul
title ALBRA - modo dev (npm run dev)
set "NO_BROWSER=0"
set "FRESH=0"

REM ---------- 0. Flags ----------
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--no-browser" set "NO_BROWSER=1"
if /i "%~1"=="--fresh" set "FRESH=1"
shift
goto parse_args
:args_done

cd /d "%~dp0backend"

REM ---------- HOST/PORT desde .env (mismos defaults que config.py) ----------
set "HOST=127.0.0.1"
set "PORT=8000"
if exist .env for /f "eol=# tokens=1,* delims==" %%a in (.env) do (
    if /i "%%a"=="HOST" set "HOST=%%b"
    if /i "%%a"=="PORT" set "PORT=%%b"
)
set "URL=http://127.0.0.1:%PORT%"

REM ---------- 1. Localizar Python ----------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    python3 --version >nul 2>&1
    if not errorlevel 1 set "PY=python3"
)
if not defined PY (
    echo [ERROR] Python no encontrado.
    echo         Instala Python 3.11+ desde python.org y marca
    echo         "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)
echo [1/5] Python listo: %PY%

REM ---------- 2. Ya esta corriendo? (doble click a prueba de duplicados) ----------
call :health >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] El servidor ya esta corriendo en %URL%
    if "%NO_BROWSER%"=="0" start "" %URL%
    echo         Abriendo dashboard... esta ventana se cierra sola.
    timeout /t 3 >nul
    exit /b 0
)

REM ---------- 3. Entorno virtual (solo la primera vez) ----------
if not exist ".venv\Scripts\python.exe" (
    echo [2/5] Creando entorno virtual backend\.venv - solo la primera vez...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo [2/5] Entorno virtual OK - backend\.venv
)
set "VPY=%CD%\.venv\Scripts\python.exe"

REM ---------- 4. Dependencias (solo si requirements.txt cambio) ----------
if "%FRESH%"=="1" if exist ".venv\.deps_ok" del ".venv\.deps_ok" >nul 2>&1
for %%F in (requirements.txt) do set "REQSIG=%%~zF_%%~tF"
set "DEPS_SIG="
if exist .venv\.deps_ok set /p DEPS_SIG=<.venv\.deps_ok
if not "%REQSIG%"=="%DEPS_SIG%" (
    echo [3/5] Instalando dependencias - solo la 1a vez o si requirements.txt cambio...
    echo        Con progreso visible abajo; los proximos arranques saltan esto al instante.
    echo.
    "%VPY%" -m pip install --no-input --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Fallo pip install. Revisa tu conexion y vuelve a lanzar start.bat
        pause
        exit /b 1
    )
    echo %REQSIG%>".venv\.deps_ok"
) else (
    echo [3/5] Dependencias OK - sin cambios, instalacion omitida
)

REM ---------- 5. Aviso .env ----------
if not exist .env (
    echo.
    echo [AVISO] Falta backend\.env
    echo         Copia .env.example como .env y coloca tus claves.
    echo         El servidor arrancara, pero algunas funciones
    echo         quedaran sin configurar.
    echo.
)
echo [4/5] Config lista - HOST=%HOST% PORT=%PORT%

REM ---------- 6. Navegador automatico cuando el server responda ----------
if "%NO_BROWSER%"=="0" (
    start "ALBRA navegador" /min cmd /c ""%VPY%" _dev_wait_open.py %URL%"
)

REM ---------- 7. Servidor en PRIMER PLANO con hot-reload ----------
echo [5/5] Arrancando servidor en %URL% - hot-reload activado
echo.
echo        Logs en vivo abajo. Guarda un archivo y se recarga solo.
echo        Para DETENER: Ctrl+C aqui  -  o doble click en DETENER-con-ventana.bat
echo ============================================================
"%VPY%" -m uvicorn main:app --host %HOST% --port %PORT% --reload
if errorlevel 1 (
    echo.
    echo [ERROR] El servidor se detuvo con error. Revisa el log de arriba.
    pause
) else (
    echo.
    echo [OK] Servidor detenido. Hasta la proxima.
    timeout /t 3 >nul
)
exit /b 0

REM ---------- Subrutina de health check ----------
:health
".venv\Scripts\python.exe" -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('%URL%/api/health',timeout=2).getcode()==200 else 1)" 2>nul
exit /b %errorlevel%
