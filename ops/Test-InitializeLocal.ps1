[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$runId = [guid]::NewGuid().ToString('N')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) "advisor-bootstrap-$runId"
New-Item -ItemType Directory -Path (Join-Path $testRoot 'ops') | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Initialize-Local.ps1') -Destination (Join-Path $testRoot 'ops/Initialize-Local.ps1')
$script = Join-Path $testRoot 'ops/Initialize-Local.ps1'
$envPath = Join-Path $testRoot '.env'
function Invoke-Case([string]$Label, [string[]]$Arguments, [bool]$Success) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $script @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if (($code -eq 0) -ne $Success) { throw "Unexpected result: $Label (exit $code)" }
    Write-Host "[OK] $Label"
}
Invoke-Case 'fresh custom configuration' @('-ProjectName','bootstrap-test','-ApiImageTag','bootstrap-test','-WebPort','13000','-ApiPort','18000') $true
$before = (Get-FileHash -LiteralPath $envPath).Hash
$lines = Get-Content -LiteralPath $envPath
$secrets = @($lines | Where-Object { $_ -match '^(ADMIN|MIGRATOR|APP)_DB_PASSWORD=' } | ForEach-Object { ($_ -split '=',2)[1] })
if ($secrets.Count -ne 3 -or @($secrets | Sort-Object -Unique).Count -ne 3) { throw 'Secrets must be independent.' }
foreach ($secret in $secrets) { if ([Convert]::FromBase64String($secret).Length -ne 32) { throw 'Invalid generated secret length.' } }
Invoke-Case 'idempotent without parameters' @() $true
Invoke-Case 'matching configuration with common parameter' @('-ProjectName','bootstrap-test','-Verbose') $true
Invoke-Case 'conflicting project refused' @('-ProjectName','different') $false
Invoke-Case 'conflicting port refused' @('-ApiPort','18001') $false
Invoke-Case 'invalid project refused' @('-ProjectName','INVALID') $false
Invoke-Case 'invalid tag refused' @('-ApiImageTag','bad/tag') $false
Invoke-Case 'out-of-range port refused' @('-ApiPort','65536') $false
Invoke-Case 'duplicate ports refused' @('-ApiPort','12345','-WebPort','12345') $false
if ((Get-FileHash -LiteralPath $envPath).Hash -ne $before) { throw 'Existing .env was altered.' }
# Delete only the exact unique test directory created above; never the real project configuration.
$resolved = [IO.Path]::GetFullPath($testRoot)
if ((Split-Path $resolved -Leaf) -ne "advisor-bootstrap-$runId" -or (Split-Path $resolved -Parent).TrimEnd('\') -ne ([IO.Path]::GetTempPath()).TrimEnd('\')) { throw 'Unsafe cleanup target.' }
Remove-Item -LiteralPath $resolved -Recurse
Write-Host 'PASS: bootstrap, validation and .env preservation; temporary fixture removed.'
# Do not leak an expected negative-test exit status into the CI wrapper.
exit 0
