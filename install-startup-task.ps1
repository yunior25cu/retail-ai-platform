# ============================================================
# install-startup-task.ps1
# Registra una tarea programada que arranca start-retail-ai.bat
# automaticamente al login del usuario.
#
# Uso:
#   Click derecho > Ejecutar con PowerShell
#   (Si pide UAC, aceptar.)
#
# Para desinstalar:
#   schtasks /Delete /TN RetailAiUvicorn /F
# ============================================================

$ErrorActionPreference = "Stop"
$batPath = Join-Path $PSScriptRoot "start-retail-ai.bat"
$taskName = "RetailAiUvicorn"

if (-not (Test-Path $batPath)) {
    Write-Host "[ERROR] No se encontro $batPath" -ForegroundColor Red
    pause
    exit 1
}

# Eliminar tarea previa si existe (idempotente)
$existing = schtasks /Query /TN $taskName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Tarea previa encontrada, eliminando..."
    schtasks /Delete /TN $taskName /F | Out-Null
}

# Crear la tarea
Write-Host "Registrando tarea $taskName -> $batPath"
schtasks /Create /SC ONLOGON /TN $taskName /TR "`"$batPath`"" /F

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] No se pudo registrar la tarea." -ForegroundColor Red
    Write-Host "Posibles causas:" -ForegroundColor Yellow
    Write-Host "  - PowerShell sin permisos (probar Ejecutar como administrador)"
    Write-Host "  - Politica de ejecucion bloqueada"
    pause
    exit 1
}

Write-Host ""
Write-Host "[OK] Tarea registrada." -ForegroundColor Green
Write-Host "Se ejecutara en el proximo login del usuario actual."
Write-Host ""
Write-Host "Para arrancar AHORA sin esperar al login:"
Write-Host "  schtasks /Run /TN $taskName"
Write-Host ""
Write-Host "Para verificar estado:"
Write-Host "  schtasks /Query /TN $taskName"
Write-Host ""
Write-Host "Para desinstalar:"
Write-Host "  schtasks /Delete /TN $taskName /F"
pause
