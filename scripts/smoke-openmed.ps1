param([string]$BaseUrl = 'http://localhost:8090', [string]$EncounterId = 'demo-encounter-1')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$credential = [IO.File]::ReadAllText((Join-Path $projectRoot '.secrets/clinician-token.txt')).Trim()
$headers = @{Authorization="Bearer $credential"}
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
$status = Invoke-RestMethod -Uri "$BaseUrl/api/ai/status" -Headers $headers
Assert-True ($status.operations.deidentify.ready) 'Local de-identification is not ready; provision model files and inspect the worker health.'
$before = Invoke-RestMethod -Uri "$BaseUrl/api/encounters/$EncounterId" -Headers $headers
# This local smoke must never transmit a saved encounter to a remote AI service.
$operations = @('deidentify')
if ($status.operations.entities.provider -eq 'openmed' -and $status.operations.entities.ready) {
    $operations += 'entities'
}
foreach ($operation in $operations) {
    $body = @{expectedVersion=$before.version;operation=$operation} | ConvertTo-Json
    $result = Invoke-RestMethod -Uri "$BaseUrl/api/encounters/$EncounterId/review" -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 150
    Assert-True ($result.encounterVersion -eq $before.version) 'AI response version does not match the saved note.'
    Assert-True ($result.reviewRequired -eq $true) 'AI output must require clinician review.'
    Assert-True ($result.operation -eq $operation) 'AI operation mismatch.'
    Assert-True ($result.model.id -and $result.model.revision) 'AI model provenance is missing.'
    Assert-True (-not $result.PSObject.Properties['original_text']) 'Upstream original text must not be returned.'
    if ($operation -eq 'deidentify') {
        Assert-True ($result.redactedText.Length -gt 0) 'De-identification preview is empty.'
        Assert-True ($result.entities.Count -eq 0) 'De-identification must not return raw PII entities.'
    }
    Write-Output "PASS: saved-note $operation review, pinned model provenance, review requirement, filtered output."
}
$after = Invoke-RestMethod -Uri "$BaseUrl/api/encounters/$EncounterId" -Headers $headers
Assert-True ($after.version -eq $before.version) 'AI review unexpectedly changed note version.'
Assert-True (($after.note | ConvertTo-Json -Compress) -eq ($before.note | ConvertTo-Json -Compress)) 'AI review unexpectedly changed note contents.'
$staleBody = @{expectedVersion=($before.version + 1);operation='entities'} | ConvertTo-Json
$stale = Invoke-WebRequest -Uri "$BaseUrl/api/encounters/$EncounterId/review" -Method Post -Headers $headers -ContentType 'application/json' -Body $staleBody -SkipHttpErrorCheck
Assert-True ($stale.StatusCode -eq 409) 'Stale note review must be rejected.'
Write-Output 'PASS: clinical record unchanged and stale-version review rejected. No note text or AI result contents were printed.'
