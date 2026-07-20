' Starts the Wakanda web server (uvicorn on 127.0.0.1:8000) with NO visible window.
' Launched at logon (Startup-folder shortcut / WakandaServer task) via wscript.exe
' (windowless); WScript.Shell.Run with window-style 0 hides the cmd host. Runs in the
' user session so .env + network work. Output -> output/wakanda_server.log.
'
' --reload makes uvicorn watch the source and restart itself whenever a .py file
' changes, so a `git pull` (or a local edit) goes LIVE with no manual restart. The
' reloader only reacts to *.py changes, so the log writes never trigger a reload loop.
Dim q, repo, cmd
q = Chr(34)
repo = "C:\Users\norma\drift-sentiment-agent"
cmd = "cmd /c cd /d " & q & repo & q & " && " & q & repo & "\.venv\Scripts\python.exe" & q & _
      " -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload > " & q & repo & "\output\wakanda_server.log" & q & " 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
