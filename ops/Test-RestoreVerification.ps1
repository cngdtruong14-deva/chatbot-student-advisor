<#
.SYNOPSIS
    Verifies restoration of a consistent backup by restoring into isolated targets
    and executing 3 live functional queries (Finding A10, Comment 15).
.PARAMETER BackupDir
    Path to the backup directory containing backup_manifest.json, database.dump, and chroma_snapshot.zip.
.PARAMETER TestDbName
    Name of the temporary isolated test database (defaults to student_advisor_restore_test).
.PARAMETER TestChromaDir
    Temporary directory for extracting and testing the restored Chroma index.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BackupDir,
    [string]$TestDbName = "student_advisor_restore_test",
    [string]$TestChromaDir = "artifacts\restore_test\chroma"
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    Write-Host "`n======================================================="
    Write-Host "=== STARTING RESTORE VERIFICATION TEST              ==="
    Write-Host "=======================================================`n"

    $manifestPath = Join-Path $BackupDir "backup_manifest.json"
    if (-not (Test-Path $manifestPath)) {
        throw "Manifest not found at $manifestPath"
    }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Write-Host "Backup ID: $($manifest.backup_id) (Created: $($manifest.created_at))"

    # Step 1: Verify file checksums
    Write-Host "`nStep 1: Verifying backup archive checksums..."
    $dumpFile = Join-Path $BackupDir $manifest.database_dump.file
    $chromaZip = Join-Path $BackupDir $manifest.chroma_snapshot.file

    $calcDumpHash = (Get-FileHash -Path $dumpFile -Algorithm SHA256).Hash.ToLower()
    if ($calcDumpHash -ne $manifest.database_dump.sha256) {
        throw "Database dump SHA256 mismatch! Expected $($manifest.database_dump.sha256), got $calcDumpHash"
    }
    Write-Host "  Database dump checksum OK ($calcDumpHash)"

    $calcChromaHash = (Get-FileHash -Path $chromaZip -Algorithm SHA256).Hash.ToLower()
    if ($calcChromaHash -ne $manifest.chroma_snapshot.sha256) {
        throw "Chroma snapshot SHA256 mismatch! Expected $($manifest.chroma_snapshot.sha256), got $calcChromaHash"
    }
    Write-Host "  Chroma snapshot checksum OK ($calcChromaHash)"

    # Step 2: Restore into isolated test database
    Write-Host "`nStep 2: Restoring database into isolated target: $TestDbName..."
    $dbContainer = (docker compose ps -q db).Trim()
    if (-not $dbContainer) { throw "DB container not running" }

    # Drop test DB if previously existed, then create clean empty test DB
    docker compose exec -T db psql -U advisor_admin -d postgres -c "DROP DATABASE IF EXISTS $TestDbName;"
    docker compose exec -T db psql -U advisor_admin -d postgres -c "CREATE DATABASE $TestDbName OWNER advisor_admin;"

    $tempRestoreDump = "/tmp/restore-$([Guid]::NewGuid().ToString('N')).dump"
    docker cp $dumpFile "${dbContainer}:$tempRestoreDump"
    docker compose exec -T db pg_restore -U advisor_admin -d $TestDbName --single-transaction --exit-on-error $tempRestoreDump
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
    docker compose exec -T db rm -f $tempRestoreDump
    Write-Host "  Database restored successfully into $TestDbName."

    # Step 3: Extract Chroma snapshot into isolated directory in writable vectorstore
    Write-Host "`nStep 3: Extracting Chroma snapshot into isolated directory..."
    $restoreTestBase = Join-Path $projectRoot "vectorstore\restore_test"
    $fullChromaDir = Join-Path $restoreTestBase "chroma"
    if (Test-Path $fullChromaDir) { Remove-Item -Recurse -Force $fullChromaDir }
    if (-not (Test-Path $restoreTestBase)) { New-Item -ItemType Directory -Path $restoreTestBase -Force | Out-Null }
    tar -xzf $chromaZip -C $restoreTestBase
    Write-Host "  Chroma snapshot extracted to $fullChromaDir."

    # Step 4: Execute 3 Live Verification Queries
    Write-Host "`nStep 4: Executing 3 Live Functional Verification Queries against restored data..."
    
    $verifyOut = docker compose exec -T api python /artifacts/restore_test/run_restore_verification.py --db-name $TestDbName --chroma-path /vectorstore/restore_test/chroma
    $verifyResults = $verifyOut | ConvertFrom-Json

    $prevText = if ($verifyResults.query_2_db_citation.chunk_preview) { $verifyResults.query_2_db_citation.chunk_preview.Substring(0, [Math]::Min(50, $verifyResults.query_2_db_citation.chunk_preview.Length)) } else { "N/A" }
    Write-Host "  Query 1 (Chroma Vector Retrieval):  $($verifyResults.query_1_vector_retrieval.status) - Count: $($verifyResults.query_1_vector_retrieval.vector_count), Retrieved: $($verifyResults.query_1_vector_retrieval.retrieved_chunk_id)"
    Write-Host "  Query 2 (DB Citation Text Match):   $($verifyResults.query_2_db_citation.status) - Preview: $prevText..."
    Write-Host "  Query 3 (Student Profile Restore):  $($verifyResults.query_3_student_profile.status) - Code: $($verifyResults.query_3_student_profile.student_code), Email: $($verifyResults.query_3_student_profile.email)"

    $allPassed = ($verifyResults.query_1_vector_retrieval.status -eq 'PASS' -and
                  $verifyResults.query_2_db_citation.status -eq 'PASS' -and
                  $verifyResults.query_3_student_profile.status -eq 'PASS')

    # Step 5: Clean up isolated test resources
    Write-Host "`nStep 5: Cleaning up isolated test resources..."
    docker compose exec -T db psql -U advisor_admin -d postgres -c "DROP DATABASE IF EXISTS $TestDbName;"
    if (Test-Path $restoreTestBase) { Remove-Item -Recurse -Force $restoreTestBase }

    $receipt = @{
        timestamp = (Get-Date).ToString('o')
        backup_verified = $manifest.backup_id
        all_passed = $allPassed
        details = $verifyResults
    }
    $receiptPath = Join-Path $projectRoot "artifacts\restore_test\restore_verification_receipt.json"
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -Path $receiptPath -Encoding utf8

    if (-not $allPassed) {
        throw "Restore verification failed! Check receipt at $receiptPath"
    }

    Write-Host "`nSUCCESS: Restore verification passed all 3 live queries!"
    Write-Host "Receipt: $receiptPath`n"
} finally {
    Pop-Location
}
