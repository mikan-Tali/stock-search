"""スイングトレード（1〜3か月）向けの銘柄分析・売買計画・保有銘柄レビュー."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .indicators import add_indicators
from .market import lot_size

# 保有期間 1〜3 か月を想定した損切り・利確幅（ATR 倍数）
STOP_ATR = 2.0
TARGET1_ATR = 4.0   # リスクリワード 1:2
TARGET2_ATR = 6.0   # リスクリワード 1:3
TRAIL_ATR = 2.5


@dataclass
class StockAnalysis:
    ticker: str
    price: float
    score: float                      # -100〜+100
    signal: str                       # 強い買い / 買い / 中立 / 売り / 強い売り
    setup: str                        # 押し目買い / ブレイクアウト など
    trend: str
    rsi: float
    atr: float
    atr_pct: float
    ret20: float
    ret60: float
    vol_ratio: float
    dist_52w_high: float
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    stop: float = math.nan
    target1: float = math.nan
    target2: float = math.nan

    def to_dict(self) -> dict:
        return asdict(self)


def _signal_label(score: float) -> str:
    if score >= 50:
        return "強い買い"
    if score >= 20:
        return "買い"
    if score <= -50:
        return "強い売り"
    if score <= -20:
        return "売り"
    return "中立"


def analyze(ticker: str, df: pd.DataFrame, live_price: float | None = None) -> StockAnalysis | None:
    """日足 OHLCV（最低 80 本程度）から総合スコアと売買計画を算出する."""
    if df is None or len(df) < 80:
        return None
    d = add_indicators(df)
    last, prev = d.iloc[-1], d.iloc[-2]
    price = float(live_price) if live_price else float(last["Close"])
    atr = float(last["ATR14"])
    reasons: list[str] = []
    risks: list[str] = []
    score = 0.0

    # --- トレンド（最大 ±35）
    sma25, sma75 = float(last["SMA25"]), float(last["SMA75"])
    sma25_slope = float(d["SMA25"].iloc[-1] / d["SMA25"].iloc[-6] - 1)
    if price > sma25 > sma75 and sma25_slope > 0:
        trend = "上昇トレンド"
        score += 35
        reasons.append("株価 > 25日線 > 75日線、25日線も上向きの上昇トレンド")
    elif price < sma25 < sma75 and sma25_slope < 0:
        trend = "下降トレンド"
        score -= 35
        risks.append("株価 < 25日線 < 75日線の下降トレンド")
    elif price > sma75:
        trend = "もみ合い（上寄り）"
        score += 10
    else:
        trend = "もみ合い（下寄り）"
        score -= 10

    # --- モメンタム（最大 ±20）
    ret20 = float(last["Ret20"]) if not np.isnan(last["Ret20"]) else 0.0
    ret60 = float(last["Ret60"]) if not np.isnan(last["Ret60"]) else 0.0
    mom = np.clip(ret60 * 100, -20, 20) * 0.6 + np.clip(ret20 * 100, -15, 15) * 0.5
    score += float(np.clip(mom, -20, 20))
    if ret60 > 0.15:
        reasons.append(f"直近3か月 +{ret60:.0%} と強いモメンタム")
    elif ret60 < -0.15:
        risks.append(f"直近3か月 {ret60:.0%} と弱いモメンタム")

    # --- MACD（最大 ±15）
    if last["MACD"] > last["MACD_signal"] and prev["MACD"] <= prev["MACD_signal"]:
        score += 15
        reasons.append("MACD がゴールデンクロス（直近）")
    elif last["MACD"] < last["MACD_signal"] and prev["MACD"] >= prev["MACD_signal"]:
        score -= 15
        risks.append("MACD がデッドクロス（直近）")
    elif last["MACD_hist"] > 0 and last["MACD_hist"] > prev["MACD_hist"]:
        score += 7
    elif last["MACD_hist"] < 0 and last["MACD_hist"] < prev["MACD_hist"]:
        score -= 7

    # --- RSI（過熱・売られすぎ、最大 ±15）
    rsi = float(last["RSI14"])
    if rsi >= 80:
        score -= 15
        risks.append(f"RSI {rsi:.0f}：短期的に過熱（高値掴みに注意）")
    elif rsi >= 70:
        score -= 5
        risks.append(f"RSI {rsi:.0f}：やや過熱")
    elif rsi <= 25:
        score += 10
        reasons.append(f"RSI {rsi:.0f}：売られすぎ（リバウンド候補）")
    elif trend == "上昇トレンド" and 40 <= rsi <= 55:
        score += 10
        reasons.append(f"上昇トレンド中に RSI {rsi:.0f} まで調整（押し目）")

    # --- 出来高（最大 +10）
    vol_ratio = float(last["Volume"] / last["VolMA20"]) if last["VolMA20"] else 1.0
    if vol_ratio >= 2 and price > float(prev["Close"]):
        score += 10
        reasons.append(f"出来高が20日平均の {vol_ratio:.1f} 倍で上昇（資金流入）")
    elif vol_ratio >= 2 and price < float(prev["Close"]):
        score -= 10
        risks.append(f"出来高 {vol_ratio:.1f} 倍を伴う下落（売り圧力）")

    # --- 52週高値との距離
    high_52w = float(d["High"].tail(250).max())
    dist_high = price / high_52w - 1
    low_20 = float(d["Low"].tail(20).min())

    # --- セットアップ判定
    near_mid = abs(price / sma25 - 1) < 0.03
    if dist_high > -0.03 and vol_ratio >= 1.5 and trend.startswith("上昇"):
        setup = "ブレイクアウト（高値更新）"
        score += 5
    elif trend == "上昇トレンド" and near_mid and rsi < 60:
        setup = "押し目買い（25日線付近）"
        score += 5
    elif rsi <= 30 and price <= float(last["BB_lower"]) * 1.01:
        setup = "リバウンド狙い（逆張り）"
        risks.append("逆張りは下落トレンド継続のリスクあり。小さめのポジションで")
    elif trend == "下降トレンド":
        setup = "様子見 / 空売り候補"
    else:
        setup = "明確なセットアップなし"

    atr_pct = atr / price
    if atr_pct > 0.05:
        risks.append(f"日々の値動きが大きい（ATR {atr_pct:.1%}）→ 株数を抑える")

    score = float(np.clip(score, -100, 100))

    # --- 売買計画（買いの場合）
    stop = max(price - STOP_ATR * atr, low_20 - 0.5 * atr) if score >= 0 else price + STOP_ATR * atr
    if score >= 0 and price - stop < 1.0 * atr:  # 直近安値が近すぎる場合は最低 1ATR 確保
        stop = price - 1.0 * atr
    risk_per_share = abs(price - stop)
    sign = 1 if score >= 0 else -1
    target1 = price + sign * 2 * risk_per_share
    target2 = price + sign * 3 * risk_per_share

    return StockAnalysis(
        ticker=ticker, price=price, score=round(score, 1), signal=_signal_label(score), setup=setup,
        trend=trend, rsi=round(rsi, 1), atr=atr, atr_pct=atr_pct, ret20=ret20, ret60=ret60,
        vol_ratio=round(vol_ratio, 2), dist_52w_high=dist_high, reasons=reasons, risks=risks,
        stop=round(stop, 1), target1=round(target1, 1), target2=round(target2, 1),
    )


@dataclass
class PositionSize:
    shares: int
    cost: float
    risk_amount: float
    risk_pct_of_capital: float
    position_pct_of_capital: float
    needs_margin: bool
    note: str


def position_size(ticker: str, entry: float, stop: float, capital: float, risk_pct: float = 1.0,
                  max_position_pct: float = 25.0, max_leverage: float = 1.0) -> PositionSize:
    """許容損失額から株数を計算（固定リスク法）。単元（100株）に丸める."""
    lot = lot_size(ticker)
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0 or entry <= 0:
        return PositionSize(0, 0, 0, 0, 0, False, "損切り価格が不正です")
    risk_budget = capital * risk_pct / 100
    by_risk = risk_budget / risk_per_share
    by_cap = capital * max_position_pct / 100 * max_leverage / entry
    raw = min(by_risk, by_cap)
    shares = int(raw // lot * lot)
    note = ""
    if shares == 0:
        min_cost = entry * lot
        note = (f"資金・リスク条件では1単元（{lot}株＝約{min_cost:,.0f}円）に届きません。"
                "単元未満株（S株・ミニ株）での購入を検討してください。")
        shares = int(raw) if lot > 1 else 0
    cost = shares * entry
    risk_amount = shares * risk_per_share
    return PositionSize(
        shares=shares, cost=cost, risk_amount=risk_amount,
        risk_pct_of_capital=risk_amount / capital * 100 if capital else 0,
        position_pct_of_capital=cost / capital * 100 if capital else 0,
        needs_margin=cost > capital * max_position_pct / 100, note=note,
    )


def review_holding(row: dict, a: StockAnalysis | None, price: float) -> dict:
    """保有銘柄ごとのアクション提案（保有継続 / 利確 / 損切り / 買い増し）."""
    side = 1 if row.get("side", "買い") == "買い" else -1
    avg = float(row["avg_price"])
    shares = float(row["shares"])
    pnl = side * (price - avg) * shares
    pnl_pct = side * (price / avg - 1) * 100
    stop = row.get("stop_loss")
    stop = float(stop) if stop is not None and not pd.isna(stop) else (a.stop if a and side == 1 else None)
    target = row.get("take_profit")
    target = float(target) if target is not None and not pd.isna(target) else None

    action, why = "保有継続", []
    trail = None
    if a is not None:
        trail = price - TRAIL_ATR * a.atr if side == 1 else price + TRAIL_ATR * a.atr
    if side == 1 and stop is not None and price <= stop:
        action = "損切り"
        why.append(f"損切りライン {stop:,.1f} を割り込み")
    elif side == -1 and stop is not None and price >= stop:
        action = "損切り"
        why.append(f"損切りライン {stop:,.1f} を上抜け")
    elif target is not None and side * (price - target) >= 0:
        action = "利確検討"
        why.append(f"目標株価 {target:,.1f} に到達")
    elif a is not None:
        if side == 1 and a.trend == "下降トレンド":
            action = "売却検討"
            why.append("下降トレンド入り。スイングの前提が崩れている")
        elif side == 1 and a.rsi >= 78 and pnl_pct > 10:
            action = "一部利確"
            why.append(f"RSI {a.rsi:.0f} と過熱、含み益 {pnl_pct:.1f}%")
        elif side == 1 and a.score >= 40 and pnl_pct > 0:
            action = "買い増し候補"
            why.append("上昇トレンド継続中で含み益。押し目での追加を検討")
        elif side == 1 and a.score <= -20:
            action = "売却検討"
            why.append(f"総合スコア {a.score:+.0f} と弱い")
    if action == "保有継続" and not why:
        why.append("前提に大きな変化なし")
    if trail is not None and side == 1 and pnl_pct > 5 and (stop is None or trail > stop):
        why.append(f"利益確保のため損切りを {trail:,.0f} へ引き上げ（トレーリングストップ）を推奨")
    return {
        "action": action, "reasons": why, "pnl": pnl, "pnl_pct": pnl_pct, "stop": stop,
        "trail_stop": trail, "market_value": price * shares,
    }


def portfolio_risk(holdings: pd.DataFrame, prices: dict[str, float], histories: dict[str, pd.DataFrame],
                   benchmark: pd.DataFrame | None, capital: float) -> dict:
    """ポートフォリオ全体の集中度・相関・β・レバレッジ等."""
    if holdings.empty:
        return {}
    h = holdings.copy()
    h["price"] = h["ticker"].map(prices)
    h = h.dropna(subset=["price"])
    sign = np.where(h["side"] == "買い", 1, -1)
    h["mv"] = h["price"] * h["shares"]
    h["exposure"] = sign * h["mv"]
    gross = float(h["mv"].sum())
    net = float(h["exposure"].sum())
    weights = (h.groupby("ticker")["exposure"].sum() / gross) if gross else pd.Series(dtype=float)

    rets = pd.DataFrame({t: histories[t]["Close"].pct_change() for t in weights.index if t in histories}).dropna(how="all").tail(126)
    corr = rets.corr() if rets.shape[1] >= 2 else pd.DataFrame()
    port_ret = (rets.fillna(0) * weights.reindex(rets.columns).fillna(0)).sum(axis=1) if not rets.empty else pd.Series(dtype=float)
    vol = float(port_ret.std() * np.sqrt(250)) if len(port_ret) > 20 else math.nan
    beta = math.nan
    if benchmark is not None and len(port_ret) > 20:
        b = benchmark["Close"].pct_change().reindex(port_ret.index).dropna()
        pr = port_ret.reindex(b.index)
        if b.var() > 0:
            beta = float(np.cov(pr, b)[0, 1] / b.var())

    high_corr = []
    if not corr.empty:
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b_ in cols[i + 1:]:
                if corr.loc[a, b_] >= 0.7:
                    high_corr.append((a, b_, float(corr.loc[a, b_])))

    margin_mv = float(h.loc[h["account"].str.startswith("信用"), "mv"].sum())
    return {
        "gross": gross, "net": net,
        "leverage": gross / capital if capital else math.nan,
        "margin_mv": margin_mv,
        "weights": weights.sort_values(ascending=False),
        "max_weight": float(weights.abs().max()) if len(weights) else 0.0,
        "corr": corr, "high_corr_pairs": high_corr,
        "volatility": vol, "beta": beta,
    }


def market_regime(index_df: pd.DataFrame | None, vix_df: pd.DataFrame | None = None) -> dict:
    """地合い判定。リスクオフ時はポジションサイズを落とす係数を返す."""
    if index_df is None or len(index_df) < 200:
        return {"label": "不明", "size_factor": 1.0, "notes": []}
    close = index_df["Close"]
    sma200 = close.rolling(200).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    last = close.iloc[-1]
    notes = []
    if last > sma50 > sma200:
        label, factor = "強気（リスクオン）", 1.0
        notes.append("指数が50日線・200日線の上。積極的にエントリー可")
    elif last > sma200:
        label, factor = "中立", 0.75
        notes.append("指数は200日線の上だが短期は調整。サイズはやや控えめに")
    else:
        label, factor = "弱気（リスクオフ）", 0.5
        notes.append("指数が200日線の下。新規買いは半分のサイズ、またはキャッシュ比率を高めに")
    if vix_df is not None and not vix_df.empty:
        vix = float(vix_df["Close"].iloc[-1])
        if vix >= 30:
            factor *= 0.5
            notes.append(f"VIX {vix:.0f}：市場の不安が高い。レバレッジは避ける")
        elif vix >= 20:
            factor *= 0.8
            notes.append(f"VIX {vix:.0f}：やや警戒")
    return {"label": label, "size_factor": factor, "notes": notes}
