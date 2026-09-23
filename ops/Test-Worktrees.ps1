<#
.SYNOPSIS
Runs destructive worktree safety cases only inside a uniquely marked temporary Git sandbox.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]@('\', '/'))
$runId = [guid]::NewGuid().ToString('N')
$sandboxRoot = Join-Path $scratchRoot "worktree-safety-$runId"
$markerPath = Join-Path $sandboxRoot 'SANDBOX_MARKER.json'
$success = $false

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Invoke-GitChecked([string]$Directory, [string[]]$Arguments) {
    & git -C $Directory @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git command failed in sandbox: git -C $Directory $($Arguments -join ' ')" }
}
function Invoke-Setup([string]$Runner, [string]$Role, [string]$Target, [switch]$Remove) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Runner 'ops\Setup-Worktrees.ps1'), '-Role', $Role, '-TargetDir', $Target)
    if ($Remove) { $arguments += '-Remove' }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $result = & powershell @arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    return @{ ExitCode = $exitCode; Output = ($result -join "`n") }
}
function Assert-RefusedAndIntact([hashtable]$Result, [string]$Path, [string]$ExpectedHash, [string]$Label) {
    Assert-True ($Result.ExitCode -ne 0) "$Label removal was unexpectedly accepted."
    Assert-True (Test-Path -LiteralPath $Path) "$Label file disappeared after refusal."
    Assert-True ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $ExpectedHash) "$Label file changed after refusal."
    Write-Host "[OK] $Label refusal preserved the file." -ForegroundColor Green
}

