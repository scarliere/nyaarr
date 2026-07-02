param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainScript = Join-Path $ProjectRoot "main.py"
$TrayScript = Join-Path $ProjectRoot "nyaarr\tray.py"
$DataRoot = Join-Path $ProjectRoot "data"
$Targets = @(
    Join-Path $DataRoot "user",
    Join-Path $DataRoot "cache",
    Join-Path $DataRoot "logs",
    Join-Path $DataRoot "image"
)

function Write-Step {
    param([string]$Message)
    Write-Host "[Nyaarr] $Message"
}

function Assert-InProject {
    param([string]$Path)
    $projectFullPath = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $targetFullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $targetFullPath.StartsWith($projectFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean path outside project root: $targetFullPath"
    }
}

function Stop-ExistingNyaarrProcesses {
    $mainScriptFullPath = [System.IO.Path]::GetFullPath($MainScript)
    $trayScriptFullPath = [System.IO.Path]::GetFullPath($TrayScript)
    $projectRootFullPath = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $currentProcessId = $PID
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
    $matches = @()

    foreach ($candidate in $processes) {
        if (-not $candidate.CommandLine) {
            continue
        }
        if ([int]$candidate.ProcessId -eq [int]$currentProcessId) {
            continue
        }
        $commandLine = [string]$candidate.CommandLine
        $runsMainScript = $commandLine.IndexOf($mainScriptFullPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $runsTrayScript = $commandLine.IndexOf($trayScriptFullPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $runsProjectMain = ($commandLine.IndexOf("main.py", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and ($commandLine.IndexOf($projectRootFullPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        $runsProjectTray = ($commandLine.IndexOf("tray.py", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and ($commandLine.IndexOf($projectRootFullPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        if ($runsMainScript -or $runsTrayScript -or $runsProjectMain -or $runsProjectTray) {
            $matches += $candidate
        }
    }

    if (-not $matches) {
        return
    }

    Write-Step "Stopping $($matches.Count) running Nyaarr process(es)."
    foreach ($match in $matches) {
        try {
            Stop-Process -Id $match.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Host "Unable to stop process $($match.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
}

function Clear-DirectoryContents {
    param([string]$Path)
    Assert-InProject $Path
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    Get-ChildItem -LiteralPath $Path -Force | Where-Object { $_.Name -ne ".gitkeep" } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
    New-Item -ItemType File -Force -Path (Join-Path $Path ".gitkeep") | Out-Null
}

Write-Host "This will delete Nyaarr local test data under:" -ForegroundColor Yellow
foreach ($target in $Targets) {
    Write-Host "  $target" -ForegroundColor Yellow
}
Write-Host "It will not delete code, .venv, tools, requirements, or the desktop shortcut." -ForegroundColor Yellow

if (-not $Force) {
    $answer = Read-Host "Type CLEAN to continue"
    if ($answer -ne "CLEAN") {
        Write-Host "Cancelled."
        exit 0
    }
}

Stop-ExistingNyaarrProcesses
foreach ($target in $Targets) {
    Write-Step "Cleaning $target"
    Clear-DirectoryContents $target
}

Write-Step "Local data cleared. Next startup will behave like a fresh client and ask for superadmin setup again."