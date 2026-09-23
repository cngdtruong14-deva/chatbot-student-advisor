<#
Restore only into an explicitly named EMPTY database. Never implicitly replace the live database.
Create a separate database on a disposable Docker container, then pass its exact identity.
SQL scripts are not accepted: only pg_dump custom archives are supported.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InFile,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]+$')][string]$TargetContainer,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z][a-zA-Z0-9_]+$')][string]$Database,
    [Parameter(Mandatory=$true)][string]$ConfirmTarget
)
$ErrorActionPreference='Stop'
if ($ConfirmTarget -cne "RESTORE:${TargetContainer}:${Database}") { throw 'Exact restore target confirmation required' }
$file = Get-Item -LiteralPath $InFile -ErrorAction Stop
if ($file.PSIsContainer -or $file.Extension -notin @('.dump','.backup')) { throw 'Only trusted pg_dump custom archives (.dump/.backup) are supported' }
# Read-only guard: target must exist and contain no application objects.
$count = & docker exec $TargetContainer psql -U advisor_admin -d $Database -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S')"
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify restore target' }
if ($count.Trim() -ne '0') { throw 'Target is not empty. Restore into a new isolated database; live overwrite is prohibited.' }
$tempName = '/tmp/advisor-restore-' + [Guid]::NewGuid().ToString('N') + '.dump'
& docker cp $file.FullName "${TargetContainer}:$tempName"
if ($LASTEXITCODE -ne 0) { throw 'Cannot copy archive to restore target' }
& docker exec $TargetContainer pg_restore --list $tempName *> $null
if ($LASTEXITCODE -ne 0) { throw 'Invalid custom backup archive; no restore attempted' }
& docker exec $TargetContainer pg_restore -U advisor_admin -d $Database --single-transaction --exit-on-error $tempName
if ($LASTEXITCODE -ne 0) { throw 'Restore failed and transaction rolled back; any nonzero exit is failure' }
Write-Host "PASS: restored into explicit empty target ${TargetContainer}/${Database}. Source backup and temporary archive preserved."
