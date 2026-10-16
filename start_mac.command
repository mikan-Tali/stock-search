#!/bin/bash
# スイング株提案ツール 起動ファイル（Mac）
# このファイルだけを好きな場所に置いて使えます。起動のたびに GitHub から最新版を取り込みます。
REPO_ZIP="https://github.com/mikan-Tali/stock-search/archive/HEAD.zip"
BASE="$HOME/Library/Application Support/stock-search"
APP="$BASE/app"
VENV="$BASE/venv"
export STOCK_SEARCH_DB="$BASE/portfolio.db"
HERE="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python が見つかりません。https://www.python.org/downloads/ からインストールしてください。"
  read -p "Enter キーで閉じます"
  exit 1
fi
mkdir -p "$BASE"

echo "最新版を確認しています..."
TMP="$BASE/new"
rm -rf "$TMP" && mkdir -p "$TMP"
if curl -fsSL "$REPO_ZIP" -o "$BASE/latest.zip" && unzip -q "$BASE/latest.zip" -d "$TMP"; then
  rm -rf "$APP" && mv "$TMP"/*/ "$APP"
else
  echo "最新版を取得できませんでした。前回の版で起動します。"
fi
rm -rf "$TMP" "$BASE/latest.zip"

if [ ! -f "$APP/app.py" ]; then
  echo "アプリ本体がありません。インターネットに接続してから、もう一度起動してください。"
  read -p "Enter キーで閉じます"
  exit 1
fi

if [ ! -f "$STOCK_SEARCH_DB" ] && [ -f "$HERE/data/portfolio.db" ]; then
  cp "$HERE/data/portfolio.db" "$STOCK_SEARCH_DB"
  echo "以前の保有データを引き継ぎました。"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "初回セットアップ中です（数分かかります）..."
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --disable-pip-version-check -r "$APP/requirements.txt" || {
  echo "セットアップに失敗しました。上のエラーメッセージをスクリーンショットで送ってください。"
  read -p "Enter キーで閉じます"
  exit 1
}

if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  mkdir -p "$HOME/.streamlit"
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo "ブラウザが自動で開きます。終了するにはこのウィンドウを閉じてください。"
cd "$APP"
"$VENV/bin/python" -m streamlit run app.py --browser.gatherUsageStats false
