<#
  Daily pre-market brief runner (local, headless).
  1. Runs claude -p with brief_prompt.md to research the market and write
     output/brief_email.html and output/brief_whatsapp.txt.
  2. Verifies both files were produced fresh (never sends stale content).
  3. Emails the full brief and WhatsApps the key points via the send scripts.
  4. Logs to output/brief_<date>.log; on failure, best-effort WhatsApp alert.
  Invoked by the "DriftDailyBrief" scheduled task (wake-to-run, 9am Mon-Fri).
  Secrets come from .env in the repo root (never committed).
#>

$ErrorActionPreference = 'Stop'

$repo      = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py        = Join-Path $repo '.venv\Scripts\python.exe'
$briefDir  = $PSScriptRoot
$prompt    = Join-Path $briefDir 'brief_prompt.md'
$outDir    = Join-Path $repo 'output'
$emailFile = Join-Path $outDir 'brief_email.html'
$waFile    = Join-Path $outDir 'brief_whatsapp.txt'

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd'
$log   = Join-Path $outDir "brief_$stamp.log"

# Second log copy in the user profile root, used to diagnose scheduled-task runs
# whose repo-output writes aren't visible from the debug environment.
$dbg = Join-Path $env:USERPROFILE 'brief_debug.log'
function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Add-Content -Path $dbg -Value $line -Encoding utf8 -ErrorAction SilentlyContinue
}
function Alert($msg) {
    try { $msg | & $py (Join-Path $briefDir 'send_whatsapp.py') *>> $log } catch {}
}

Log "===== Daily brief run start ====="

# Auth token for headless claude -p (from .env). The desktop app's own login
# is NOT visible to headless claude -p; claude setup-token issues this token.
$tokLine = Get-Content (Join-Path $repo '.env') -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*CLAUDE_CODE_OAUTH_TOKEN\s*=' } | Select-Object -First 1
if ($tokLine) { $env:CLAUDE_CODE_OAUTH_TOKEN = ($tokLine -split '=', 2)[1].Trim() }
if (-not $env:CLAUDE_CODE_OAUTH_TOKEN) {
    Log "FATAL: CLAUDE_CODE_OAUTH_TOKEN not set in .env."
    Alert "Brief $stamp fallo: falta el token de Claude en .env."
    exit 1
}

# Resolve claude.exe. This machine runs the Microsoft Store (MSIX) build, so the
# exe lives under %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\... The
# path is version-stamped, so resolve the newest (survives app updates).
$globs = @("$env:LOCALAPPDATA\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\*\claude.exe", "$env:APPDATA\Claude\claude-code\*\claude.exe")
$exe = Get-ChildItem $globs -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
if (-not $exe) {
    Log "FATAL: claude.exe not found (checked MSIX package and APPDATA)."
    Alert "Brief $stamp fallo: no se encontro claude.exe."
    exit 1
}
Log "Using claude: $exe"

# Clear stale output so we never send yesterday's brief.
Remove-Item $emailFile, $waFile -ErrorAction SilentlyContinue

# Generate the brief.
Set-Location $repo
Log "Running claude -p ..."
try {
    Get-Content $prompt -Raw | & $exe -p --permission-mode acceptEdits --allowedTools WebSearch WebFetch Write Read *>> $log
    $code = $LASTEXITCODE
} catch {
    Log "ERROR invoking claude: $_"
    $code = 1
}
Log "claude exit code: $code"

# Verify fresh output (non-empty, written in the last 40 minutes).
function Fresh($f) {
    if (-not (Test-Path $f)) { return $false }
    $item = Get-Item $f
    return ($item.Length -gt 0) -and ($item.LastWriteTime -gt (Get-Date).AddMinutes(-40))
}
if ((-not (Fresh $emailFile)) -or (-not (Fresh $waFile))) {
    Log "FATAL: brief files missing or stale - NOT sending."
    Alert "Brief $stamp fallo al generarse. Revisa el log: $log"
    exit 1
}
Log "Brief files OK."

# Send.
$dateEs = (Get-Date).ToString('dddd d/MM/yyyy', [System.Globalization.CultureInfo]::GetCultureInfo('es-ES'))
Log "Sending email ..."
& $py (Join-Path $briefDir 'send_email.py') --subject "Brief de Mercado - $dateEs" --body-file $emailFile --html *>> $log
$emailCode = $LASTEXITCODE
Log "send_email exit code: $emailCode"
Log "Sending WhatsApp ..."
& $py (Join-Path $briefDir 'send_whatsapp.py') --text-file $waFile *>> $log
$waCode = $LASTEXITCODE
Log "send_whatsapp exit code: $waCode"

if ($emailCode -ne 0 -or $waCode -ne 0) {
    Log "===== Run finished WITH SEND ERRORS ====="
    exit 1
}
Log "===== Run finished OK ====="
exit 0
