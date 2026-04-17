@echo off
chcp 65001 > nul
echo === Step 1: GitHubから最新コードを取得 ===
git pull origin claude/eclipse-hci-gui-app-87wtD
echo.
echo === Step 2: 最新のbuild_exe.batでビルド ===
call build_exe.bat
