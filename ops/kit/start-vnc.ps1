# FatFish remote desktop (noVNC) launcher - proven pattern: Start-Process ssh
$ErrorActionPreference = 'Continue'
$cmd = $args[0]
$key = Join-Path $PSScriptRoot 'napcat_tunnel'
$running = Get-Process ssh -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*ssh*' }
$probe = Test-NetConnection -ComputerName 127.0.0.1 -Port 6081 -WarningAction SilentlyContinue
if (-not $probe.TcpTestSucceeded) {
    Write-Host 'Opening tunnel to SnowLuma remote desktop...'
    Start-Process ssh -ArgumentList @('-i', $key, '-o', 'ServerAliveInterval=30', '-N', '-L', '6081:127.0.0.1:6081', 'ubuntu@101.34.204.107') -WindowStyle Minimized
    Start-Sleep -Seconds 3
}
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:6081/vnc.html' -TimeoutSec 8 -UseBasicParsing
    Write-Host ('Tunnel OK (HTTP ' + $r.StatusCode + '). Browser opens now.')
} catch {
    Write-Host 'Tunnel probe failed - the minimized ssh window may show the error.'
}
Start-Process 'http://127.0.0.1:6081/vnc.html'
