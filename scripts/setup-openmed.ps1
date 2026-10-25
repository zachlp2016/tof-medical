# Explicit provisioning only: network access downloads pinned public model files.
# The running inference container has no internet route and mounts models read-only.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$secretDir = Join-Path $projectRoot '.secrets'
$tokenFile = Join-Path $secretDir 'openmed-token.txt'
if (-not (Test-Path -LiteralPath (Join-Path $secretDir 'principals.json'))) {
    throw 'Run scripts/bootstrap.ps1 before provisioning local OpenMed.'
}
if (-not (Test-Path -LiteralPath $tokenFile)) {
    $tokenBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
    [IO.File]::WriteAllText($tokenFile, [Convert]::ToHexString($tokenBytes).ToLowerInvariant())
    if ($IsWindows) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $tokenFile /inheritance:r /grant:r "${identity}:F" 'SYSTEM:F' | Out-Null
    }
}
function Invoke-DockerChecked([string[]]$DockerArgs) {
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker provisioning step failed (exit $LASTEXITCODE). Existing credentials and data were preserved." }
}
Push-Location $projectRoot
try {
    Invoke-DockerChecked -DockerArgs @('compose', 'build', 'openmed')
    Invoke-DockerChecked -DockerArgs @('volume', 'create', 'tof-clinical_openmed-models')
    # No EHR secrets, records, or database access are mounted into this downloader.
    Invoke-DockerChecked -DockerArgs @('run', '--rm', '--user', '0', '--network', 'bridge',
        '--mount', 'type=volume,source=tof-clinical_openmed-models,target=/models',
        '-e', 'OPENMED_OFFLINE=0', '-e', 'HF_HUB_OFFLINE=0',
        '-e', 'TRANSFORMERS_OFFLINE=0', '-e', 'HF_DATASETS_OFFLINE=0',
        'tof-clinical-openmed:local', 'python', '/app/provision_models.py')
}
finally { Pop-Location }
Write-Output 'Local OpenMed models provisioned. Start with: docker compose up --build -d'
