<# Stage 8 disposable contract, integration and real-browser verification. #>
[CmdletBinding()]
param(
    [int]$TimeoutSec = 180,
    [string]$UseApiImage = '',
    [string]$UseWebImage = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runId = 's8-' + (Get-Date -Format 'yyyyMMddHHmmss')
$project = "sic-stage8-$runId"
$apiImage = if ($UseApiImage) { $UseApiImage } else { "sic-student-advisor-api:$runId" }
$webImage = if ($UseWebImage) { $UseWebImage } else { "sic-student-advisor-web:$runId" }
$evidence = Join-Path $root "artifacts/stage8/$runId"
$envFile = Join-Path ([System.IO.Path]::GetTempPath()) "advisor-$runId.env"
$compose = Join-Path $root 'ops/stage8.compose.yaml'

function New-Secret([int]$Bytes = 32) {
    $data = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    # Hex avoids platform-specific .env parsing edge cases around Base64
    # padding and punctuation while retaining the full random entropy.
    try { $rng.GetBytes($data); [Convert]::ToHexString($data).ToLowerInvariant() }
    finally { $rng.Dispose() }
}
function Get-FreePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}
function Write-Meta([string]$Text) {
    $line = "$(Get-Date -Format o) $Text"
    $line | Tee-Object -FilePath (Join-Path $evidence 'stage8-meta.log') -Append
}
function Invoke-Compose([string[]]$Arguments) {
    & docker compose --project-name $project -f $compose --env-file $envFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed (exit $LASTEXITCODE): $($Arguments -join ' ')" }
}

$adminPass = New-Secret
$migratorPass = New-Secret
$appPass = New-Secret
$jwtSecret = New-Secret 48
$demoPass = New-Secret 24
$webPort = Get-FreePort
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

@(
    "STAGE8_API_IMAGE=$apiImage"
    "STAGE8_WEB_IMAGE=$webImage"
    "STAGE8_WEB_PORT=$webPort"
    "STAGE8_ADMIN_PASSWORD=$adminPass"
    "STAGE8_MIGRATOR_PASSWORD=$migratorPass"
    "STAGE8_APP_PASSWORD=$appPass"
    "STAGE8_JWT_SECRET=$jwtSecret"
) | Set-Content -LiteralPath $envFile -Encoding ASCII

Push-Location $root
try {
    Write-Meta "START project=$project url=http://127.0.0.1:$webPort"
    node frontend/tests/api-contracts.cjs backend/tests/openapi.snapshot.json *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'contract.log')
    if ($LASTEXITCODE -ne 0) { throw 'Frontend/OpenAPI contract gate failed' }

    if (-not $UseApiImage) {
        Write-Meta "Building isolated API image $apiImage"
        & docker build -t $apiImage -f backend/Dockerfile . *>&1 |
            Tee-Object -FilePath (Join-Path $evidence 'api-build.log')
        if ($LASTEXITCODE -ne 0) { throw 'API image build failed' }
    }
    if (-not $UseWebImage) {
        Write-Meta "Building isolated web image $webImage"
        & docker build -t $webImage -f frontend/Dockerfile frontend *>&1 |
            Tee-Object -FilePath (Join-Path $evidence 'web-build.log')
        if ($LASTEXITCODE -ne 0) { throw 'Web image build failed' }
    }

    # Start in deterministic phases so a migration failure is streamed into
    # the release evidence instead of being hidden behind `compose up --wait`.
    Invoke-Compose @('up', '-d', '--wait', '--wait-timeout', "$TimeoutSec", 'db') *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'compose-db.log')
    Invoke-Compose @('up', '--no-deps', '--abort-on-container-exit', '--exit-code-from', 'migrate', 'migrate') *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'migration.log')
    Invoke-Compose @('up', '-d', '--wait', '--wait-timeout', "$TimeoutSec", 'api', 'web') *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'compose-app.log')
    Write-Meta 'Disposable stack healthy'

    & docker compose --project-name $project -f $compose --env-file $envFile exec -T `
        -e PYTHONPATH=/app api python tests/integration_application.py *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'integration.log')
    if ($LASTEXITCODE -ne 0) { throw 'Application integration gate failed' }

    & docker compose --project-name $project -f $compose --env-file $envFile exec -T `
        -e PYTHONPATH=/app api python -m unittest discover -s tests -p 'test_*.py' -v *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'backend-unittest.log')
    if ($LASTEXITCODE -ne 0) { throw 'Backend unit and DB lifecycle gate failed' }

    $demoPass | & docker compose --project-name $project -f $compose --env-file $envFile exec -T api `
        python -c "import sys; from app.seed import seed; from app.security import password_hash; from app.store import transaction,run; p=sys.stdin.read().strip(); seed(p); c=transaction(); db=c.__enter__(); run(db, 'UPDATE app.users SET password_hash=:h,auth_version=auth_version+1 WHERE email IN (:s1,:s2,:a,:d,:u)', h=password_hash(p), s1='student@demo.local', s2='student2@demo.local', a='advisor@demo.local', d='admin@demo.local', u='unlinked@demo.local'); c.__exit__(None,None,None); print('Stage 8 demo seed complete')" *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'seed.log')
    if ($LASTEXITCODE -ne 0) { throw 'Disposable demo seed failed' }

    $demoPass | node frontend/tests/e2e_stage8.cjs "http://127.0.0.1:$webPort" $evidence *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'browser-e2e.log')
    if ($LASTEXITCODE -ne 0) { throw 'Stage 8 browser E2E failed' }

    Write-Meta 'VERDICT: PASS — contract, integration, backend unit/lifecycle and browser E2E'
} catch {
    Write-Meta "VERDICT: FAIL — $($_.Exception.Message)"
    throw
} finally {
    Write-Meta 'Cleanup disposable stack'
    & docker compose --project-name $project -f $compose --env-file $envFile down --volumes --remove-orphans *>&1 |
        Tee-Object -FilePath (Join-Path $evidence 'cleanup.log')
    Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
    $remaining = & docker ps -a --filter "label=com.docker.compose.project=$project" -q
    $remainingVolumes = & docker volume ls --filter "label=com.docker.compose.project=$project" -q
    if ($remaining -or $remainingVolumes) {
        Write-Meta 'Cleanup verification FAILED: disposable resources remain'
        throw 'Stage 8 cleanup verification failed'
    }
    Write-Meta 'Cleanup verified; live project untouched'
    $adminPass = $migratorPass = $appPass = $jwtSecret = $demoPass = $null
    Pop-Location
}
