' Starts the Wakanda web server (uvicorn on 127.0.0.1:8000) with NO visible window.
' Launched at logon by the WakandaServer scheduled task via wscript.exe (windowless);
' WScript.Shell.Run with window-style 0 hides the cmd host. Runs in the user session
' so .env + network work. Server output -> output/wakanda_server.log for debugging.
Dim q, repo, cmd
q = Chr(34)
repo = "C:\Users\norma\drift-sentiment-agent"
cmd = "cmd /c cd /d " & q & repo & q & " && " & q & repo & "\.venv\Scripts\python.exe" & q & _
      " -m uvicorn server:app --host 127.0.0.1 --port 8000 > " & q & repo & "\output\wakanda_server.log" & q & " 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
