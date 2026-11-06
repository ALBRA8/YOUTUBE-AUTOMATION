@echo off
REM ============================================================
REM  ALBRA - DETENER SERVIDOR
REM  Mata solo procesos PYTHON escuchando en el puerto 8000
REM ============================================================
chcp 65001 >nul
title ALBRA - Detener
echo Deteniendo servidor ALBRA (puerto 8000)...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -match 'python') { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; Write-Host ('  Detenido PID ' + $p.Id) } }"
timeout /t 1 >nul
echo [OK] Listo. Si seguia algo abierto, cierre la ventana ALBRA SERVER.
pause
