@echo off
echo ==========================================
echo  EHX Crosspoint Controller - Build
echo ==========================================
echo.

set BRANCH=claude/eclipse-hci-gui-app-87wtD
set REPO=choco-bananas/choco-bananas

if not exist "pat.txt" (
    echo ERROR: pat.txt not found.
    echo Please create pat.txt with your GitHub PAT on the first line.
    pause
    exit /b 1
)
set /p PAT=<pat.txt

echo [1/4] Downloading eclipse_hci_gui.py ...
curl -s -H "Authorization: token %PAT%" -L -o eclipse_hci_gui.py "https://raw.githubusercontent.com/%REPO%/%BRANCH%/eclipse_hci_gui.py"
if errorlevel 1 (
    echo ERROR: Download failed.
    pause
    exit /b 1
)
echo Done.
echo.

echo [2/4] Removing old build ...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec
echo.

echo [3/4] Checking PyInstaller ...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller ...
    pip install pyinstaller
)
echo.

echo [4/4] Building EXE ...
pyinstaller --onefile --windowed --clean --name "EHX_Crosspoint_Controller" eclipse_hci_gui.py
echo.

if exist "dist\EHX_Crosspoint_Controller.exe" (
    echo ==========================================
    echo  Build complete: EHX_Crosspoint_Controller.exe
    echo ==========================================
    start explorer dist
) else (
    echo Build failed. Check errors above.
)
pause
