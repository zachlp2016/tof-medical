param([int]$Port = 8090)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$secretDir = Join-Path $projectRoot '.secrets'
$envFile = Join-Path $projectRoot '.env'
if ((Test-Path -LiteralPath $envFile) -or (Test-Path -LiteralPath $secretDir)) {
    throw 'Setup already exists. Preserve existing database credentials and tokens; this script does not rotate them.'
}
function New-RandomSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToHexString($bytes).ToLowerInvariant()
}
$dbPassword = New-RandomSecret
$mcpToken = New-RandomSecret
$clinicianToken = New-RandomSecret
$openmedToken = New-RandomSecret
$sha = [System.Security.Cryptography.SHA256]::Create()
function Get-TokenDigest([string]$Token) {
    return [Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Token))).ToLowerInvariant()
}
New-Item -ItemType Directory -Path $secretDir | Out-Null
New-Item -ItemType Directory -Path (Join-Path $secretDir 'utility') | Out-Null
$principals = @{}
$principals[(Get-TokenDigest $mcpToken)] = @{tenant_id='demo-clinic'; actor_id='tof-mcp-demo'; scopes=@('ehr:read')}
$principals[(Get-TokenDigest $clinicianToken)] = @{tenant_id='demo-clinic'; actor_id='demo-clinician'; scopes=@('ehr:read','ehr:write','ehr:audit')}
[IO.File]::WriteAllText((Join-Path $secretDir 'principals.json'), ($principals | ConvertTo-Json -Depth 5))
[IO.File]::WriteAllText((Join-Path $secretDir 'mcp-token.txt'), $mcpToken)
[IO.File]::WriteAllText((Join-Path $secretDir 'clinician-token.txt'), $clinicianToken)
[IO.File]::WriteAllText((Join-Path $secretDir 'openmed-token.txt'), $openmedToken)
[IO.File]::WriteAllText($envFile, "POSTGRES_PASSWORD=$dbPassword`nEHR_PORT=$Port`n")
$sha.Dispose()
# Remove inherited broad access on host secrets. Container bind access remains read-only.
if ($IsWindows) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $secretDir /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
    & icacls.exe $envFile /inheritance:r /grant:r "${identity}:F" 'SYSTEM:F' | Out-Null
}
Write-Output "Created local synthetic-demo configuration. Credentials are in .secrets (not printed)."
Write-Output "Provision local AI: ./scripts/setup-openmed.ps1"
Write-Output "Configure TOF AI when keys are available: ./scripts/setup-utility.ps1"
Write-Output "Start: docker compose up --build -d"
Write-Output "Open: http://localhost:$Port"
