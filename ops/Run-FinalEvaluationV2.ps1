<#
.SYNOPSIS
    Runs Benchmark Final Evaluation v2 with freeze manifest verification and token lifecycle (Comment 16).
.PARAMETER Manifest
    Path to freeze manifest.
.PARAMETER Dataset
    Path to benchmark dataset.
#>
[CmdletBinding()]
param(
    [string]$Manifest = "/artifacts/freeze_v2/freeze_manifest_v2.json",
    [string]$Dataset = "/artifacts/benchmark_v2/benchmark_v2_template.jsonl"
)

$ErrorActionPreference = 'Stop'
$message = @'
QUARANTINED: This legacy V2 runner scored reference answers rather than actual
RAG/LLM output. Its artifacts are diagnostic only. Do not reuse or overwrite
them. Use the Stage 6 RAG benchmark runner after its reviewed dataset, freeze
approval, corpus-release identity, and one-shot output directory are ready.
'@
throw $message
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    Write-Host "`n======================================================="
    Write-Host "=== RUNNING BENCHMARK FINAL EVALUATION V2           ==="
    Write-Host "=======================================================`n"

    $apiContainer = (docker compose ps -q api).Trim()
    if (-not $apiContainer) { throw "API container not running." }

    docker compose exec -T api python -m app.execute_final_evaluation_v2 `
        --manifest "$Manifest" `
        --dataset "$Dataset" `
        --output-dir "/vectorstore/freeze_v2"

    if ($LASTEXITCODE -ne 0) { throw "Evaluation runner failed with exit code $LASTEXITCODE" }

    # Sync lifecycle tokens and results back to host artifacts/freeze_v2/
    $hostTargetDir = Join-Path $projectRoot "artifacts\freeze_v2"
    if (-not (Test-Path $hostTargetDir)) { New-Item -ItemType Directory -Path $hostTargetDir -Force | Out-Null }
    Copy-Item -Path "vectorstore\freeze_v2\*" -Destination $hostTargetDir -Force

    Write-Host "`nSUCCESS: Tokens and results synced to artifacts/freeze_v2/`n"
} finally {
    Pop-Location
}
