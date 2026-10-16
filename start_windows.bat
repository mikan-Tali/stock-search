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
if not exist .venv (
  echo 初回セットアップ中です（数分かかります）...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo ブラウザが自動で開きます。終了するにはこの黒い画面を閉じてください。
streamlit run app.py
pause
