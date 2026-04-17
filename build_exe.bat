@echo off
chcp 65001 > nul
echo ==========================================
echo  EHX Crosspoint Controller - EXE ビルド
echo ==========================================
echo.

echo [1/4] GitHubから最新コードを取得中...
git pull origin claude/eclipse-hci-gui-app-87wtD
if errorlevel 1 (
    echo 警告: git pull に失敗しました。ローカルのファイルでビルドします。
)
echo.

echo [2/4] 古いビルドを削除中...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec
echo.

echo [3/4] PyInstaller を確認中...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller をインストール中...
    pip install pyinstaller
)
echo.

echo [4/4] EXE をビルド中...
pyinstaller --onefile --windowed --clean --name "EHX_Crosspoint_Controller" eclipse_hci_gui.py
echo.

if exist "dist\EHX_Crosspoint_Controller.exe" (
    echo ==========================================
    echo  完了! EHX_Crosspoint_Controller.exe
    echo ==========================================
    start explorer dist
) else (
    echo ビルド失敗。上のエラーを確認してください。
)
pause
