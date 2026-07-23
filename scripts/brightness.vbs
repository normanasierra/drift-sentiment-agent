' Set the external monitor brightness to the percent passed as the first argument,
' with NO console flash. Backs the desktop "Brillo NN%" shortcuts:
'     wscript.exe brightness.vbs 25
' Delegates to set_brightness.ps1 (DDC/CI). Defaults to 50% if no arg is given.
Dim pct, repo, cmd
repo = "C:\Users\norma\drift-sentiment-agent"
If WScript.Arguments.Count > 0 Then pct = WScript.Arguments(0) Else pct = "50"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & _
      repo & "\scripts\set_brightness.ps1"" -Percent " & pct
CreateObject("WScript.Shell").Run cmd, 0, False
