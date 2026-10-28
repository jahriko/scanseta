# Starts the Scanseta backend on this PC, opens a temporary Cloudflare tunnel to it,
# then points scanseta.uic.edu.ph at the tunnel address. Run it again after any restart.
#
# One-time setup on this PC:
#   1. Run setup.ps1 (installs the backend) and install cloudflared.
#   2. Copy pc.env.example to pc.env and fill in the two values.
# Run with: powershell -ExecutionPolicy Bypass -File .\start-gpu-server.ps1
# Keep this window open. Press Ctrl+C in it to stop the backend and the tunnel.
# If you close the window instead, end python.exe and cloudflared.exe in Task Manager before running again.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = $PSScriptRoot
$projectId = "prj_ELw6z14G0IAZH3nW1LuRpnsZ1fnx"
$teamId = "team_q5US972YTWpumxpK0eIxamqP"
$port = 8000

Get-Content "$root\pc.env" | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') { Set-Variable -Name $Matches[1] -Value $Matches[2] }
}
if (-not $VERCEL_TOKEN -or -not $VERCEL_DEPLOY_HOOK) { throw "pc.env needs VERCEL_TOKEN and VERCEL_DEPLOY_HOOK." }

function Wait-For($what, $seconds, [scriptblock]$check, [scriptblock]$abort = $null) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if ($abort) { & $abort }
        try { $result = & $check; if ($result) { return $result } } catch { }
        Start-Sleep -Seconds 3
    }
    throw "Timed out waiting for $what."
}

$python = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Backend is not set up. Run setup.ps1 first." }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { throw "cloudflared is not installed or not on PATH." }

$running = $false
try { Invoke-RestMethod "http://localhost:$port/health" -TimeoutSec 3 | Out-Null; $running = $true } catch { if ($_.Exception.Response) { $running = $true } }
if ($running) { throw "Something is already running on port $port. End python.exe and cloudflared.exe in Task Manager, then run this again." }

Write-Host "[0/5] Checking the Vercel token..." -ForegroundColor Yellow
$headers = @{ Authorization = "Bearer $VERCEL_TOKEN" }
try { Invoke-RestMethod "https://api.vercel.com/v2/user" -Headers $headers | Out-Null }
catch { throw "Vercel rejected the token in pc.env. Create a new one at vercel.com/account/tokens." }

$backend = $null; $tunnel = $null
try {
    Write-Host "[1/5] Starting the backend (the model takes a few minutes to load)..." -ForegroundColor Yellow
    $backend = Start-Process $python -ArgumentList "run_server.py" `
        -WorkingDirectory "$root\backend" -PassThru -RedirectStandardOutput "$root\backend.log" -RedirectStandardError "$root\backend.err.log"
    $health = Wait-For "the backend" 1500 {
        $h = Invoke-RestMethod "http://localhost:$port/health"
        if ($h.model_loaded) { $h }
    } { if ($backend.HasExited) { throw "Backend stopped. See backend.err.log." } }
    if (-not $health.gpu_available) { Write-Host "      WARNING: no GPU found, the model runs on the CPU and will be very slow." -ForegroundColor Red }
    else { Write-Host "      Model loaded on $($health.device)." }

    Write-Host "[2/5] Opening the tunnel..." -ForegroundColor Yellow
    $tunnelLog = "$root\tunnel.log"
    Remove-Item $tunnelLog -ErrorAction SilentlyContinue
    $tunnel = Start-Process cloudflared -ArgumentList "tunnel","--url","http://localhost:$port" `
        -PassThru -RedirectStandardError $tunnelLog -RedirectStandardOutput "$root\tunnel.out.log"
    $url = Wait-For "the tunnel address" 90 {
        if (Test-Path $tunnelLog) {
            $m = [regex]::Matches((Get-Content $tunnelLog -Raw), 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com') | Select-Object -First 1
            if ($m) { $m.Value }
        }
    } { if ($tunnel.HasExited) { throw "cloudflared stopped. See tunnel.log." } }
    Write-Host "      $url"

    Write-Host "[3/5] Checking the tunnel reaches the backend..." -ForegroundColor Yellow
    Wait-For "the tunnel to answer" 120 { (Invoke-RestMethod "$url/health").model_loaded } | Out-Null

    Write-Host "[4/5] Updating the website address..." -ForegroundColor Yellow
    $base = "https://api.vercel.com/v9/projects/$projectId/env"
    $envVar = (Invoke-RestMethod "${base}?teamId=$teamId" -Headers $headers).envs | Where-Object key -eq "VITE_API_BASE_URL" | Select-Object -First 1
    if (-not $envVar) { throw "VITE_API_BASE_URL was not found on the Vercel project." }
    Invoke-RestMethod "$base/$($envVar.id)?teamId=$teamId" -Method Patch -Headers $headers `
        -ContentType "application/json" -Body (@{ value = $url } | ConvertTo-Json) | Out-Null

    Write-Host "[5/5] Redeploying the website (about 30 seconds)..." -ForegroundColor Yellow
    Invoke-RestMethod $VERCEL_DEPLOY_HOOK -Method Post | Out-Null

    Write-Host "`nDone. Open https://scanseta.uic.edu.ph in about a minute and switch to Live mode." -ForegroundColor Green
    Write-Host "Keep this window open. Press Ctrl+C to stop." -ForegroundColor Green
    Wait-Process -Id $backend.Id
} finally {
    foreach ($p in @($tunnel, $backend)) {
        if ($p -and -not $p.HasExited) {
            if ($env:OS -eq "Windows_NT") { taskkill /T /F /PID $p.Id | Out-Null }
            else { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
    }
}
