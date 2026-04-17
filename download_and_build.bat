@echo off
chcp 65001 > nul
echo ==========================================
echo  EHX Crosspoint Controller - ダウンロード＆ビルド
echo ==========================================
echo.

set BRANCH=claude/eclipse-hci-gui-app-87wtD
set REPO=choco-bananas/choco-bananas

rem PAT を pat.txt から読み込む (1行目がトークン)
if not exist "pat.txt" (
    echo エラー: pat.txt が見つかりません。
    echo pat.txt に GitHub Personal Access Token を1行で書いて保存してください。
    pause
    exit /b 1
)
set /p PAT=<pat.txt

echo [1/4] 最新の eclipse_hci_gui.py をダウンロード中...
curl -s -H "Authorization: token %PAT%" -L -o eclipse_hci_gui.py "https://raw.githubusercontent.com/%REPO%/%BRANCH%/eclipse_hci_gui.py"
if errorlevel 1 (
    echo エラー: eclipse_hci_gui.py のダウンロードに失敗しました
    pause
    exit /b 1
)
echo OK: eclipse_hci_gui.py を更新しました
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
