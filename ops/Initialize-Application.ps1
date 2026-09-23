$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $environmentFile)) { throw 'Run Initialize-Local.ps1 first.' }
$content = [IO.File]::ReadAllText($environmentFile)
if ($content -match '(?m)^JWT_SECRET=') {
    Write-Host 'JWT_SECRET exists; preserved without displaying it.'
    exit 0
}
$randomBytes = New-Object byte[] 48
$generator = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
$applicationSecret = [Convert]::ToBase64String($randomBytes)
[IO.File]::AppendAllText($environmentFile, "`nJWT_SECRET=$applicationSecret`n", (New-Object Text.UTF8Encoding($false)))
Write-Host 'Added local JWT secret. Existing credentials preserved. Recreate API to load it.'
