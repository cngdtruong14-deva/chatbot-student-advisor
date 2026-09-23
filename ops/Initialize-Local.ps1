[CmdletBinding()]
param (
    [string]$ProjectName = 'sic-student-advisor',
    [string]$ApiImageTag = 'foundation',
    [ValidateRange(1, 65535)][int]$WebPort = 3000,
    [ValidateRange(1, 65535)][int]$ApiPort = 8000
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{0,62}$') { throw 'ProjectName must use lowercase letters, digits, hyphens, or underscores.' }
if ($ApiImageTag -notmatch '^[a-z0-9][a-z0-9._-]{0,127}$') { throw 'ApiImageTag must use lowercase letters, digits, dots, hyphens, or underscores.' }
if ($WebPort -eq $ApiPort) { throw 'WebPort and ApiPort must be different.' }

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
$configurationKeys = @('COMPOSE_PROJECT_NAME', 'API_IMAGE_TAG', 'WEB_PORT', 'API_PORT')

function Get-SafeEnvConfiguration([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([A-Z_]+)=(.*)$' -and $configurationKeys -contains $Matches[1]) { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

if (Test-Path -LiteralPath $envPath) {
    $existing = Get-SafeEnvConfiguration $envPath
    $defaults = @{ COMPOSE_PROJECT_NAME = 'sic-student-advisor'; API_IMAGE_TAG = 'foundation'; WEB_PORT = '3000'; API_PORT = '8000' }
    $requested = @{ COMPOSE_PROJECT_NAME = $ProjectName; API_IMAGE_TAG = $ApiImageTag; WEB_PORT = "$WebPort"; API_PORT = "$ApiPort" }
    foreach ($parameter in $PSBoundParameters.Keys) {
        $key = @{ ProjectName = 'COMPOSE_PROJECT_NAME'; ApiImageTag = 'API_IMAGE_TAG'; WebPort = 'WEB_PORT'; ApiPort = 'API_PORT' }[$parameter]
        if (-not $key) { continue } # Ignore PowerShell common parameters such as Verbose.
        $actual = if ($existing.ContainsKey($key)) { $existing[$key] } else { $defaults[$key] }
        if ($requested[$key] -ne $actual) { throw "Existing .env is preserved; requested $parameter conflicts with its current configuration. Edit .env deliberately after stopping the relevant stack." }
    }
    Write-Host 'Existing .env preserved; its requested configuration is unchanged.'
    exit 0
}

$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
function New-LocalSecret { $buffer = New-Object byte[] 32; $generator.GetBytes($buffer); return [Convert]::ToBase64String($buffer) }
try {
    $content = @(
        '# LOCAL SECRETS - DO NOT COMMIT OR SHARE',
        "COMPOSE_PROJECT_NAME=$ProjectName", "API_IMAGE_TAG=$ApiImageTag",
        ('ADMIN_DB_PASSWORD=' + (New-LocalSecret)), ('MIGRATOR_DB_PASSWORD=' + (New-LocalSecret)), ('APP_DB_PASSWORD=' + (New-LocalSecret)),
        "WEB_PORT=$WebPort", "API_PORT=$ApiPort"
    )
    [System.IO.File]::WriteAllLines($envPath, $content, (New-Object System.Text.UTF8Encoding($false)))
} finally { $generator.Dispose() }
Write-Host "Created a local .env for project '$ProjectName'. Secret values are not displayed."
