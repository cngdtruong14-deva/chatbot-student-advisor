param(
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$ApiImage
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$testName = 'advisor-check-' + (Get-Date -Format 'yyyyMMddHHmmss')
$testNetwork = $testName + '-net'
$names = @('POSTGRES_PASSWORD','POSTGRES_USER','POSTGRES_DB','MIGRATOR_DB_PASSWORD','APP_DB_PASSWORD','DB_HOST','DB_NAME','DB_USER','DB_PASSWORD','JWT_SECRET','APP_ENV','ADVISOR_TEST_DATABASE','ADVISOR_DOCUMENT_DB_TEST','RAG_METHOD','RAG_LLM_ENABLED')
$previous = @{}
foreach ($n in $names) { $previous[$n] = [Environment]::GetEnvironmentVariable($n, 'Process') }
function Checked([string[]]$DockerArgs) {
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Isolated verification failed ($LASTEXITCODE)" }
}
Push-Location $projectRoot
try {
    $env:POSTGRES_PASSWORD = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    $env:MIGRATOR_DB_PASSWORD = [Guid]::NewGuid().ToString('N')
    $env:APP_DB_PASSWORD = [Guid]::NewGuid().ToString('N')
    $env:POSTGRES_USER = 'advisor_admin'; $env:POSTGRES_DB = 'student_advisor'
    $env:DB_HOST = $testName; $env:DB_NAME = 'student_advisor'
    $env:JWT_SECRET = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    $env:ADVISOR_TEST_DATABASE = '1'; $env:ADVISOR_DOCUMENT_DB_TEST = '1'
    $env:APP_ENV = 'test'
    $env:RAG_METHOD = 'keyword'; $env:RAG_LLM_ENABLED = '0'
    Checked @('network','create','--internal',$testNetwork)
    $initScript = Join-Path $projectRoot 'ops/postgres/010-roles.sh'
    Checked @('run','-d','--name',$testName,'--network',$testNetwork,'--env','POSTGRES_PASSWORD','--env','POSTGRES_USER','--env','POSTGRES_DB','--env','MIGRATOR_DB_PASSWORD','--env','APP_DB_PASSWORD','--mount',"type=bind,source=$initScript,target=/docker-entrypoint-initdb.d/010-roles.sh,readonly",'postgres:17-alpine')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker exec $testName pg_isready -h 127.0.0.1 -U advisor_admin -d student_advisor *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Isolated Postgres did not become ready' }
    $common = @('run','--rm','--network',$testNetwork,'--env','DB_HOST','--env','DB_NAME','--env','DB_USER','--env','DB_PASSWORD','--env','JWT_SECRET','--env','APP_ENV','--env','ADVISOR_TEST_DATABASE','--env','ADVISOR_DOCUMENT_DB_TEST','--env','RAG_METHOD','--env','RAG_LLM_ENABLED')
    $env:DB_USER='advisor_migrator'; $env:DB_PASSWORD=$env:MIGRATOR_DB_PASSWORD
    Checked ($common + @($ApiImage,'alembic','upgrade','head'))
    $env:DB_USER='advisor_app'; $env:DB_PASSWORD=$env:APP_DB_PASSWORD
    # Seed/password changes and importer writes happen ONLY in this isolated DB.
    Checked ($common + @($ApiImage,'python','-m','tests.integration_application'))
    Checked ($common + @($ApiImage,'python','-m','unittest','discover','-s','tests','-p','test_*.py','-v'))
    Write-Host "PASS: isolated application tests. Database container retained stopped: $testName"
} finally {
    & docker stop $testName 2>$null | Out-Null
    foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $previous[$n], 'Process') }
    Pop-Location
}
