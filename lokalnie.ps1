# Test lokalny w Dockerze (Windows). Zmiany w app/ widać od razu (live reload).
Set-Location -Path $PSScriptRoot
$port = if ($env:HELPERS_PORT) { $env:HELPERS_PORT } else { '8000' }
Write-Host "Strona: http://localhost:$port"
Write-Host "Panel:  http://localhost:$port/admin  (hasło: dev)  (Ctrl+C zatrzymuje)"
docker compose -f docker-compose.local.yml up --build
