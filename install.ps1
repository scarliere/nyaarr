Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$StartScript = Join-Path $ProjectRoot "start.ps1"
$AppIconPng = Join-Path $ProjectRoot "nyaarr\static\img\default-icon.png"
$ShortcutIcon = Join-Path $ProjectRoot "data\image\nyaarr.ico"
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Nyaarr.lnk"

function Write-Step {
    param([string]$Message)
    Write-Host "[Nyaarr] $Message"
}

function Find-Python {
    $candidates = @(
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }
        try {
            $versionArgs = @($candidate.Args) + @("--version")
            $versionOutput = & $candidate.Command @versionArgs 2>&1
            if ($LASTEXITCODE -eq 0 -and ($versionOutput -join " ") -match "Python 3") {
                return $candidate
            }
        } catch {
            continue
        }
    }
    return $null
}

function Install-Python-With-Winget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3 was not found and winget is unavailable. Install Python 3.12+ from https://www.python.org/downloads/ and rerun install.ps1."
    }

    Write-Step "Python 3 was not found. Installing Python with winget."
    winget install --id Python.Python.3.12 --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed to install Python. Install Python manually and rerun install.ps1."
    }
}

function New-ShortcutIcon {
    if (Test-Path -LiteralPath $ShortcutIcon) {
        return $ShortcutIcon
    }
    if (-not (Test-Path -LiteralPath $AppIconPng)) {
        return "powershell.exe,0"
    }

    Write-Step "Creating shortcut icon."
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ShortcutIcon) | Out-Null
    Add-Type -AssemblyName System.Drawing
    $source = [System.Drawing.Bitmap]::new($AppIconPng)
    $bitmap = [System.Drawing.Bitmap]::new($source, [System.Drawing.Size]::new(256, 256))
    $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
    $stream = [System.IO.File]::Create($ShortcutIcon)
    try {
        $icon.Save($stream)
    } finally {
        $stream.Close()
        $icon.Dispose()
        $bitmap.Dispose()
        $source.Dispose()
    }
    return $ShortcutIcon
}

function New-DesktopShortcut {
    Write-Step "Creating desktop shortcut: $ShortcutPath"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`""
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.IconLocation = New-ShortcutIcon
    $shortcut.Description = "Start Nyaarr and open it in your browser"
    $shortcut.Save()
}

Write-Step "Installing Nyaarr from $ProjectRoot"

$python = Find-Python
if (-not $python) {
    Install-Python-With-Winget
    $python = Find-Python
}
if (-not $python) {
    throw "Python 3 is still unavailable after installation. Open a new terminal and rerun install.ps1."
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Step "Creating local virtual environment."
    & $python.Command @($python.Args + @("-m", "venv", $VenvDir))
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the virtual environment."
    }
} else {
    Write-Step "Using existing virtual environment."
}

Write-Step "Upgrading pip."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

Write-Step "Installing Python dependencies."
& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements.txt."
}

$FfprobePath = Join-Path $ProjectRoot "tools\ffmpeg\bin\ffprobe.exe"
if (-not (Test-Path -LiteralPath $FfprobePath)) {
    Write-Step "Installing repo-local ffprobe for media quality tags."
    try {
        & $VenvPython (Join-Path $ProjectRoot "scripts\install_ffprobe.py")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ffprobe install failed. Nyaarr can still run, but media quality tagging may be unavailable." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "ffprobe install failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Step "ffprobe is already installed."
}

New-DesktopShortcut

Write-Step "Install complete. Use the Nyaarr desktop shortcut or run start.ps1."
Write-Step "The launcher starts Nyaarr at http://127.0.0.1:1269 and opens your browser."