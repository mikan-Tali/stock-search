"""Claude API による総合提案（任意機能。ANTHROPIC_API_KEY が必要）.

テクニカル分析・保有状況・地合いのデータを渡し、1〜3か月のスイングトレード前提で
「何を・いくらで・何株・どこで損切り/利確するか」を日本語で提案させる。
web_search ツールで直近のニュースや決算予定も確認させる。
"""
from __future__ import annotations

import json
import os

MODEL = os.environ.get("STOCK_SEARCH_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = """あなたは日本株を中心とした個別株スイングトレード（保有期間1〜3か月）のアドバイザーです。
ユーザーの資産運用の主軸は投資信託で、個別株はリターン上積みのためのサテライト枠です。
自動売買はせず、ユーザーが提案を読んで自分で発注します。

渡されるデータ（保有銘柄、テクニカル分析、スクリーニング上位、地合い、リスク設定）を根拠に、以下を日本語で提案してください。
必要に応じて web_search で直近のニュース・決算発表日・材料を確認し、決算跨ぎになる銘柄は明記してください。

出力フォーマット（Markdown）:
1. 地合いの要約（2〜3行）
2. 保有銘柄へのアクション（銘柄ごとに: 継続/利確/損切り/買い増し、理由、損切り・利確価格の更新案）
3. 新規エントリー候補（最大3銘柄。各銘柄: エントリー価格帯、損切り、目標1/目標2、株数（リスク設定に基づく）、根拠、主なリスク、想定保有期間）
4. ポートフォリオ全体の注意点（集中・相関・レバレッジ）
5. 信用取引（レバレッジ）を使う場合の条件と上限の目安

ルール:
- 数値はデータに基づかせ、推測の場合はそう書く。
- 1トレードの損失は設定された許容リスク（資金比%）以内に収める株数を示す。
- レバレッジは地合いが強気でかつ損切りを厳守できる場合のみ、設定上限以内で提案する。
- 最後に「投資判断はご自身で。本提案は情報提供であり利益を保証しません」と一言添える。"""


def is_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _to_jsonable(obj):
    import math

    import pandas as pd

    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _to_jsonable(obj.to_dict("records"))
    if isinstance(obj, pd.Series):
        return _to_jsonable(obj.to_dict())
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "item"):
        return _to_jsonable(obj.item())
    return obj


def generate_advice(context: dict, user_note: str = "", use_web_search: bool = True) -> str:
    """分析コンテキストを渡して提案文（Markdown）を返す."""
    import anthropic

    client = anthropic.Anthropic()
    payload = json.dumps(_to_jsonable(context), ensure_ascii=False, indent=1)
    text = f"以下が現在のデータです。\n\n```json\n{payload}\n```"
    if user_note:
        text += f"\n\nユーザーからの補足: {user_note}"
    messages: list[dict] = [{"role": "user", "content": text}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}] if use_web_search else []

    response = None
    for _ in range(4):  # web_search の長いターンは pause_turn で中断されるので継続する
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            tools=tools,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    if response is None:
        return "応答がありませんでした。"
    if response.stop_reason == "refusal":
        return "モデルが回答を辞退しました。条件を変えて再度お試しください。"
    parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    return "".join(parts).strip() or "応答テキストがありませんでした。"
