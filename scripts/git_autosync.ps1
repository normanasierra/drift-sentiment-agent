# Auto-sync this repo with GitHub: pull remote changes (rebase, auto-stashing any
# local edits) then push local commits. Run by the "GitAutoSync" scheduled task
# (~every 30 min + at logon). Never commits — only syncs already-committed state.
$ErrorActionPreference = 'Continue'
$git  = 'C:\Program Files\Git\cmd\git.exe'
$repo = 'C:\Users\norma\drift-sentiment-agent'
Set-Location $repo
$log = Join-Path $repo 'output\git_autosync.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

Add-Content $log ("[{0}] === autosync ===" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8
# Redirect git's stdout+stderr at the OS level via cmd, so PowerShell doesn't wrap
# git's normal progress (which it writes to stderr) as "NativeCommandError" noise.
$q = '"'
& cmd /c ("$q$git$q pull --rebase --autostash >> $q$log$q 2>&1")
& cmd /c ("$q$git$q push >> $q$log$q 2>&1")
Add-Content $log "[done]" -Encoding utf8
