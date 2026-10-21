@echo off
REM ============================================================
REM  ALBRA - LANZADOR ROBUSTO (doble click y listo)
REM  - Comprueba si el servidor ya esta corriendo
REM  - Crea el entorno virtual solo la primera vez
REM  - Instala dependencias solo si requirements.txt cambio
REM  - Arranca el servidor en su propia ventana
REM  - Abre el navegador SOLO cuando el servidor responde
REM ============================================================
chcp 65001 >nul
title ALBRA - Iniciando...
cd /d "%~dp0backend"

REM ---------- 1. Localizar Python ----------
set "PY=python"
%PY% --version >nul 2>&1
if not errorlevel 1 goto have_py
set "PY=py -3"
%PY% --version >nul 2>&1
if not errorlevel 1 goto have_py
echo [ERROR] Python no encontrado.
echo         Instala Python 3.11+ desde python.org y marca
echo         "Add Python to PATH" durante la instalacion.
pause
exit /b 1
:have_py

REM ---------- 2. Ya esta corriendo? (doble click a prueba de duplicados) ----------
echo [1/4] Comprobando si el servidor ya esta activo...
call :health >nul 2>&1
if not errorlevel 1 (
    echo       Ya estaba corriendo. Abriendo dashboard...
    start "" http://127.0.0.1:8000
    timeout /t 2 >nul
    exit /b 0
)

REM ---------- 3. Entorno virtual (solo la primera vez) ----------
echo [2/4] Preparando entorno virtual...
if not exist .venv (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

REM ---------- 4. Dependencias (solo si cambiaron) ----------
echo [3/4] Comprobando dependencias...
for %%F in (requirements.txt) do set "REQSIG=%%~zF_%%~tF"
set "DEPS_SIG="
if exist .venv\.deps_ok set /p DEPS_SIG=<.venv\.deps_ok
if not "%REQSIG%"=="%DEPS_SIG%" (
    echo       Instalando/actualizando dependencias (puede tardar la primera vez)...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo pip install. Revisa tu conexion y vuelve a intentar.
        pause
        exit /b 1
    )
    echo %REQSIG%>".venv\.deps_ok"
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

REM ---------- 6. Arrancar servidor en ventana propia ----------
echo [4/4] Arrancando servidor en http://127.0.0.1:8000 ...
start "ALBRA SERVER - NO CERRAR" cmd /k ""%CD%\.venv\Scripts\python.exe" main.py"

REM ---------- 7. Esperar a que responda y abrir navegador ----------
set /a TRIES=0
:wait
set /a TRIES+=1
if %TRIES% gtr 60 (
    echo [AVISO] El servidor no respondio en 120s.
    echo         Revisa la ventana "ALBRA SERVER" para ver el error.
    pause
    exit /b 0
)
timeout /t 2 /nobreak >nul
call :health >nul 2>&1
if errorlevel 1 goto wait

start "" http://127.0.0.1:8000
echo.
echo [OK] Servidor listo. Dashboard abierto en tu navegador.
echo      Para detenerlo: DETENER-ALBRA.bat o cierra la ventana ALBRA SERVER.
timeout /t 4 >nul
exit /b 0

REM ---------- Subrutina de health check ----------
:health
".venv\Scripts\python.exe" -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).getcode()==200 else 1)" 2>nul
exit /b %errorlevel%
