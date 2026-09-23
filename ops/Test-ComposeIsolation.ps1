<#
.SYNOPSIS
Runs a temporary second Docker Compose stack and proves it does not disturb the root stack.

.DESCRIPTION
Only temporary containers/networks are removed. All database volumes and local test configuration are retained.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runId = [guid]::NewGuid().ToString('N').Substring(0, 12)
$testProject = "sic-advisor-isolation-$runId"
$testTag = "isolation-$runId"
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "student-advisor-compose-$runId"
$envFile = Join-Path $testRoot '.env'
$started = $false

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes); return [Convert]::ToBase64String($bytes) } finally { $rng.Dispose() }
}
function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop(); return $port
}
function Invoke-Compose([string[]]$Arguments) {
    & docker compose --project-directory $projectRoot -f (Join-Path $projectRoot 'compose.yaml') --env-file $envFile -p $testProject @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Test Compose command failed: $($Arguments -join ' ')" }
}
function Get-ReadyStatus([int]$Port) {
    return (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec 10).status
}

try {
    $rootBinding = docker compose --project-directory $projectRoot -f (Join-Path $projectRoot 'compose.yaml') port api 8000
    if ($LASTEXITCODE -ne 0) { throw 'Cannot find root API binding.' }
    $rootPort = [int]($rootBinding.Split(':')[-1])
    $rootStatus = Get-ReadyStatus $rootPort
    if ($rootStatus -ne 'ready') { throw 'Root stack is not ready before isolation verification.' }
    $webPort = Get-FreePort
    do { $apiPort = Get-FreePort } while ($apiPort -eq $webPort)
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $lines = @(
        "COMPOSE_PROJECT_NAME=$testProject", "API_IMAGE_TAG=$testTag", "WEB_PORT=$webPort", "API_PORT=$apiPort",
        ('ADMIN_DB_PASSWORD=' + (New-Secret)), ('MIGRATOR_DB_PASSWORD=' + (New-Secret)), ('APP_DB_PASSWORD=' + (New-Secret))
    )
    [System.IO.File]::WriteAllLines($envFile, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Push-Location $projectRoot
    try {
        Invoke-Compose @('build', 'api', 'web')
        $started = $true
        Invoke-Compose @('up', '-d', '--wait', '--wait-timeout', '180')
    } finally { Pop-Location }
    if ((Get-ReadyStatus $apiPort) -ne 'ready') { throw 'Temporary API did not become ready.' }
    $testIds = @(Invoke-Compose @('ps', '-q', 'db', 'api', 'web'))
    if ($LASTEXITCODE -ne 0 -or $testIds.Count -ne 3 -or $testIds -contains '') { throw 'Temporary stack does not have exactly db/api/web containers.' }
    $rootIds = @(docker compose --project-directory $projectRoot -f (Join-Path $projectRoot 'compose.yaml') ps -q db api web)
    if ($LASTEXITCODE -ne 0 -or (@($rootIds | Where-Object { $testIds -contains $_ }).Count -ne 0)) { throw 'Root and temporary stacks share a container.' }
    $testVolume = "$testProject`_postgres_data"
    $volumeInfo = docker volume inspect $testVolume | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $volumeInfo[0].Labels.'com.docker.compose.project' -ne $testProject) { throw 'Temporary volume does not belong to the temporary project.' }
    $testObjects = docker inspect @testIds | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect temporary resources.' }
    $rootObjects = docker inspect @rootIds | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect root resources.' }
    $testNetworks = @($testObjects | ForEach-Object { $_.NetworkSettings.Networks.PSObject.Properties.Name } | Sort-Object -Unique)
    $rootNetworks = @($rootObjects | ForEach-Object { $_.NetworkSettings.Networks.PSObject.Properties.Name } | Sort-Object -Unique)
    if (@($testNetworks | Where-Object { $rootNetworks -contains $_ }).Count) { throw 'Stacks share a network.' }
    $testVolumes = @($testObjects | ForEach-Object { $_.Mounts } | Where-Object { $_.Type -eq 'volume' } | ForEach-Object { $_.Name })
    $rootVolumes = @($rootObjects | ForEach-Object { $_.Mounts } | Where-Object { $_.Type -eq 'volume' } | ForEach-Object { $_.Name })
    if (@($testVolumes | Where-Object { $rootVolumes -contains $_ }).Count) { throw 'Stacks share a volume.' }
    $testApi = $testObjects | Where-Object { $_.Config.Labels.'com.docker.compose.service' -eq 'api' }
    if ($testApi.Config.Image -ne "sic-student-advisor-api:$testTag") { throw 'Temporary API tag mismatch.' }
    # Inspect output remains in memory; never print container environments.
    Write-Host "[OK] Independent temporary project, containers, ports, and volume verified: $testProject" -ForegroundColor Green
    Push-Location $projectRoot
    try { Invoke-Compose @('down'); $started = $false } finally { Pop-Location }
    if ((Get-ReadyStatus $rootPort) -ne 'ready') { throw 'Root stack became unhealthy after temporary stack cleanup.' }
    Write-Host "PASS: temporary containers/networks removed; root ready; test volume retained: $testVolume" -ForegroundColor Green
} finally {
    Write-Host "Test configuration retained locally (contains secrets, do not share): $testRoot"
    if ($started) { Write-Warning "Temporary stack remains for inspection: $testProject" }
}
