<#
.SYNOPSIS
    Creates a consistent, point-in-time backup of the PostgreSQL database.
.PARAMETER OutFile
    The target path for the backup file. Defaults to artifacts/backups/student_advisor_<timestamp>.dump.
#>
[CmdletBinding()]
param(
    [string]$OutFile = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    if (-not $OutFile) {
        $backupDir = Join-Path $projectRoot "artifacts\backups"
        if (-not (Test-Path $backupDir)) {
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        }
        $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $OutFile = Join-Path $backupDir "student_advisor_$timestamp.dump"
    } else {
        $parentDir = Split-Path -Parent $OutFile
        if ($parentDir -and (-not (Test-Path $parentDir))) {
            New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
        }
    }

    if (Test-Path -LiteralPath $OutFile) { throw 'Backup exists; choose a new output filename. Never overwrite a backup.' }
    $dbContainer = (docker compose ps -q db).Trim()
    if (-not $dbContainer) {
        throw "Database service 'db' is not running. Start services with ops/Start-Local.ps1 first."
    }

    Write-Host "Creating database backup from container $dbContainer..."
    $tempName = '/tmp/advisor-backup-' + [Guid]::NewGuid().ToString('N') + '.dump'
    docker compose exec -T db pg_dump -U advisor_admin -d student_advisor -Fc -f $tempName
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

    docker cp "${dbContainer}:$tempName" "$OutFile"
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed with exit code $LASTEXITCODE" }

    # Keep the temporary copy until the owner verifies the backup. No volume deletion.

    $fileInfo = Get-Item $OutFile
    Write-Host "SUCCESS: Backup created at $($fileInfo.FullName) ($($fileInfo.Length) bytes)"
} finally {
    Pop-Location
}
