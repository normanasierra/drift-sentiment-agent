# Autentica el CLI de Claude para el brief diario (una sola vez).
# Se ejecuta con doble clic en el lanzador "Autenticar-Candy.cmd" del Escritorio.

Write-Host ""
Write-Host "  ===  Candy: autenticar Claude para el brief diario  ===" -ForegroundColor Magenta
Write-Host ""

$claude = Get-ChildItem "$env:APPDATA\Claude\claude-code\*\claude.exe" -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName

if (-not $claude) {
    Write-Host "  No se encontro claude.exe." -ForegroundColor Red
    Write-Host "  Abre la app de Claude una vez y vuelve a ejecutar este boton." -ForegroundColor Red
    Write-Host ""
    Read-Host "  Presiona Enter para cerrar"
    exit 1
}

Write-Host "  Usando: $claude" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Se abrira el navegador (o vera un enlace abajo) para que inicies" -ForegroundColor Yellow
Write-Host "  sesion con tu cuenta de Claude. Autoriza y listo." -ForegroundColor Yellow
Write-Host ""

& $claude setup-token
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "  Listo! Autenticacion completada. Ya puedes cerrar esta ventana." -ForegroundColor Green
} else {
    Write-Host "  Termino con codigo $code. Si viste un error, cuentaselo a Candy." -ForegroundColor Yellow
}
Write-Host ""
Read-Host "  Presiona Enter para cerrar"
