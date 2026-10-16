@echo off
chcp 65001 > nul
rem ============================================================
rem  スイング株提案ツール 起動ファイル（Windows）
rem  このファイルだけをデスクトップなど好きな場所に置いて使えます。
rem  起動のたびに GitHub から最新版を自動で取り込みます。
rem ============================================================
set "REPO_ZIP=https://github.com/mikan-Tali/stock-search/archive/HEAD.zip"
set "BASE=%LOCALAPPDATA%\stock-search"
set "APP=%BASE%\app"
set "VENV=%BASE%\venv"
set "STOCK_SEARCH_DB=%BASE%\portfolio.db"

python -c "import sys" > nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/downloads/ からインストールしてください。
  echo インストール時に「Add python.exe to PATH」に必ずチェックを入れてください。
  pause
  exit /b
)
if not exist "%BASE%" mkdir "%BASE%"

echo 最新版を確認しています...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';" ^
  "$z=Join-Path $env:BASE 'latest.zip'; $t=Join-Path $env:BASE 'new';" ^
  "Invoke-WebRequest -UseBasicParsing $env:REPO_ZIP -OutFile $z;" ^
  "if (Test-Path $t) { Remove-Item $t -Recurse -Force };" ^
  "Expand-Archive $z $t;" ^
  "$src=(Get-ChildItem $t -Directory | Select-Object -First 1).FullName;" ^
  "if (Test-Path $env:APP) { Remove-Item $env:APP -Recurse -Force };" ^
  "Move-Item $src $env:APP; Remove-Item $t -Recurse -Force; Remove-Item $z"
if errorlevel 1 echo 最新版を取得できませんでした（ネット未接続など）。前回の版で起動します。

if not exist "%APP%\app.py" (
  echo アプリ本体がありません。インターネットに接続してから、もう一度起動してください。
  pause
  exit /b
)

rem 以前のフォルダで使っていた保有データがあれば引き継ぐ
if not exist "%STOCK_SEARCH_DB%" if exist "%~dp0data\portfolio.db" (
  copy "%~dp0data\portfolio.db" "%STOCK_SEARCH_DB%" > nul
  echo 以前の保有データを引き継ぎました。
)

if not exist "%VENV%\Scripts\python.exe" (
  echo 初回セットアップ中です（数分かかります）...
  python -m venv "%VENV%"
)
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "%APP%\requirements.txt"
if errorlevel 1 (
  echo.
  echo セットアップに失敗しました。上のエラーメッセージをスクリーンショットで送ってください。
  pause
  exit /b
)

rem Streamlit 初回起動時のメールアドレス入力を省略する
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" > nul 2>&1
  (echo [general]& echo email = "") > "%USERPROFILE%\.streamlit\credentials.toml"
)

echo ブラウザが自動で開きます。終了するにはこの黒い画面を閉じてください。
cd /d "%APP%"
"%VENV%\Scripts\python.exe" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
