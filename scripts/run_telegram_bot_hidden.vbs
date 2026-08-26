' Launch the Telegram agent bot with NO visible window (persistent listener).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\norma\drift-sentiment-agent"
sh.Run """C:\Users\norma\drift-sentiment-agent\.venv\Scripts\python.exe"" ""C:\Users\norma\drift-sentiment-agent\scripts\telegram_bot.py""", 0, False
