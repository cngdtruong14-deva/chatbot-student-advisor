$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & "$PSScriptRoot/Initialize-Local.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'Local configuration initialization failed' }
    & "$PSScriptRoot/Initialize-Application.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'Application secret initialization failed' }
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Docker Compose configuration' }
    docker compose build api web
    if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
    docker compose up -d --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Inspect docker compose ps -a and logs locally.' }
    docker compose ps -a
} finally { Pop-Location }
