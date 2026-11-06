' ============================================================
'  ALBRA - DETENER SERVIDOR (doble click, sin terminal)
'  Mata solo procesos PYTHON escuchando en el puerto del servidor
'  y confirma con un mensaje emergente (no es una terminal).
' ============================================================
Option Explicit
Dim sh, ps
Set sh = CreateObject("WScript.Shell")
' Puerto por defecto 8000. Si cambiaste PORT en backend\.env,
' abre este archivo con el Bloc de notas y cambia el numero.
ps = "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | " & _
     "ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; " & _
     "if ($p -and $p.ProcessName -match 'python') { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }"
sh.Run "powershell -NoProfile -WindowStyle Hidden -Command """ & ps & """", 0, True
MsgBox "Servidor ALBRA detenido." & vbCrLf & "(si seguia algo abierto, era otra aplicacion)", 64, "ALBRA"
