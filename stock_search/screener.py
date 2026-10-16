"""銘柄スクリーニング（候補ユニバースを分析しスコア順に並べる）."""
from __future__ import annotations

import pandas as pd

from .analysis import analyze

# 流動性の高い東証プライム主要銘柄（スイングで売買しやすい大型・中型株）
DEFAULT_UNIVERSE: dict[str, str] = {
    "7203.T": "トヨタ自動車", "6758.T": "ソニーG", "8306.T": "三菱UFJ FG", "9984.T": "ソフトバンクG",
    "6861.T": "キーエンス", "8035.T": "東京エレクトロン", "9432.T": "NTT", "9433.T": "KDDI",
    "6098.T": "リクルートHD", "4063.T": "信越化学", "8316.T": "三井住友FG", "8411.T": "みずほFG",
    "7974.T": "任天堂", "6501.T": "日立製作所", "6367.T": "ダイキン", "4502.T": "武田薬品",
    "4568.T": "第一三共", "9983.T": "ファーストリテイリング", "8058.T": "三菱商事", "8031.T": "三井物産",
    "8001.T": "伊藤忠商事", "8053.T": "住友商事", "2914.T": "JT", "6902.T": "デンソー",
    "7267.T": "ホンダ", "7011.T": "三菱重工", "7012.T": "川崎重工", "7013.T": "IHI",
    "6857.T": "アドバンテスト", "6920.T": "レーザーテック", "6146.T": "ディスコ", "6723.T": "ルネサス",
    "4519.T": "中外製薬", "4661.T": "オリエンタルランド", "6594.T": "ニデック", "6954.T": "ファナック",
    "6273.T": "SMC", "6981.T": "村田製作所", "6762.T": "TDK", "6752.T": "パナソニックHD",
    "6702.T": "富士通", "6701.T": "NEC", "4307.T": "野村総合研究所", "9434.T": "ソフトバンク",
    "8766.T": "東京海上HD", "8725.T": "MS&AD", "8630.T": "SOMPO HD", "8591.T": "オリックス",
    "8604.T": "野村HD", "8801.T": "三井不動産", "8802.T": "三菱地所", "9020.T": "JR東日本",
    "9022.T": "JR東海", "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船",
    "5401.T": "日本製鉄", "5108.T": "ブリヂストン", "4452.T": "花王", "3382.T": "セブン&アイ",
    "2802.T": "味の素", "4543.T": "テルモ", "7741.T": "HOYA", "7751.T": "キヤノン",
    "4901.T": "富士フイルム", "6503.T": "三菱電機", "5803.T": "フジクラ", "6526.T": "ソシオネクスト",
    "1605.T": "INPEX", "5020.T": "ENEOS HD", "8697.T": "日本取引所G", "2413.T": "エムスリー",
    "4385.T": "メルカリ", "3659.T": "ネクソン", "9766.T": "コナミG", "4689.T": "LINEヤフー",
}


def screen(histories: dict[str, pd.DataFrame], names: dict[str, str] | None = None,
           min_turnover: float = 5e8) -> pd.DataFrame:
    """各銘柄を分析し、売買代金フィルタ後にスコア降順で返す.

    min_turnover: 20日平均売買代金の下限（円）。流動性の低い銘柄はスイングでも滑りやすいため除外。
    """
    names = names or {}
    rows = []
    for t, df in histories.items():
        a = analyze(t, df)
        if a is None:
            continue
        turnover = float((df["Close"] * df["Volume"]).tail(20).mean())
        if t.endswith(".T") and turnover < min_turnover:
            continue
        rows.append({
            "ticker": t, "name": names.get(t, ""), "price": a.price, "score": a.score, "signal": a.signal,
            "setup": a.setup, "trend": a.trend, "RSI": a.rsi, "3か月騰落": a.ret60, "1か月騰落": a.ret20,
            "52週高値比": a.dist_52w_high, "ATR%": a.atr_pct, "出来高倍率": a.vol_ratio,
            "損切り": a.stop, "目標1": a.target1, "目標2": a.target2, "売買代金(億)": turnover / 1e8,
            "根拠": " / ".join(a.reasons), "リスク": " / ".join(a.risks),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
