@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -c "import sys" > nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/downloads/ からインストールしてください。
  echo インストール時に「Add python.exe to PATH」に必ずチェックを入れてください。
  pause
  exit /b
)

rem Windows のパス長制限（260文字）を避けるため、仮想環境は短い場所に作る
set "VENV=%LOCALAPPDATA%\stock-search\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo 初回セットアップ中です（数分かかります）...
  python -m venv "%VENV%"
)
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo セットアップに失敗しました。上のエラーメッセージをスクリーンショットで送ってください。
  pause
  exit /b
)
echo ブラウザが自動で開きます。終了するにはこの黒い画面を閉じてください。
"%VENV%\Scripts\python.exe" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
