' Launches the Sunday brief (--force: runs on the closed-market day) with NO window.
' See run_brief_hidden.vbs for the mechanics (wscript host + pythonw + window-style 0).
Dim py, script
py = "C:\Users\norma\drift-sentiment-agent\.venv\Scripts\pythonw.exe"
script = "C:\Users\norma\drift-sentiment-agent\scripts\daily_brief\run_brief_local.py"
CreateObject("WScript.Shell").Run """" & py & """ """ & script & """ --force", 0, False
