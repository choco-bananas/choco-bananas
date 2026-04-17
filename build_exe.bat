@echo off
chcp 65001 > nul
echo === Clear-Com Eclipse HCI Controller - EXE ビルド ===
echo.

echo 古いビルドを削除中...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "Eclipse_HCI_Controller.spec" del /q Eclipse_HCI_Controller.spec

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller をインストール中...
    pip install pyinstaller
)

echo EXE をビルド中...
pyinstaller --onefile --windowed --clean --name "Eclipse_HCI_Controller" eclipse_hci_gui.py
echo.
if exist "dist\Eclipse_HCI_Controller.exe" (
    echo 完了! dist\Eclipse_HCI_Controller.exe を確認してください
    start explorer dist
) else (
    echo ビルド失敗。上のエラーを確認してください。
)
pause
