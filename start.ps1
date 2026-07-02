Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectRoot "main.py"
$HostName = if ($env:NYAARR_HOST) { $env:NYAARR_HOST } else { "127.0.0.1" }
$Port = if ($env:NYAARR_PORT) { [int]$env:NYAARR_PORT } else { 1269 }
$BrowserUrl = if ($env:NYAARR_PUBLIC_URL) { $env:NYAARR_PUBLIC_URL } else { "http://127.0.0.1:$Port" }
$ProbeUrl = "http://127.0.0.1:$Port"
$LogDir = Join-Path $ProjectRoot "data\logs"
$StdoutLog = Join-Path $LogDir "nyaarr.out.log"
$StderrLog = Join-Path $LogDir "nyaarr.err.log"

function Write-Step {
    param([string]$Message)
    Write-Host "[Nyaarr] $Message"
}

function Wait-To-Read {
    Write-Host ""
    Read-Host "Press Enter to close"
}

function Show-RecentLog {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $content = Get-Content -LiteralPath $Path -Tail 30 -ErrorAction SilentlyContinue
    if (-not $content) {
        return
    }
    Write-Host ""
    Write-Host "--- $Label ---" -ForegroundColor Yellow
    $content | ForEach-Object { Write-Host $_ }
}

function Test-NyaarrReady {
    try {
        $response = Invoke-WebRequest -Uri $ProbeUrl -UseBasicParsing -TimeoutSec 2 -MaximumRedirection 5
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Open-NyaarrBrowser {
    param([string]$Url)
    try {
        Start-Process -FilePath $Url
    } catch {
        Write-Host "Unable to open browser automatically: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "Open this URL manually: $Url" -ForegroundColor Cyan
        Wait-To-Read
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Nyaarr is not installed yet. Run install.ps1 first." -ForegroundColor Yellow
    Wait-To-Read
    exit 1
}

if (-not (Test-Path -LiteralPath $MainScript)) {
    Write-Host "main.py was not found at $MainScript. Reinstall Nyaarr or fix the shortcut target." -ForegroundColor Red
    Wait-To-Read
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $ProjectRoot

if (Test-NyaarrReady) {
    Write-Step "Nyaarr is already running. Opening browser at $BrowserUrl."
    Open-NyaarrBrowser $BrowserUrl
    exit 0
}

Write-Step "Starting Nyaarr. Bind host: $HostName. Browser URL: $BrowserUrl"
$env:NYAARR_HOST = $HostName
$env:NYAARR_PORT = [string]$Port
$env:NYAARR_DEBUG = if ($env:NYAARR_DEBUG) { $env:NYAARR_DEBUG } else { "0" }

$process = Start-Process -FilePath $VenvPython -ArgumentList @($MainScript) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru

$started = $false
for ($attempt = 0; $attempt -lt 45; $attempt++) {
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
    Write-Step "Nyaarr is ready. Opening browser."
    Open-NyaarrBrowser $BrowserUrl
    exit 0
}

if ($process.HasExited) {
    Write-Host "Nyaarr stopped during startup. Exit code: $($process.ExitCode)" -ForegroundColor Red
    Write-Host "Logs: $StdoutLog and $StderrLog" -ForegroundColor Yellow
    Show-RecentLog $StdoutLog "stdout"
    Show-RecentLog $StderrLog "stderr"
    Wait-To-Read
    exit 1
}

Write-Host "Nyaarr process is running, but the readiness check timed out." -ForegroundColor Yellow
Write-Host "Trying to open $BrowserUrl anyway." -ForegroundColor Yellow
Open-NyaarrBrowser $BrowserUrl
Write-Host "If the page still does not load, check $StdoutLog and $StderrLog." -ForegroundColor Yellow
Wait-To-Read