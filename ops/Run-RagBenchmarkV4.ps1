[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Image,
    [Parameter(Mandatory=$true)][string]$SourceCommit,
    [Parameter(Mandatory=$true)][string]$SourceArchiveSha256,
    [Parameter(Mandatory=$true)][ValidateSet('dev','test')][string]$Split,
    [Parameter(Mandatory=$true)][string]$InputDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$DisposableChromaDirectory,
    [Parameter(Mandatory=$true)][string]$DockerNetwork,
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [string]$DatasetName = 'questions_v4_reviewed.jsonl',
    [string]$ChunksFileName = 'utt_corpus_chunks.json',
    [string]$RuntimeBindingName = 'runtime_binding.json',
    [string]$GenerationApprovalName = 'generation_approval.json',
    [string]$ReviewLedgerName = 'review_ledger.json',
    [string]$FreezeApprovalName = 'freeze_approval.json',
    [string]$ReleaseReceiptName = 'release_v2_receipt.json',
    [string]$ReleaseManifestName = 'release_v2_manifest.json'
)

$ErrorActionPreference = 'Stop'
$immutableImage = '^[^@\s]+@sha256:[a-f0-9]{64}$'
if ($Image -notmatch $immutableImage) { throw 'Use an immutable repository@sha256:<64> image reference; tags and bare image IDs are forbidden.' }
if ($SourceCommit -notmatch '^[a-f0-9]{40}$') { throw 'SourceCommit must be a full 40-character Git commit.' }
if ($SourceArchiveSha256 -notmatch '^[a-f0-9]{64}$') { throw 'SourceArchiveSha256 must be SHA-256.' }

$input = (Resolve-Path -LiteralPath $InputDirectory).Path
$envPath = (Resolve-Path -LiteralPath $EnvFile).Path
$chroma = (Resolve-Path -LiteralPath $DisposableChromaDirectory).Path
if (-not (Test-Path -LiteralPath (Join-Path $chroma '.benchmark-disposable'))) {
    throw 'DisposableChromaDirectory must be a copied index containing .benchmark-disposable; active index is forbidden.'
}
if (Test-Path -LiteralPath $OutputDirectory) {
    if (@(Get-ChildItem -LiteralPath $OutputDirectory -Force).Count -ne 0) { throw 'OutputDirectory must be new or empty.' }
} else {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path

$required = @($DatasetName, $ChunksFileName, $RuntimeBindingName, $GenerationApprovalName)
if ($Split -eq 'test') { $required += @($ReviewLedgerName, $FreezeApprovalName, $ReleaseReceiptName, $ReleaseManifestName) }
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $input $name) -PathType Leaf)) { throw "Missing benchmark input: $name" }
}

$args = @(
    'run','--rm','--network',$DockerNetwork,
    '--env-file',$envPath,
    '-e',"RAG_SOURCE_COMMIT=$SourceCommit",
    '-e',"RAG_SOURCE_ARCHIVE_SHA256=$SourceArchiveSha256",
    '-e',"RAG_BENCHMARK_IMAGE_DIGEST=$($Image.Split('@')[1])",
    '-e','RAG_SOURCE_MOUNTED=0',
    '-e','RAG_DIRECTORY=/vectorstore',
    '-e','HF_HOME=/vectorstore/hf',
    '-e','HF_HUB_OFFLINE=1',
    '--mount',"type=bind,source=$input,target=/benchmark/input,readonly",
    '--mount',"type=bind,source=$output,target=/benchmark/output",
    '--mount',"type=bind,source=$chroma,target=/vectorstore",
    $Image,'python','-m','app.rag_benchmark_adapter',
    '--dataset',"/benchmark/input/$DatasetName",
    '--chunks-file',"/benchmark/input/$ChunksFileName",
    '--split',$Split,
    '--output-dir','/benchmark/output',
    '--runtime-binding',"/benchmark/input/$RuntimeBindingName",
    '--generation-approval',"/benchmark/input/$GenerationApprovalName"
)
if ($Split -eq 'test') {
    $args += @(
        '--review-ledger',"/benchmark/input/$ReviewLedgerName",
        '--approval',"/benchmark/input/$FreezeApprovalName",
        '--release-receipt',"/benchmark/input/$ReleaseReceiptName",
        '--release-manifest',"/benchmark/input/$ReleaseManifestName"
    )
}
& docker @args
if ($LASTEXITCODE -ne 0) { throw "RAG Benchmark V4 container failed with exit code $LASTEXITCODE" }