try {
    New-Item -ItemType Directory -Path $sandboxRoot -Force | Out-Null
    @{ purpose = 'worktree safety test'; run_id = $runId } | ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8
    $remote = Join-Path $sandboxRoot 'remote.git'
    $seed = Join-Path $sandboxRoot 'seed'
    $runner = Join-Path $sandboxRoot 'runner'
    $target = Join-Path $sandboxRoot 'worktrees'
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    & git init --bare $remote
    if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize bare sandbox remote.' }
    & git --git-dir=$remote symbolic-ref HEAD refs/heads/main
    if ($LASTEXITCODE -ne 0) { throw 'Cannot set sandbox remote HEAD to main.' }
    & git init -b main $seed
    if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize sandbox seed repository.' }
    Invoke-GitChecked $seed @('config', 'user.email', 'phase0@example.invalid')
    Invoke-GitChecked $seed @('config', 'user.name', 'Phase 0 Test')
    Set-Content -LiteralPath (Join-Path $seed 'README.md') -Value 'sandbox baseline' -Encoding UTF8
    Invoke-GitChecked $seed @('add', 'README.md')
    Invoke-GitChecked $seed @('commit', '-m', 'sandbox baseline')
    Invoke-GitChecked $seed @('branch', 'feature/app')
    Invoke-GitChecked $seed @('branch', 'feature/ml')
    Invoke-GitChecked $seed @('remote', 'add', 'origin', $remote)
    Invoke-GitChecked $seed @('push', 'origin', 'main', 'feature/app', 'feature/ml')
    & git clone $remote $runner
    if ($LASTEXITCODE -ne 0) { throw 'Cannot clone sandbox runner.' }
    Invoke-GitChecked $runner @('config', 'user.email', 'phase0@example.invalid')
    Invoke-GitChecked $runner @('config', 'user.name', 'Phase 0 Test')
    New-Item -ItemType Directory -Path (Join-Path $runner 'ops') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'ops\Setup-Worktrees.ps1') -Destination (Join-Path $runner 'ops\Setup-Worktrees.ps1')

    # Local branch already exists.
    Invoke-GitChecked $runner @('branch', '--track', 'feature/app', 'origin/feature/app')
    $app = Invoke-Setup $runner 'App' $target
    Assert-True ($app.ExitCode -eq 0) "Local-branch worktree creation failed: $($app.Output)"
    $appPath = Join-Path $target 'chatbot-student-advisor-app'

    # Exact same path and branch is idempotent.
    $repeat = Invoke-Setup $runner 'App' $target
    Assert-True ($repeat.ExitCode -eq 0 -and $repeat.Output -match '\[EXISTS\]') 'Idempotent worktree creation failed.'

    # An occupied non-worktree path must not be changed.
    $mlPath = Join-Path $target 'chatbot-student-advisor-ml'
    New-Item -ItemType Directory -Path $mlPath | Out-Null
    $conflictFile = Join-Path $mlPath 'keep.txt'
    Set-Content -LiteralPath $conflictFile -Value 'do not touch' -Encoding UTF8
    $conflictHash = (Get-FileHash -LiteralPath $conflictFile -Algorithm SHA256).Hash
    $conflict = Invoke-Setup $runner 'ML' $target
    Assert-True ($conflict.ExitCode -ne 0) 'Non-worktree path conflict was unexpectedly accepted.'
    Assert-True ((Get-FileHash -LiteralPath $conflictFile -Algorithm SHA256).Hash -eq $conflictHash) 'Path-conflict file changed.'
    Remove-Item -LiteralPath $conflictFile -Force
    Remove-Item -LiteralPath $mlPath -Force

    # Remote-only branch fallback.
    $ml = Invoke-Setup $runner 'ML' $target
    Assert-True ($ml.ExitCode -eq 0) "Remote-only branch fallback failed: $($ml.Output)"

    # A registered path on a wrong branch must fail rather than be silently reused.
    Invoke-GitChecked $appPath @('checkout', '-b', 'sandbox/wrong-branch')
    $wrongBranch = Invoke-Setup $runner 'App' $target
    Assert-True ($wrongBranch.ExitCode -ne 0) 'Wrong-branch worktree was unexpectedly accepted.'
    Invoke-GitChecked $appPath @('checkout', 'feature/app')

    # Dirty, staged, untracked, and ignored files must each remain intact.
    $tracked = Join-Path $appPath 'README.md'
    Add-Content -LiteralPath $tracked -Value 'modified'
    $hash = (Get-FileHash -LiteralPath $tracked -Algorithm SHA256).Hash
    Assert-RefusedAndIntact (Invoke-Setup $runner 'App' $target -Remove) $tracked $hash 'Modified file'
    Invoke-GitChecked $appPath @('restore', 'README.md')
    Add-Content -LiteralPath $tracked -Value 'staged'
    Invoke-GitChecked $appPath @('add', 'README.md')
    $hash = (Get-FileHash -LiteralPath $tracked -Algorithm SHA256).Hash
    Assert-RefusedAndIntact (Invoke-Setup $runner 'App' $target -Remove) $tracked $hash 'Staged file'
    Invoke-GitChecked $appPath @('restore', '--staged', 'README.md')
    Invoke-GitChecked $appPath @('restore', 'README.md')
    $untracked = Join-Path $appPath 'untracked.txt'
    Set-Content -LiteralPath $untracked -Value 'untracked' -Encoding UTF8
    $hash = (Get-FileHash -LiteralPath $untracked -Algorithm SHA256).Hash
    Assert-RefusedAndIntact (Invoke-Setup $runner 'App' $target -Remove) $untracked $hash 'Untracked file'
    Remove-Item -LiteralPath $untracked -Force
    Set-Content -LiteralPath (Join-Path $appPath '.gitignore') -Value "*.env`nartifacts/**" -Encoding UTF8
    Invoke-GitChecked $appPath @('add', '.gitignore')
    Invoke-GitChecked $appPath @('commit', '-m', 'sandbox ignores')
    $ignoredRoot = Join-Path $appPath '.env'
    Set-Content -LiteralPath $ignoredRoot -Value 'synthetic' -Encoding UTF8
    $hash = (Get-FileHash -LiteralPath $ignoredRoot -Algorithm SHA256).Hash
    Assert-RefusedAndIntact (Invoke-Setup $runner 'App' $target -Remove) $ignoredRoot $hash 'Ignored root file'
    Remove-Item -LiteralPath $ignoredRoot -Force
    $ignoredNested = Join-Path $appPath 'artifacts\incoming\nested.joblib'
    New-Item -ItemType Directory -Path (Split-Path -Parent $ignoredNested) -Force | Out-Null
    Set-Content -LiteralPath $ignoredNested -Value 'synthetic' -Encoding UTF8
    $hash = (Get-FileHash -LiteralPath $ignoredNested -Algorithm SHA256).Hash
    Assert-RefusedAndIntact (Invoke-Setup $runner 'App' $target -Remove) $ignoredNested $hash 'Ignored nested file'
    Remove-Item -LiteralPath $ignoredNested -Force

    # Clean removals work; a missing local and remote branch fails without a false success.
    $removed = Invoke-Setup $runner 'App' $target -Remove
    Assert-True ($removed.ExitCode -eq 0 -and -not (Test-Path -LiteralPath $appPath)) 'Clean App worktree removal failed.'
    $mlRemoved = Invoke-Setup $runner 'ML' $target -Remove
    Assert-True ($mlRemoved.ExitCode -eq 0) 'Clean ML worktree removal failed.'
    Invoke-GitChecked $runner @('branch', '-d', 'feature/ml')
    Invoke-GitChecked $remote @('update-ref', '-d', 'refs/heads/feature/ml')
    Invoke-GitChecked $runner @('remote', 'prune', 'origin')
    $missingBranch = Invoke-Setup $runner 'ML' $target
    Assert-True ($missingBranch.ExitCode -ne 0 -and $missingBranch.Output -notmatch '\[OK\]') 'Missing branch was unexpectedly accepted.'

    # A Git error in a non-repository must not be reported as success.
    $nonRepo = Join-Path $sandboxRoot 'not-a-repo'
    New-Item -ItemType Directory -Path (Join-Path $nonRepo 'ops') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'ops\Setup-Worktrees.ps1') -Destination (Join-Path $nonRepo 'ops\Setup-Worktrees.ps1')
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $nonRepoResult = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $nonRepo 'ops\Setup-Worktrees.ps1') -List 2>&1
        $nonRepoExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    Assert-True ($nonRepoExit -ne 0 -and (($nonRepoResult -join "`n") -notmatch '\[OK\]')) 'Git-error path was unexpectedly accepted.'
    Write-Host 'PASS: all worktree safety sandbox cases passed.' -ForegroundColor Green
    $success = $true
} finally {
    if ($success -and (Test-Path -LiteralPath $markerPath)) {
        $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($marker.run_id -eq $runId -and (Split-Path -Parent $sandboxRoot) -eq $scratchRoot) {
            Remove-Item -LiteralPath $sandboxRoot -Recurse -Force
            Write-Host 'Removed only the uniquely marked test sandbox.' -ForegroundColor DarkGray
        } else { throw 'Refusing to remove a sandbox with an invalid marker.' }
    } elseif (-not $success) {
        Write-Warning "Sandbox retained for inspection: $sandboxRoot"
    }
}
# GitHub's pwsh wrapper propagates LASTEXITCODE from the expected negative test.
# Reach this only after every assertion and safe cleanup succeeded.
exit 0
