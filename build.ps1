$pat = (Get-Content "pat.txt" -First 1).Trim()
$headers = @{ Authorization = "token $pat" }
$url = "https://raw.githubusercontent.com/choco-bananas/choco-bananas/claude/eclipse-hci-gui-app-87wtD/eclipse_hci_gui.py"

Write-Host "[1/4] Downloading eclipse_hci_gui.py ..."
Invoke-WebRequest -Uri $url -Headers $headers -OutFile "eclipse_hci_gui.py"
Write-Host "Done."

Write-Host "[2/4] Removing old build ..."
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Force *.spec -ErrorAction SilentlyContinue

Write-Host "[3/4] Checking PyInstaller ..."
pip show pyinstaller 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller ..."
    pip install pyinstaller
}

Write-Host "[4/4] Building EXE ..."
pyinstaller --onefile --windowed --clean --name "EHX_Crosspoint_Controller" eclipse_hci_gui.py

if (Test-Path "dist\EHX_Crosspoint_Controller.exe") {
    Write-Host "Build complete: EHX_Crosspoint_Controller.exe"
    Start-Process explorer dist
} else {
    Write-Host "Build failed. Check errors above."
}
Read-Host "Press Enter to exit"
