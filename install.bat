@echo off
setlocal EnableExtensions EnableDelayedExpansion

if /I "%~1"=="/?" goto :usage
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS=%PROJECT_ROOT%\requirements.txt"
set "START_SCRIPT=%PROJECT_ROOT%\start.ps1"
set "APP_ICON_PNG=%PROJECT_ROOT%\nyaarr\static\img\default-icon.png"
set "SHORTCUT_ICON=%PROJECT_ROOT%\data\image\nyaarr.ico"
set "DESKTOP=%USERPROFILE%\Desktop"
for /f "usebackq delims=" %%D in (`powershell.exe -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
set "SHORTCUT_PATH=%DESKTOP%\Nyaarr.lnk"

call :step "Installing Nyaarr from %PROJECT_ROOT%"
call :find_python
if not defined PYTHON_EXE (
    call :install_python_with_winget || goto :fail
    call :find_python
)
if not defined PYTHON_EXE (
    echo Python 3 is still unavailable after installation. Open a new terminal and rerun install.bat.
    goto :fail
)

if not exist "%VENV_PYTHON%" (
    call :step "Creating local virtual environment."
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        goto :fail
    )
) else (
    call :step "Using existing virtual environment."
)

call :step "Upgrading pip."
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    goto :fail
)

call :step "Installing Python dependencies."
"%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%"
if errorlevel 1 (
    echo Failed to install requirements.txt.
    goto :fail
)

set "FFPROBE_PATH=%PROJECT_ROOT%\tools\ffmpeg\bin\ffprobe.exe"
if not exist "%FFPROBE_PATH%" (
    call :step "Installing repo-local ffprobe for media quality tags."
    "%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\install_ffprobe.py"
    if errorlevel 1 echo ffprobe install failed. Nyaarr can still run, but media quality tagging may be unavailable.
) else (
    call :step "ffprobe is already installed."
)

call :create_shortcut_icon
call :create_desktop_shortcut || goto :fail

call :step "Install complete. Use the Nyaarr desktop shortcut or run start.ps1."
call :step "The launcher starts Nyaarr at http://127.0.0.1:1269 and opens your browser."
exit /b 0

:usage
echo Usage: install.bat
echo.
echo Installs Nyaarr alpha dependencies into .venv, attempts repo-local ffprobe,
echo and creates the Nyaarr desktop shortcut.
exit /b 0

:step
echo [Nyaarr] %~1
exit /b 0

:find_python
set "PYTHON_EXE="
set "PYTHON_ARGS="
py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    exit /b 0
)
python --version 2>nul | findstr /R /C:"^Python 3" >nul
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
    exit /b 0
)
python3 --version 2>nul | findstr /R /C:"^Python 3" >nul
if not errorlevel 1 (
    set "PYTHON_EXE=python3"
    set "PYTHON_ARGS="
    exit /b 0
)
exit /b 0

:install_python_with_winget
where winget >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found and winget is unavailable. Install Python 3.12+ from https://www.python.org/downloads/ and rerun install.bat.
    exit /b 1
)
call :step "Python 3 was not found. Installing Python with winget."
winget install --id Python.Python.3.12 --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo winget failed to install Python. Install Python manually and rerun install.bat.
    exit /b 1
)
exit /b 0

:create_shortcut_icon
if exist "%SHORTCUT_ICON%" exit /b 0
if not exist "%APP_ICON_PNG%" exit /b 0
call :step "Creating shortcut icon."
if not exist "%PROJECT_ROOT%\data\image" mkdir "%PROJECT_ROOT%\data\image" >nul 2>nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Drawing; $source=[System.Drawing.Bitmap]::new('%APP_ICON_PNG%'); $bitmap=[System.Drawing.Bitmap]::new($source,[System.Drawing.Size]::new(256,256)); $icon=[System.Drawing.Icon]::FromHandle($bitmap.GetHicon()); $stream=[System.IO.File]::Create('%SHORTCUT_ICON%'); try { $icon.Save($stream) } finally { $stream.Close(); $icon.Dispose(); $bitmap.Dispose(); $source.Dispose() }"
if errorlevel 1 echo Shortcut icon creation failed. The shortcut will use the default PowerShell icon.
exit /b 0

:create_desktop_shortcut
call :step "Creating desktop shortcut: %SHORTCUT_PATH%"
set "SHORTCUT_ICON_LOCATION=%SHORTCUT_ICON%"
if not exist "%SHORTCUT_ICON%" set "SHORTCUT_ICON_LOCATION=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe,0"
set "SHORTCUT_TARGET=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "SHORTCUT_ARGS=-NoProfile -ExecutionPolicy Bypass -File ""%START_SCRIPT%"""
set "VBS=%TEMP%\nyaarr_create_shortcut_%RANDOM%%RANDOM%.vbs"
> "%VBS%" echo Set shell = CreateObject("WScript.Shell")
>> "%VBS%" echo Set shortcut = shell.CreateShortcut(WScript.Arguments(0))
>> "%VBS%" echo shortcut.TargetPath = WScript.Arguments(1)
>> "%VBS%" echo shortcut.Arguments = WScript.Arguments(2)
>> "%VBS%" echo shortcut.WorkingDirectory = WScript.Arguments(3)
>> "%VBS%" echo shortcut.IconLocation = WScript.Arguments(4)
>> "%VBS%" echo shortcut.Description = "Start Nyaarr and open it in your browser"
>> "%VBS%" echo shortcut.Save
cscript //nologo "%VBS%" "%SHORTCUT_PATH%" "%SHORTCUT_TARGET%" "%SHORTCUT_ARGS%" "%PROJECT_ROOT%" "%SHORTCUT_ICON_LOCATION%"
set "VBS_EXIT=%ERRORLEVEL%"
del "%VBS%" >nul 2>nul
if not "%VBS_EXIT%"=="0" (
    echo Failed to create desktop shortcut.
    exit /b 1
)
exit /b 0

:fail
echo.
echo [Nyaarr] Install failed.
exit /b 1
