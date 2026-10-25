#Requires -RunAsAdministrator
param(
    [ValidateRange(1024,65535)][int]$Port = 8090,
    [string]$InterfaceAlias = 'Wi-Fi',
    [string]$LocalAddress = '192.168.10.154'
)
$ErrorActionPreference = 'Stop'
# Restrict the exception to one currently assigned address, one interface,
# one TCP port, and directly connected subnets. No global firewall settings change.
$assigned = Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -eq $LocalAddress -and $_.AddressState -eq 'Preferred' }
if (-not $assigned) { throw 'The requested local address is not assigned to this interface.' }
$ruleName = "TOF-Clinical-LAN-$Port"
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -LocalAddress $LocalAddress -RemoteAddress LocalSubnet `
        -InterfaceAlias $InterfaceAlias -Profile Private,Public -EdgeTraversalPolicy Block | Out-Null
}
else {
    New-NetFirewallRule -Name $ruleName -DisplayName "TOF Clinical LAN (TCP $Port)" `
        -Description 'Local-subnet access to the synthetic TOF Clinical EHR demo.' `
        -Enabled True -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -LocalAddress $LocalAddress -RemoteAddress LocalSubnet -InterfaceAlias $InterfaceAlias `
        -Profile Private,Public -EdgeTraversalPolicy Block | Out-Null
}
Write-Output "Allowed local-subnet access to http://${LocalAddress}:$Port on $InterfaceAlias."
