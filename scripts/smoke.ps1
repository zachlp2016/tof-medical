param([string]$BaseUrl = 'http://localhost:8090')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$credential = [IO.File]::ReadAllText((Join-Path $projectRoot '.secrets/mcp-token.txt')).Trim()
$headers = @{Authorization="Bearer $credential"; Accept='application/json, text/event-stream'}
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Invoke-Rpc([hashtable]$Payload) {
    Invoke-WebRequest -Uri "$BaseUrl/mcp" -Method Post -Headers $headers -ContentType 'application/json' -Body ($Payload | ConvertTo-Json -Depth 10)
}
$ready = Invoke-WebRequest -Uri "$BaseUrl/readyz"
Assert-True ($ready.StatusCode -eq 200) 'Database readiness failed'
$unauthorized = Invoke-WebRequest -Uri "$BaseUrl/mcp" -Method Post -ContentType 'application/json' -Body '{"jsonrpc":"2.0","id":"test","method":"tools/list"}' -SkipHttpErrorCheck
Assert-True ($unauthorized.StatusCode -eq 401) 'MCP must require a credential'
# Exact discovery used by TOF Settings, intentionally before initialization.
$discovery = (Invoke-Rpc @{jsonrpc='2.0';id='connection-test';method='tools/list';params=@{}}).Content | ConvertFrom-Json
Assert-True ($discovery.id -eq 'connection-test') 'Discovery request ID mismatch'
Assert-True ($discovery.result.tools.Count -eq 5) 'Expected the five bounded clinical read tools'
foreach ($tool in $discovery.result.tools) {
    Assert-True ($tool.annotations.readOnlyHint -eq $true) "Tool must declare read-only: $($tool.name)"
}
$initialized = (Invoke-Rpc @{jsonrpc='2.0';id='init';method='initialize';params=@{protocolVersion='2025-11-25';capabilities=@{};clientInfo=@{name='tof-contract-smoke';version='1.0.0'}}}).Content | ConvertFrom-Json
Assert-True ($initialized.result.protocolVersion -eq '2025-11-25') 'TOF protocol negotiation mismatch'
$headers['MCP-Protocol-Version'] = '2025-11-25'
$notification = Invoke-Rpc @{jsonrpc='2.0';method='notifications/initialized'}
Assert-True ($notification.StatusCode -eq 202) 'Initialized notification must return 202'
$result = (Invoke-Rpc @{jsonrpc='2.0';id='call';method='tools/call';params=@{name='search_patients';arguments=@{query='Eleanor'}}}).Content | ConvertFrom-Json
Assert-True (-not $result.result.isError) 'Clinical search failed'
Assert-True ($result.result.content.Count -gt 0) 'Clinical search response is empty'
$writeAttempt = Invoke-WebRequest -Uri "$BaseUrl/api/patients" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"firstName":"Denied","lastName":"Write","dateOfBirth":"1990-01-01","sex":"unknown"}' -SkipHttpErrorCheck
Assert-True ($writeAttempt.StatusCode -eq 403) 'MCP read credential must not authorize clinical writes'
$spoof = Invoke-WebRequest -Uri "$BaseUrl/mcp" -Method Post -Headers @{Authorization="Bearer $credential";Accept='application/json, text/event-stream';Origin='https://untrusted.example'} -ContentType 'application/json' -Body '{"jsonrpc":"2.0","id":"test","method":"tools/list"}' -SkipHttpErrorCheck
Assert-True ($spoof.StatusCode -eq 403) 'Untrusted browser origin must be rejected'
Write-Output 'PASS: readiness, authentication, exact TOF discovery, five read tools, protocol handshake, 202 notification, clinical search, write denial, origin denial.'
