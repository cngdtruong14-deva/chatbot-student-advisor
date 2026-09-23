<#
.SYNOPSIS
Phase B isolated runtime verification: 4 gates + integration on ephemeral stack.
#>
[CmdletBinding()]
param(
    [int]$TimeoutSec = 180,
    [string]$UseExistingImage = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchDir = Join-Path $projectRoot 'scratch'

$runId = 'pb-' + (Get-Date -Format 'yyyyMMddHHmmss')
$project = "sic-phase-b-$runId"

if ($UseExistingImage) {
    $apiImage = $UseExistingImage
} else {
    $apiImage = "sic-student-advisor-api:phase-b-$runId"
}

$phaseBLog = Join-Path $scratchDir 'phase_b_runtime.log'
$integLog = Join-Path $scratchDir 'phase_b_integration.log'
$metaLog = Join-Path $scratchDir 'phase_b_meta.txt'

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes); return [Convert]::ToBase64String($bytes) }
    finally { $rng.Dispose() }
}

function Write-Meta([string]$msg) {
    $ts = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
    "$ts $msg" | Out-Host
    "$ts $msg" | Add-Content -Path $metaLog -Encoding UTF8
}

$adminPass = New-Secret
$migratorPass = New-Secret
$appPass = New-Secret
$jwtSecret = New-Secret

# Set env vars in process scope for docker compose to inherit
$env:COMPOSE_PROJECT_NAME = $project
$env:PHASE_B_API_IMAGE = $apiImage
$env:PHASE_B_ADMIN_PASSWORD = $adminPass
$env:PHASE_B_MIGRATOR_PASSWORD = $migratorPass
$env:PHASE_B_APP_PASSWORD = $appPass
$env:PHASE_B_JWT_SECRET = $jwtSecret

Write-Meta "=== Phase B Isolated Runtime Start ==="
Write-Meta "Project  : $project"
Write-Meta "Run ID   : $runId"
Write-Meta "API image: $apiImage"
Write-Meta "Log files: $phaseBLog, $integLog, $metaLog"

Push-Location $projectRoot
try {
    if (-not $UseExistingImage) {
        Write-Meta "Building API image..."
        $buildLog = Join-Path $scratchDir 'phase_b_build.log'
        docker build -t $apiImage -f backend/Dockerfile . *> $buildLog
        if ($LASTEXITCODE -ne 0) { 
            Write-Meta "Build failed (exit $LASTEXITCODE), see $buildLog"
            throw "Build failed" 
        }
        Write-Meta "Build OK"
    } else {
        Write-Meta "Using existing image: $apiImage"
    }

    Write-Meta "Starting Phase B stack..."
    $composeLog = Join-Path $scratchDir 'phase_b_compose.log'
    $envFile = Join-Path $scratchDir "phase_b_$runId.env"
    @(
        "PHASE_B_API_IMAGE=$apiImage"
        "PHASE_B_ADMIN_PASSWORD=$adminPass"
        "PHASE_B_MIGRATOR_PASSWORD=$migratorPass"
        "PHASE_B_APP_PASSWORD=$appPass"
        "PHASE_B_JWT_SECRET=$jwtSecret"
    ) | Set-Content $envFile -Encoding ASCII
    docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile up -d --wait --wait-timeout 90 *> $composeLog
    if ($LASTEXITCODE -ne 0) { 
        Write-Meta "Compose up failed (exit $LASTEXITCODE), see $composeLog"
        throw "Compose up failed" 
    }

    Write-Meta "Waiting for DB healthy..."
    $ready = $false
    for ($i = 0; $i -lt $TimeoutSec; $i += 3) {
        $health = & docker compose --project-name $project -f ops/phase-b.compose.yaml ps db --format '{{.State}}' 2>$null
        if ($health -like '*healthy*' -or $health -like '*running*') { $ready = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $ready) { throw "DB not ready after ${TimeoutSec}s" }
    Write-Meta "DB ready"

    Write-Meta "Running Phase B gate tests..."
    "=== Phase B Gate Tests ===" | Set-Content $phaseBLog
    & docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile exec -T api python -m app.phase_b_test 2>&1 | Add-Content $phaseBLog
    $phaseBExit = $LASTEXITCODE
    Write-Meta "phase_b_test exit: $phaseBExit"

    Write-Meta "Resetting disposable stack for integration suite..."
    & docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile down --volumes --remove-orphans > $null 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Disposable stack reset cleanup failed" }
    & docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile up -d --wait --wait-timeout 90 >> $composeLog 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Disposable integration stack startup failed" }
    Write-Meta "Disposable integration stack ready"

    Write-Meta "Running integration application suite..."
    "=== Integration Application ===" | Set-Content $integLog
    & docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile exec -T -e PYTHONPATH=/app api python tests/integration_application.py 2>&1 | Add-Content $integLog
    $integExit = $LASTEXITCODE
    Write-Meta "integration_application exit: $integExit"

    Write-Meta "=== Results ==="
    Write-Meta "phase_b_test    : exit $phaseBExit"
    Write-Meta "integration_app : exit $integExit"
    if ($phaseBExit -eq 0 -and $integExit -eq 0) {
        Write-Meta "VERDICT: ALL PASS"
    } else {
        Write-Meta "VERDICT: FAIL (check logs)"
        throw "Phase B verification failed: gates=$phaseBExit integration=$integExit"
    }

} finally {
    Write-Meta "Cleanup: removing Phase B resources..."
    & docker compose --project-name $project -f ops/phase-b.compose.yaml --env-file $envFile down --volumes --remove-orphans > $null 2>&1
    if (-not $UseExistingImage) { & docker image rm $apiImage 2>&1 > $null }
    Remove-Item $envFile -Force -ErrorAction SilentlyContinue
    # Explicitly verify no orphaned volumes remain for this disposable run
    $orphanedVols = docker volume ls --filter "name=$project" -q
    if ($orphanedVols) {
        docker volume rm $orphanedVols 2>&1 > $null
    }
    # Reset process environment variables
    $env:COMPOSE_PROJECT_NAME = $null
    $env:PHASE_B_API_IMAGE = $null
    $env:PHASE_B_ADMIN_PASSWORD = $null
    $env:PHASE_B_MIGRATOR_PASSWORD = $null
    $env:PHASE_B_APP_PASSWORD = $null
    $env:PHASE_B_JWT_SECRET = $null
    Write-Meta "Cleanup complete. Live stack sic-student-advisor untouched."
    $adminPass = $migratorPass = $appPass = $jwtSecret = $null
    Pop-Location
}


