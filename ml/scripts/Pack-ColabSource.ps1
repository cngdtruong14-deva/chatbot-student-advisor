param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$destination = [IO.Path]::GetFullPath($OutputPath)
if ([IO.Path]::GetExtension($destination) -ne '.zip') { throw 'Output must be a ZIP.' }
if (Test-Path -LiteralPath $destination) { throw 'Source bundle exists; use a new name instead of overwriting.' }
# Only the files that enter the Colab archive need be clean.  This preserves
# isolation from unrelated in-progress backend/frontend work in the repository.
$dirty = git -C $repoRoot status --porcelain -- ml packages/advisor_core contracts
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Refuse non-reproducible source bundle: commit the exact ML/core/contracts source first.' }
$commit = (git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[a-f0-9]{40}$') { throw 'Cannot resolve an exact Git commit.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$manifestFiles = @{}
$archive = [IO.Compression.ZipFile]::Open($destination, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($folder in @('ml','packages/advisor_core/src','contracts')) {
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repoRoot $folder) -File -Recurse) {
            $relative = $file.FullName.Substring($repoRoot.Length+1).Replace('\','/')
            if ($relative -match '(^|/)(__pycache__|raw|processed|runs|export|work|chroma|node_modules|build)(/|$)') { continue }
            if ($file.Extension -notin @('.py','.ipynb','.json','.jsonl','.md','.txt','.ps1')) { continue }
            if ($file.Name -match '(approval\.json|reviewed\.jsonl)$') { continue }
            if ($relative -match '(^|/)\.env') { throw 'Unexpected secret path' }
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$file.FullName,$relative) | Out-Null
            $manifestFiles[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $packagePath = Join-Path $repoRoot 'packages/advisor_core/pyproject.toml'
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$packagePath,'packages/advisor_core/pyproject.toml') | Out-Null
    $manifestFiles['packages/advisor_core/pyproject.toml'] = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $entry=$archive.CreateEntry('SOURCE_MANIFEST.json')
    $writer=New-Object IO.StreamWriter($entry.Open(), (New-Object Text.UTF8Encoding($false)))
    try { $writer.Write((@{source_kind='clean_git_commit_source_archive';source_commit=$commit;files=$manifestFiles;contract_version='1.0.0'} | ConvertTo-Json -Depth 5)) } finally { $writer.Dispose() }
} finally { $archive.Dispose() }
Write-Host "Source-only bundle: $destination"
Get-FileHash -LiteralPath $destination -Algorithm SHA256 | Select-Object Algorithm,Hash
