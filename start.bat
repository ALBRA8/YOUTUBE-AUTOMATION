@echo off
REM ============================================================
REM  ALBRA - START - experiencia "npm run dev" en un solo golpe
REM ------------------------------------------------------------
REM  Doble click en start.bat (o `start.bat` en una terminal) y
REM  TODO queda corriendo:
REM    [1/5] Localiza Python (py -3 / python / python3)
REM    [2/5] Crea backend\.venv con SPINNER de progreso animado
REM    [3/5] Instala dependencias SOLO si requirements.txt cambio,
REM          con BARRAS DE PROGRESO REALES de pip - y AUTO-REPARACION:
REM          si faltan modulos (p.ej. ModuleNotFoundError) reinstala solo
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
set "SELF=%~f0"
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

REM CR para refrescar lineas del spinner (receta copy /Z)
for /f %%a in ('copy /Z "%SELF%" nul') do set "CR=%%a"
if not defined CR set "CR=."
set "SPN_FRAMES=|/-\"
set "VDONE=%CD%\_albra_venv.tmp"

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

REM ---------- 3. Entorno virtual con spinner animado ----------
if not exist ".venv\Scripts\python.exe" (
    del "%VDONE%" >nul 2>&1
    echo [2/5] Preparando entorno virtual - avance abajo...
    start "" /b cmd /c "%PY% -m venv .venv & if exist ".venv\Scripts\python.exe" (echo ok>"%VDONE%") else (echo fail>"%VDONE%")"
    call :spinner "Creando entorno virtual" "%VDONE%" 180
    del "%VDONE%" >nul 2>&1
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERROR] No se pudo crear el entorno virtual.
        echo         Cierra antivirus temporalmente o revisa espacio en disco.
        pause
        exit /b 1
    )
) else (
    echo [2/5] Entorno virtual OK - backend\.venv
)
set "VPY=%CD%\.venv\Scripts\python.exe"

REM ---------- 4. Dependencias: barras reales + auto-reparacion ----------
if "%FRESH%"=="1" if exist ".venv\.deps_ok" del ".venv\.deps_ok" >nul 2>&1
for %%F in (requirements.txt) do set "REQSIG=%%~zF_%%~tF"
set "DEPS_SIG="
if exist .venv\.deps_ok set /p DEPS_SIG=<.venv\.deps_ok
call :verify_deps
set "VOK=%errorlevel%"
if "%DEPS_SIG%"=="%REQSIG%" if "%VOK%"=="0" (
    echo [3/5] Dependencias OK - 14/14 modulos verificados, instalacion omitida
    goto deps_ready
)
if "%DEPS_SIG%"=="%REQSIG%" (
    echo [3/5] AVISO: entorno incompleto detectado - AUTO-REPARACION...
) else (
    echo [3/5] Instalando dependencias - solo la 1a vez o si requirements.txt cambio...
)
echo       Barras de descarga reales abajo - los proximos arranques saltan esto.
echo.
"%VPY%" -m pip install --progress-bar on --no-input --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo pip install. Revisa tu conexion y vuelve a lanzar start.bat
    pause
    exit /b 1
)
call :verify_deps
if errorlevel 1 (
    echo.
    echo [ERROR] pip termino pero faltan modulos. Ejecuta: start.bat --fresh
    pause
    exit /b 1
)
echo %REQSIG%>".venv\.deps_ok"
echo   [OK] 14/14 modulos verificados tras la instalacion
:deps_ready

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

REM ---------- Verificacion de 14 modulos de arranque (find_spec = instantaneo) ----------
:verify_deps
"%VPY%" -c "import importlib.util as u,sys;mods='fastapi uvicorn dotenv multipart httpx google.genai PIL apscheduler edge_tts yt_dlp googleapiclient google_auth_oauthlib faster_whisper av'.split();sys.exit(0) if all(u.find_spec(m) for m in mods) else sys.exit(1)" 2>nul
exit /b %errorlevel%

REM ---------- Spinner animado: %1=etiqueta %2=archivo-senal %3=max-segundos ----------
:spinner
set "SPN_LABEL=%~1"
set "SPN_DONE=%~2"
set /a SPN_MAX=%~3
set /a SPN_T=0
:spin_loop
if exist "%SPN_DONE%" goto spin_end
if %SPN_T% geq %SPN_MAX% goto spin_end
set /a SPN_I=SPN_T %% 4
call set "SPN_F=%%SPN_FRAMES:~%SPN_I%,1%%"
<nul set /p "=%CR%  %SPN_F% %SPN_LABEL% - %SPN_T%s transcurridos...    "
timeout /t 1 /nobreak >nul
set /a SPN_T+=1
goto spin_loop
:spin_end
<nul set /p "=%CR%  [OK] %SPN_LABEL% - %SPN_T%s                       "
echo.
exit /b 0

REM ---------- Subrutina de health check ----------
:health
".venv\Scripts\python.exe" -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('%URL%/api/health',timeout=2).getcode()==200 else 1)" 2>nul
exit /b %errorlevel%
