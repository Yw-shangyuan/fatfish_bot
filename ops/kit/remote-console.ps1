# ============================================================
#  BlueBigFatFish Remote Console  (ASCII only, do not add CJK)
#  Server: 101.34.204.107 (Tencent Cloud Lighthouse)
#  Run: double-click  remote-console.cmd
# ============================================================

$ErrorActionPreference = "Continue"
$Server  = "ubuntu@101.34.204.107"
$KeyFile = Join-Path $PSScriptRoot "napcat_tunnel"
$PidFile = Join-Path $env:TEMP "napcat_tunnel_ssh.pid"

function SshCmd([string]$remote) {
    & ssh -i "$KeyFile" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new $Server $remote
}

function PortInUse([int]$p) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    return [bool]$c
}

function Start-Tunnel {
    if (-not (Test-Path $KeyFile)) {
        Write-Host "[X] key file 'napcat_tunnel' not found. Run menu [4] first." -ForegroundColor Red
        return $false
    }
    if (PortInUse 6185) {
        Write-Host "[=] tunnel already running, opening panels directly" -ForegroundColor Yellow
        return $true
    }
    Write-Host "[*] opening tunnel 6185/6099 -> server ..." -ForegroundColor Cyan
    $p = Start-Process ssh -ArgumentList @(
        "-i", "`"$KeyFile`"", "-N", "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
        "-L", "6185:127.0.0.1:6185", "-L", "6099:127.0.0.1:6099", $Server
    ) -WindowStyle Hidden -PassThru
    $p.Id | Out-File -Encoding ascii $PidFile
    Start-Sleep -Seconds 3
    if (-not (PortInUse 6185)) {
        Write-Host "[X] tunnel failed. Check network / run menu [4] to set up key auth." -ForegroundColor Red
        return $false
    }
    Write-Host "[OK] tunnel PID=$($p.Id)  (menu [0] closes it)" -ForegroundColor Green
    return $true
}

function Show-Banners {
    Write-Host ""
    Write-Host "  +--------------------------------------------------+ " -ForegroundColor Magenta
    Write-Host "  |   BlueBigFatFish  101.34.204.107               | " -ForegroundColor Magenta
    Write-Host "  |   [1] Web panels (tunnel + browser, most used)  | " -ForegroundColor Magenta
    Write-Host "  |   [2] Server health check                      | " -ForegroundColor Magenta
    Write-Host "  |   [3] SSH terminal to server                     | " -ForegroundColor Magenta
    Write-Host "  |   [4] Set up key auth on THIS PC (first time)    | " -ForegroundColor Magenta
    Write-Host "  |   [5] Live logs: AstrBot                         | " -ForegroundColor Magenta
    Write-Host "  |   [6] Live logs: SnowLuma (QQ)                     | " -ForegroundColor Magenta
    Write-Host "  |   [0] Exit (also closes tunnel)                  | " -ForegroundColor Magenta
    Write-Host "  +--------------------------------------------------+ " -ForegroundColor Magenta
    Write-Host ""
}

function Do-Panels {
    if (-not (Start-Tunnel)) { return }
    Write-Host "[*] AstrBot panel  http://127.0.0.1:6185  (user ywsy)" -ForegroundColor Cyan
    Write-Host "[*] SnowLuma noVNC  http://127.0.0.1:6081  (VNC password: docker inspect snowluma)" -ForegroundColor Cyan
    Start-Process "http://127.0.0.1:6185"
    Start-Process "http://127.0.0.1:6099"
}

function Do-Health {
    Write-Host "[*] checking ..." -ForegroundColor Cyan
    # NOTE: remote command kept ASCII-only (argv codepage safety)
    $cmd = @'
echo '=== AstrBot ==='
systemctl is-active astrbot
echo '=== SnowLuma ==='
docker ps --filter name=snowluma --format '{{.Status}}'
echo '=== Memory(MB) ==='
free -m | sed -n 2p
echo '=== Disk ==='
df -h / | sed -n 2p
echo '=== QQ online ==='
curl -s --max-time 5 http://127.0.0.1:3000/get_status -d {}
echo ''
echo '=== Errors last 10min ==='
sudo journalctl -u astrbot --since '10 min' -p err --no-pager | tail -3
echo '=== DONE ==='
'@
    SshCmd $cmd
}

function Do-SetupKey {
    if (-not (Test-Path $KeyFile)) {
        Write-Host "[*] generating key pair ..." -ForegroundColor Cyan
        Start-Process ssh-keygen -ArgumentList @("-t","ed25519","-C","napcat-tunnel","-N","`"`"","-f","`"$KeyFile`"") -Wait -NoNewWindow
    }
    $pub = (Get-Content "$KeyFile.pub" -Raw).Trim()
    $tag = $pub.Substring(0, 40)
    Write-Host "[*] ssh will now ask for the SERVER LOGIN PASSWORD once:" -ForegroundColor Yellow
    & ssh -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no $Server "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '$tag' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; echo SETUP_DONE"
    Write-Host "[*] verifying key auth ..." -ForegroundColor Cyan
    & ssh -i "$KeyFile" -o BatchMode=yes $Server "echo KEYLESS_OK"
}

function Do-Log([string]$which) {
    if (-not (Test-Path $KeyFile)) { Write-Host "missing key file, run menu [4] first" -ForegroundColor Red; return }
    if ($which -eq "astrbot") {
        Write-Host "=== AstrBot live log (Ctrl+C to stop) ===" -ForegroundColor Cyan
        & ssh -i "$KeyFile" $Server "sudo journalctl -u astrbot -n 60 --no-pager -f"
    } else {
        Write-Host "=== SnowLuma live log (Ctrl+C to stop) ===" -ForegroundColor Cyan
        & ssh -i "$KeyFile" $Server "sudo docker logs --tail 60 -f snowluma"
    }
}

# ---------------- main loop ----------------
while ($true) {
    Show-Banners
    $choice = Read-Host "  pick"
    switch ($choice) {
        "1" { Do-Panels }
        "2" { Do-Health }
        "3" { Write-Host "[*] enter 'exit' to come back" -ForegroundColor Cyan; & ssh -i "$KeyFile" $Server }
        "4" { Do-SetupKey }
        "5" { Do-Log "astrbot" }
        "6" { Do-Log "snowluma" }
        "0" {
            if (Test-Path $PidFile) {
                $oldpid = Get-Content $PidFile -ErrorAction SilentlyContinue
                if ($oldpid) { Stop-Process -Id $oldpid -Force -ErrorAction SilentlyContinue }
                Remove-Item $PidFile -ErrorAction SilentlyContinue
                Write-Host "[OK] tunnel closed" -ForegroundColor Green
            }
            exit
        }
        default { Write-Host "invalid option" -ForegroundColor Red }
    }
    Write-Host ""
    Read-Host "press Enter to go back to menu" | Out-Null
    Clear-Host
}
