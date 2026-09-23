$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    docker compose exec -T api python -m unittest discover -s tests -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }
    docker compose exec -T api python -m tests.check_permissions
    if ($LASTEXITCODE -ne 0) { throw 'Database least-privilege tests failed' }
    $webBinding = docker compose port web 8080
    if ($LASTEXITCODE -ne 0) { throw 'Cannot find web port' }
    $apiBinding = docker compose port api 8000
    if ($LASTEXITCODE -ne 0) { throw 'Cannot find API port' }
    foreach ($binding in @($webBinding, $apiBinding)) {
        $result = Invoke-RestMethod -Uri "http://$binding/health/ready"
        if ($result.status -ne 'ready') { throw "Service not ready: $binding" }
        try {
            Invoke-RestMethod -Uri "http://$binding/api/v1/system/capabilities" | Out-Null
            throw 'Capabilities unexpectedly public; authentication required by contract.'
        } catch {
            if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 401) { throw }
        }
    }
    Write-Host 'PASS: unit tests, database privileges, API and reverse proxy readiness'
} finally { Pop-Location }
