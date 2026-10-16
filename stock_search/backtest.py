"""シグナルの簡易バックテスト（過去データで「この手法は機能していたか」を確認する）."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .analysis import analyze


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    win_rate: float
    avg_r: float
    expectancy_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    n_trades: int


def backtest(ticker: str, df: pd.DataFrame, entry_score: float = 40, max_hold_days: int = 60,
             step: int = 1, warmup: int = 120) -> BacktestResult:
    """スコアが entry_score 以上で翌日始値エントリー。損切り / 目標2 / 最大保有日数で手仕舞い.

    同時に 1 ポジションのみ。手数料・スリッページは考慮しない簡易版。
    """
    trades = []
    i = warmup
    n = len(df)
    while i < n - 1:
        a = analyze(ticker, df.iloc[: i + 1])
        if a is None or a.score < entry_score:
            i += step
            continue
        entry_idx = i + 1
        entry = float(df["Open"].iloc[entry_idx])
        risk = entry - a.stop
        if risk <= 0:
            i += step
            continue
        stop, target = entry - risk, entry + 3 * risk
        exit_price, exit_idx, why = None, None, ""
        for j in range(entry_idx, min(entry_idx + max_hold_days, n)):
            lo, hi = float(df["Low"].iloc[j]), float(df["High"].iloc[j])
            if lo <= stop:
                exit_price, exit_idx, why = stop, j, "損切り"
                break
            if hi >= target:
                exit_price, exit_idx, why = target, j, "目標到達"
                break
        if exit_price is None:
            exit_idx = min(entry_idx + max_hold_days, n) - 1
            exit_price, why = float(df["Close"].iloc[exit_idx]), "期間満了"
        trades.append({
            "entry_date": df.index[entry_idx], "exit_date": df.index[exit_idx], "entry": entry,
            "exit": exit_price, "return_pct": (exit_price / entry - 1) * 100,
            "R": (exit_price - entry) / risk, "exit_reason": why, "score": a.score,
        })
        i = exit_idx + 1
    t = pd.DataFrame(trades)
    if t.empty:
        return BacktestResult(t, np.nan, np.nan, np.nan, 0.0, 0.0, 0)
    equity = (1 + t["return_pct"] / 100).cumprod()
    dd = (equity / equity.cummax() - 1).min() * 100
    return BacktestResult(
        trades=t, win_rate=float((t["return_pct"] > 0).mean() * 100), avg_r=float(t["R"].mean()),
        expectancy_pct=float(t["return_pct"].mean()), total_return_pct=float((equity.iloc[-1] - 1) * 100),
        max_drawdown_pct=float(dd), n_trades=len(t),
    )
