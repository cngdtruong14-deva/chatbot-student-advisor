<#
.SYNOPSIS
    Creates a synchronized, consistent point-in-time snapshot of both the PostgreSQL
    database and Chroma vector store under a single backup ID (Finding A10, Comment 14).
.PARAMETER BackupId
    Custom identifier for the backup snapshot. Defaults to consistent_backup_<yyyyMMdd_HHmmss>.
.PARAMETER OutDir
    Target directory for the backup artifacts. Defaults to artifacts/backups/<BackupId>.
#>
[CmdletBinding()]
param(
    [string]$BackupId = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    if (-not $BackupId) {
        $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $BackupId = "consistent_backup_$timestamp"
    }

    if (-not $OutDir) {
        $OutDir = Join-Path $projectRoot "artifacts\backups\$BackupId"
    }

    if (-not (Test-Path $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    }

    Write-Host "`n======================================================="
    Write-Host "=== CREATING SYSTEM-CONSISTENT SNAPSHOT: $BackupId ==="
    Write-Host "=======================================================`n"

    $dbContainer = (docker compose ps -q db).Trim()
    $apiContainer = (docker compose ps -q api).Trim()
    if (-not $dbContainer -or -not $apiContainer) {
        throw "Containers 'db' and 'api' must be running. Start stack first."
    }

    # 1 & 2. Quiesce verification and count consistency check
    Write-Host "Step 1 & 2: Checking quiesce and metadata count consistency..."
    $countsJson = docker compose exec -T api python /artifacts/backup_counts.py
    $counts = $countsJson | ConvertFrom-Json
    if ($counts.running_ingests -gt 0) {
        throw "Ingestion worker is actively running ($($counts.running_ingests) in progress). Quiesce required."
    }
    Write-Host "  Quiesce verified: 0 running ingests."
    Write-Host "  DB Total Chunks:       $($counts.db_total_chunks)"
    Write-Host "  DB Active UTT Chunks:  $($counts.db_utt_active)"
    Write-Host "  Chroma Vector Count:   $($counts.chroma_vector_count)"

    $countsMatch = ($counts.db_utt_active -eq $counts.chroma_vector_count)
    if (-not $countsMatch) {
        Write-Warning "Metadata count mismatch! DB Active UTT Chunks ($($counts.db_utt_active)) != Chroma Vectors ($($counts.chroma_vector_count))"
    } else {
        Write-Host "Counts verified: DB active chunks and Chroma vectors match exactly ($($counts.db_utt_active))."
    }

    # 3. Dump PostgreSQL database atomically
    Write-Host "Step 3: Creating atomic PostgreSQL dump..."
    $tempDump = "/tmp/advisor-backup-$BackupId.dump"
    docker compose exec -T db pg_dump -U advisor_admin -d student_advisor -Fc -f $tempDump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

    $targetDumpPath = Join-Path $OutDir "database.dump"
    docker cp "${dbContainer}:$tempDump" "$targetDumpPath"
    if ($LASTEXITCODE -ne 0) { throw "Failed to copy dump from db container" }
    docker compose exec -T db rm -f $tempDump

    $dumpHash = (Get-FileHash -Path $targetDumpPath -Algorithm SHA256).Hash.ToLower()
    Write-Host "  Database dump created: $targetDumpPath (SHA256: $dumpHash)"

    # 4. Snapshot Chroma vector store using tar inside container (avoids host file lock issues)
    Write-Host "Step 4: Snapshotting Chroma vector store..."
    $tempArchiveName = "chroma_snapshot_$BackupId.tar.gz"
    docker compose exec -T api tar -czf "/vectorstore/$tempArchiveName" -C /vectorstore chroma
    if ($LASTEXITCODE -ne 0) { throw "Failed to archive chroma vectorstore inside container" }

    $targetChromaArchive = Join-Path $OutDir "chroma_snapshot.tar.gz"
    $localTempArchive = Join-Path $projectRoot "vectorstore\$tempArchiveName"
    Move-Item -Path $localTempArchive -Destination $targetChromaArchive -Force

    $chromaHash = (Get-FileHash -Path $targetChromaArchive -Algorithm SHA256).Hash.ToLower()
    Write-Host "  Chroma snapshot created: $targetChromaArchive (SHA256: $chromaHash)"

    # 5. Write Manifest Receipt
    Write-Host "Step 5: Writing consistent backup manifest..."
    $manifest = @{
        backup_id = $BackupId
        created_at = (Get-Date).ToString('o')
        counts_match = $countsMatch
        db_total_chunks = $counts.db_total_chunks
        db_utt_active_chunks = $counts.db_utt_active
        chroma_vector_count = $counts.chroma_vector_count
        database_dump = @{
            file = "database.dump"
            sha256 = $dumpHash
            size_bytes = (Get-Item $targetDumpPath).Length
        }
        chroma_snapshot = @{
            file = "chroma_snapshot.tar.gz"
            sha256 = $chromaHash
            size_bytes = (Get-Item $targetChromaArchive).Length
        }
    }
    $manifestPath = Join-Path $OutDir "backup_manifest.json"
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding utf8

    Write-Host "`nSUCCESS: System-consistent backup completed at $OutDir"
    Write-Host "Manifest: $manifestPath`n"
} finally {
    Pop-Location
}
