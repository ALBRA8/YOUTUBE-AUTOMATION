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
' El lanzador vive en launchers\: la raiz del proyecto es el ABUELO
' de este script (launchers -> raiz).
Dim raiz
raiz = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
carpeta = raiz
sh.CurrentDirectory = carpeta
py = carpeta & "\backend\.venv\Scripts\python.exe"

If fso.FileExists(py) Then
    ' Ruta silenciosa: ventana oculta (0), sin esperar (False)
    sh.Run """" & py & """ launchers\lanzador_albra.py", 0, False
Else
    ' Primera vez: asistente visible (crea venv + dependencias + arranca)
    sh.Run "cmd /c """ & carpeta & "\launchers\start.bat""", 1, False
End If
