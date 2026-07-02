Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectRoot "main.py"
$AppUrl = "http://127.0.0.1:1269"
$LogDir = Join-Path $ProjectRoot "data\logs"
$StdoutLog = Join-Path $LogDir "nyaarr.out.log"
$StderrLog = Join-Path $LogDir "nyaarr.err.log"

function Write-Step {
    param([string]$Message)
    Write-Host "[Nyaarr] $Message"
}

function Test-NyaarrReady {
    try {
        $response = Invoke-WebRequest -Uri $AppUrl -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Nyaarr is not installed yet. Run install.ps1 first." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-NyaarrReady) {
    Write-Step "Nyaarr is already running. Opening browser."
    Start-Process $AppUrl
    exit 0
}

Write-Step "Starting Nyaarr at $AppUrl"
$process = Start-Process -FilePath $VenvPython -ArgumentList @($MainScript) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru

$started = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    if (Test-NyaarrReady) {
        $started = $true
        break
    }
    if ($process.HasExited) {
        break
    }
}

if ($started) {
    Write-Step "Opening browser."
    Start-Process $AppUrl
    exit 0
}

if ($process.HasExited) {
    Write-Host "Nyaarr stopped during startup. Check $StdoutLog and $StderrLog" -ForegroundColor Red
} else {
    Write-Host "Nyaarr started, but the browser check timed out. Opening $AppUrl anyway." -ForegroundColor Yellow
    Start-Process $AppUrl
}