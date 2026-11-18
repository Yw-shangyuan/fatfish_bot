param([switch]$Quiet)
# Fetch the SnowLuma login QR code in two stages (robust against the
# Windows-ssh base64-pipe teardown hang seen 2026-10-28): stage 1 runs the
# server grabber quietly (refresh click + screenshot + crop), stage 2 scp's
# the small png file. Both legs are individually proven reliable.

$KEY  = Join-Path $PSScriptRoot "napcat_tunnel"
$SRV  = "ubuntu@101.34.204.107"
$OUT  = Join-Path $PSScriptRoot "fish_qr.png"

Write-Host "== 正在拉取肥鱼登录二维码 ==" -ForegroundColor Cyan

# stage 1: run grabber on server, stdout only gets the fresh mtime (or GRABFAIL)
$cmd = "timeout 45 bash /home/ubuntu/ops/grab-screen.sh >/dev/null 2>&1 && stat -c '%y' /tmp/fish_qr.png | cut -c1-19 || echo GRABFAIL"
$stamp = @(ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15 $SRV $cmd 2>$null) |
    Where-Object { $_ -match '\S' } | Select-Object -First 1
if (-not $stamp -or $stamp -notmatch '^\d{4}-\d{2}-\d{2}') {
    Write-Host "[X] 取码流程没跑通（服务器或 snowluma 容器不可达？）" -ForegroundColor Red
    if (-not $Quiet) { Read-Host "按回车退出" }
    exit 1
}
Write-Host ("二维码生成时间: " + $stamp + "  (刚自动点过刷新，取到即新鲜)") -ForegroundColor Yellow

# stage 2: pull the small png by scp (small file = quick and reliable)
scp -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15 "${SRV}:/tmp/fish_qr.png" "$OUT" 2>$null
$png = Get-Item $OUT -ErrorAction SilentlyContinue
if (-not $png -or $png.Length -lt 5000) {
    Write-Host "[X] 二维码图片没拉到，请重试" -ForegroundColor Red
    if (-not $Quiet) { Read-Host "按回车退出" }
    exit 1
}

Invoke-Item $OUT
Write-Host "[OK] 图片已打开：手机QQ「扫一扫」对准本屏幕即可登录" -ForegroundColor Green
Write-Host "      (约2分钟过期，过期就再双击一次本脚本，会自动点刷新取新码)" -ForegroundColor Gray
if (-not $Quiet) { Read-Host "按回车退出" }
