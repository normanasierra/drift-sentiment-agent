' Launches the git auto-sync with NO visible window. PowerShell's own -WindowStyle
' Hidden still flashes a console for a split second on launch; running it through
' wscript (a windowless host) with window-style 0 suppresses that flash entirely.
Dim cmd
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\norma\drift-sentiment-agent\scripts\git_autosync.ps1"""
CreateObject("WScript.Shell").Run cmd, 0, False
