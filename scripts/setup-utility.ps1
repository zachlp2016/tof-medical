param(
    [ValidateRange(1, 65535)][int]$Port = 8090,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$secretDir = Join-Path $projectRoot '.secrets/utility'
$clinicianPath = Join-Path $projectRoot '.secrets/clinician-token.txt'
if (-not (Test-Path -LiteralPath $clinicianPath -PathType Leaf)) {
    throw 'Run bootstrap.ps1 first. This script uses the local clinician credential for the synthetic connection check.'
}

function Read-PrivateKey([string]$Prompt) {
    $secureValue = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
        $keyValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
        if ($keyValue.Length -lt 20 -or $keyValue.Length -gt 4096 -or $keyValue -match '[^\x21-\x7E]') {
            throw 'The credential must contain 20-4096 printable ASCII characters without spaces.'
        }
        return $keyValue
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $secureValue.Dispose()
    }
}

if (-not $VerifyOnly) {
    Write-Output 'Enter the inference key and the compute reservation key. The TOF services may use different credentials.'
    Write-Output 'If one issued key explicitly authorizes both services, enter that key at both prompts.'
    $inferenceKey = $null
    $computeKey = $null
    try {
        $inferenceKey = Read-PrivateKey 'TOF utility-medium inference API key'
        $computeKey = Read-PrivateKey 'TOF compute reservation API key'
        New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
        if ($IsWindows) {
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
            & icacls.exe $secretDir /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restrict access to the credential directory.' }
        }
        [IO.File]::WriteAllText((Join-Path $secretDir 'inference-key.txt'), $inferenceKey)
        [IO.File]::WriteAllText((Join-Path $secretDir 'compute-key.txt'), $computeKey)
    } finally {
        $inferenceKey = $null
        $computeKey = $null
    }
    Write-Output 'Credentials saved in .secrets/utility; they were not printed or sent to the browser.'
    Write-Output 'Verification remains pending. When ready, run this script with -VerifyOnly or select Verify connection in the EHR.'
    return
}

$credential = [IO.File]::ReadAllText($clinicianPath).Trim()
try {
    # This endpoint accepts no note text and tests only a built-in synthetic sentence.
    # Keep this URL local so the local EHR credential is never sent to a remote host.
    $result = Invoke-RestMethod -Uri "http://localhost:$Port/api/ai/verify" -Method Post `
        -Headers @{Authorization="Bearer $credential"} -TimeoutSec 150 -MaximumRedirection 0
    if (-not $result.operations.entities.ready) {
        throw 'Verification did not report a ready utility-medium connection.'
    }
    Write-Output 'PASS: utility-medium synthetic extraction, compute reservation, and lease release verified.'
    Write-Output 'Refresh Connections in the EHR. After an EHR restart, run this script with -VerifyOnly or select Verify connection.'
} catch {
    # Do not print exception request headers, bodies, or service diagnostics.
    throw 'TOF AI verification failed. Keys remain saved. Start the updated EHR, check Connections, and verify the inference and compute permissions; then rerun with -VerifyOnly.'
} finally {
    $credential = $null
}
