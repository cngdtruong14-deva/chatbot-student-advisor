<#
.SYNOPSIS
Creates, lists, and safely removes the App and ML worktrees.

.DESCRIPTION
Removal is deliberately conservative: it refuses any modified, staged, untracked,
or ignored file. This script never force-removes a worktree.
#>
[CmdletBinding()]
param (
    [ValidateSet('App', 'ML', 'All')]
    [string]$Role = 'All',
    [switch]$List,
    [switch]$Remove,
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd([char[]]@('\', '/'))

function Get-NormalizedPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path).TrimEnd([char[]]@('\', '/'))
}

function Invoke-Git {
    param([string[]]$Arguments, [string]$FailureMessage)
    & git -C $projectRoot @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$FailureMessage (git exit $LASTEXITCODE)" }
}

function Get-WorktreeRecord([string]$Path) {
    $target = Get-NormalizedPath $Path
    $lines = @(git -C $projectRoot worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list registered Git worktrees.' }
    $record = @{}
    foreach ($line in ($lines + '')) {
        if ($line -eq '') {
            if ($record.ContainsKey('Path') -and $record.Path -ieq $target) { return $record }
            $record = @{}
        } elseif ($line.StartsWith('worktree ')) {
            $record.Path = Get-NormalizedPath $line.Substring(9)
        } elseif ($line.StartsWith('branch ')) {
            $record.Branch = $line.Substring(7).Replace('refs/heads/', '')
        }
    }
    return $null
}

function Assert-ExpectedWorktree([string]$Path, [string]$ExpectedBranch) {
    $target = Get-NormalizedPath $Path
    if ($target -ieq $projectRoot) { throw 'Refusing to operate on the primary worktree.' }
    $record = Get-WorktreeRecord $target
    if ($null -eq $record) { throw "Target is not a registered worktree: $target" }
    if (-not $record.ContainsKey('Branch') -or $record.Branch -ne $ExpectedBranch) {
        throw "Registered worktree branch is '$($record.Branch)', expected '$ExpectedBranch'."
    }
    $primaryLines = @(git -C $projectRoot worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the primary worktree.' }
    $primaryPath = ($primaryLines | Where-Object { $_.StartsWith('worktree ') } | Select-Object -First 1).Substring(9)
    if ((Get-NormalizedPath $primaryPath) -ieq $target) { throw 'Refusing to operate on the primary worktree.' }
    if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a reparse-point target.' }
    $expectedCommon = git -C $projectRoot rev-parse --path-format=absolute --git-common-dir
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve repository common directory.' }
    $targetCommon = git -C $target rev-parse --path-format=absolute --git-common-dir
    if ($LASTEXITCODE -ne 0 -or (Get-NormalizedPath $targetCommon) -ine (Get-NormalizedPath $expectedCommon)) {
        throw "Target worktree does not belong to this repository: $target"
    }
    $currentBranch = git -C $target branch --show-current
    if ($LASTEXITCODE -ne 0 -or $currentBranch -ne $ExpectedBranch) {
        throw "Target checkout branch is '$currentBranch', expected '$ExpectedBranch'."
    }
    return $target
}

function Test-WorktreeClean([string]$Path) {
    $changed = @(git -C $Path status --porcelain=v1)
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect Git status for $Path" }
    $changed = @($changed | Where-Object { $_.Trim() })
    $ignored = @(git -C $Path status --porcelain=v1 --ignored)
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect ignored files for $Path" }
    $ignored = @($ignored | Where-Object { $_.StartsWith('!! ') })
    if ($changed.Count -gt 0 -or $ignored.Count -gt 0) {
        Write-Host '[BLOCKED] Worktree is not empty of local state; refusing removal.' -ForegroundColor Red
        if ($changed.Count) { Write-Host ('Changed/untracked: ' + ($changed -join '; ')) -ForegroundColor Yellow }
        if ($ignored.Count) { Write-Host ('Ignored files: ' + ($ignored -join '; ')) -ForegroundColor Yellow }
        return $false
    }
    return $true
}

function Ensure-Branch([string]$Branch) {
    & git -C $projectRoot show-ref --verify --quiet "refs/heads/$Branch"
    if ($LASTEXITCODE -eq 0) { return }
    if ($LASTEXITCODE -ne 1) { throw 'Cannot inspect local branch references.' }
    & git -C $projectRoot ls-remote --exit-code --heads origin "refs/heads/$Branch" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Branch '$Branch' does not exist locally or at origin." }
    Invoke-Git @('fetch', '--no-tags', 'origin', "refs/heads/${Branch}:refs/remotes/origin/$Branch") "Cannot fetch origin/$Branch"
    Invoke-Git @('branch', '--track', $Branch, "origin/$Branch") "Cannot create tracking branch $Branch"
}

$baseDir = if ($TargetDir) { Get-NormalizedPath $TargetDir } else { Split-Path -Parent $projectRoot }
$worktrees = @()
if ($Role -in @('App', 'All')) { $worktrees += @{ Name = 'App'; Branch = 'feature/app'; Path = (Join-Path $baseDir 'chatbot-student-advisor-app') } }
if ($Role -in @('ML', 'All')) { $worktrees += @{ Name = 'ML'; Branch = 'feature/ml'; Path = (Join-Path $baseDir 'chatbot-student-advisor-ml') } }

if ($List) {
    Invoke-Git @('worktree', 'list') 'Cannot list Git worktrees'
    exit 0
}

foreach ($item in $worktrees) {
    $path = Get-NormalizedPath $item.Path
    if ($Remove) {
        if (-not (Test-Path -LiteralPath $path)) { Write-Host "[MISSING] $($item.Name) worktree is absent: $path"; continue }
        $safePath = Assert-ExpectedWorktree $path $item.Branch
        if (-not (Test-WorktreeClean $safePath)) { throw "Refused to remove non-clean worktree: $safePath" }
        Invoke-Git @('worktree', 'remove', '--', $safePath) "Cannot remove clean worktree $safePath"
        Write-Host "[OK] Removed clean $($item.Name) worktree: $safePath" -ForegroundColor Green
        continue
    }

    if (Test-Path -LiteralPath $path) {
        $null = Assert-ExpectedWorktree $path $item.Branch
        Write-Host "[EXISTS] $($item.Name) worktree already registered: $path" -ForegroundColor Yellow
        continue
    }
    Ensure-Branch $item.Branch
    Invoke-Git @('worktree', 'add', '--', $path, $item.Branch) "Cannot create $($item.Name) worktree"
    $null = Assert-ExpectedWorktree $path $item.Branch
    Write-Host "[OK] Created $($item.Name) worktree: $path" -ForegroundColor Green
}
