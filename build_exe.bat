@echo off
chcp 65001 > nul
echo === Clear-Com Eclipse HCI Controller - EXE ビルド ===
echo.
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller をインストール中...
    pip install pyinstaller
)
echo EXE をビルド中...
pyinstaller --onefile --windowed --name "Eclipse_HCI_Controller" eclipse_hci_gui.py
echo.
if exist "dist\Eclipse_HCI_Controller.exe" (
    echo 完了! dist\Eclipse_HCI_Controller.exe を確認してください
    start explorer dist
) else (
    echo ビルド失敗。上のエラーを確認してください。
)
pause
