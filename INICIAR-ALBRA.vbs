' ============================================================
'  ALBRA - INICIO SILENCIOSO (doble click, cero ventanas)
'  - Si el entorno virtual existe: lanza el servidor OCULTO
'    y abre el navegador cuando responde (sin terminal).
'  - Si es la primera vez: abre el asistente visible una unica vez.
' ============================================================
Option Explicit
Dim fso, sh, carpeta, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = carpeta
py = carpeta & "\backend\.venv\Scripts\python.exe"

If fso.FileExists(py) Then
    ' Ruta silenciosa: ventana oculta (0), sin esperar (False)
    sh.Run """" & py & """ lanzador_albra.py", 0, False
Else
    ' Primera vez: asistente visible (crea venv + dependencias + arranca)
    sh.Run "cmd /c """ & carpeta & "\INICIAR-DEBUG-con-ventana.bat""", 1, False
End If
