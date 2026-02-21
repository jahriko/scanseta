param(
    [switch]$SkipPlaywright,
    [switch]$SkipEnv
)

$ErrorActionPreference = "Stop"
$rootDir = $PSScriptRoot

Write-Host "=== Scanseta Setup ===" -ForegroundColor Cyan

# Backend setup
Write-Host "`n[1/5] Backend: Creating virtual environment..." -ForegroundColor Yellow
Set-Location "$rootDir\backend"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  Created .venv virtual environment"
} else {
    Write-Host "  .venv already exists (skipping creation)"
}

Write-Host "`n[2/5] Backend: Installing Python dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\pip.exe install -r requirements.txt

if (-not $SkipPlaywright) {
    Write-Host "`n[3/5] Backend: Installing Playwright Chromium..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe -m playwright install chromium
} else {
    Write-Host "`n[3/5] Skipping Playwright installation (SkipPlaywright flag set)" -ForegroundColor Gray
}

# Frontend setup
Write-Host "`n[4/5] Frontend: Installing npm dependencies..." -ForegroundColor Yellow
Set-Location "$rootDir\frontend"
npm install

# Environment configuration
if (-not $SkipEnv) {
    Write-Host "`n[5/5] Frontend: Configuring .env.local..." -ForegroundColor Yellow
    $envPath = "$rootDir\frontend\.env.local"
    $defaultApiUrl = "VITE_API_BASE_URL=http://localhost:8000"

    if (-not (Test-Path $envPath)) {
        Set-Content -Path $envPath -Value $defaultApiUrl
        Write-Host "  Created .env.local with $defaultApiUrl"
    } else {
        Write-Host "  .env.local already exists (not modified)"
    }
} else {
    Write-Host "`n[5/5] Skipping .env.local configuration (SkipEnv flag set)" -ForegroundColor Gray
}

Set-Location $rootDir
Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "You can now run .\dev.ps1 to start backend and frontend."

