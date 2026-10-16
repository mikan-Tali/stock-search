#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python が見つかりません。https://www.python.org/downloads/ からインストールしてください。"
  read -p "Enter キーで閉じます"
  exit 1
fi
if [ ! -d .venv ]; then
  echo "初回セットアップ中です（数分かかります）..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  mkdir -p "$HOME/.streamlit"
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi
echo "ブラウザが自動で開きます。終了するにはこのウィンドウを閉じてください。"
streamlit run app.py
