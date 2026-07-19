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
& $git pull --rebase --autostash *>> $log
& $git push *>> $log
Add-Content $log "[done]" -Encoding utf8
