' Launches the daily brief (morning/open run) with NO visible window.
' Task Scheduler runs this via wscript.exe (windowless host); WScript.Shell.Run
' with window-style 0 starts the Python process fully hidden. Keeps the normal
' user session (so network + .env access + idle detection work) — unlike S4U.
' pythonw.exe has no console at all; subprocess children inherit the hidden state,
' so no black window flashes during the ~4-min generation.
Dim py, script
py = "C:\Users\norma\drift-sentiment-agent\.venv\Scripts\pythonw.exe"
script = "C:\Users\norma\drift-sentiment-agent\scripts\daily_brief\run_brief_local.py"
CreateObject("WScript.Shell").Run """" & py & """ """ & script & """", 0, False
