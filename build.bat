@echo off
setlocal EnableExtensions

set "NO_PAUSE="
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"

set "PROJECT_DIR=%~dp0"
set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
set "BASE_PY=python"
set "BUILD_EXIT=1"

pushd "%PROJECT_DIR%"

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "BASE_PY=py -3.12"

%BASE_PY% -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12 was not found. Install it and add it to PATH or the Python launcher.
    goto :finish
)

if not exist "%VENV_PY%" (
    echo [INFO] Creating the project virtual environment...
    %BASE_PY% -m venv "%PROJECT_DIR%.venv"
    if errorlevel 1 (
        echo [ERROR] Could not create .venv.
        goto :finish
    )
)

"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The Python in .venv is not version 3.12. Remove .venv and run this script again.
    goto :finish
)

echo [INFO] Installing build dependencies...
"%VENV_PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Could not install build dependencies.
    goto :finish
)

echo [INFO] Generating the application icon...
"%VENV_PY%" tools\make_icon.py halo.ico
if errorlevel 1 (
    echo [ERROR] Icon generation failed.
    goto :finish
)

echo [INFO] Generating Windows version information...
"%VENV_PY%" tools\make_version.py version_info.txt
if errorlevel 1 (
    echo [ERROR] Version information generation failed.
    goto :finish
)

echo [INFO] Clearing previous build contents in dist...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $dist = Join-Path (Get-Location) 'dist'; if (-not (Test-Path -LiteralPath $dist)) { New-Item -ItemType Directory -Path $dist | Out-Null }; Get-ChildItem -LiteralPath $dist -Force | Remove-Item -Recurse -Force"
if errorlevel 1 (
    echo [ERROR] Could not clear the existing contents of dist.
    goto :finish
)

echo [INFO] Building HaloBattery...
"%VENV_PY%" -m PyInstaller --noconfirm --onedir --windowed --noupx --name HaloBattery --icon halo.ico --version-file version_info.txt --hidden-import hid --hidden-import pystray._win32 halo_battery.pyw
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    goto :finish
)

echo [INFO] Creating the versioned ZIP archive in dist...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $line = (Select-String -Path 'halo_battery.pyw' -Pattern '^\s*VERSION\s*=\s*').Line; if (-not $line) { throw 'VERSION was not found' }; $version = $line.Split([char]34)[1]; if (-not $version) { throw 'VERSION could not be read' }; $zip = Join-Path 'dist' ('HaloBattery_v' + $version + '.zip'); Compress-Archive -Path 'dist\HaloBattery' -DestinationPath $zip -Force; Write-Host ('[OK] Created ' + $zip)"
if errorlevel 1 (
    echo [ERROR] ZIP archive creation failed.
    goto :finish
)

echo [OK] Build complete. ZIP and executable are in dist.
set "BUILD_EXIT=0"

:finish
popd
if not defined NO_PAUSE pause
endlocal & exit /b %BUILD_EXIT%
