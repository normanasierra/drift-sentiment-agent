' Launches the screens summary (RSI + wall<->magneto gap -> Telegram) with NO window.
' Was python.exe (visible console 3x/day); now wscript host + pythonw + window-style 0.
Dim py, script
py = "C:\Users\norma\drift-sentiment-agent\.venv\Scripts\pythonw.exe"
script = "C:\Users\norma\drift-sentiment-agent\scripts\daily_brief\screens_alert.py"
CreateObject("WScript.Shell").Run """" & py & """ """ & script & """", 0, False
