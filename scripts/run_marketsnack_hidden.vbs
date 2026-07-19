' Launches the MarketSnack watcher with NO visible window.
' Task Scheduler runs this via wscript.exe (windowless host); WScript.Shell.Run
' with window-style 0 starts the Python process fully hidden. Keeps the normal
' user session (so network + .env access work exactly as before) — unlike S4U.
Dim py, script
py = "C:\Users\norma\drift-sentiment-agent\.venv\Scripts\pythonw.exe"
script = "C:\Users\norma\drift-sentiment-agent\scripts\marketsnack_alerts.py"
CreateObject("WScript.Shell").Run """" & py & """ """ & script & """", 0, False
