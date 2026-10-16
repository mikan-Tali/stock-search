"""テクニカル指標の計算（pandas のみで実装）."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(avg_loss != 0, 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, window: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.rolling(window, min_periods=window).std()
    return pd.DataFrame({"mid": mid, "upper": mid + k * std, "lower": mid - k * std})


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV の DataFrame に主要指標の列を追加して返す."""
    out = df.copy()
    close = out["Close"]
    out["SMA5"] = sma(close, 5)
    out["SMA25"] = sma(close, 25)
    out["SMA75"] = sma(close, 75)
    out["RSI14"] = rsi(close, 14)
    m = macd(close)
    out["MACD"], out["MACD_signal"], out["MACD_hist"] = m["macd"], m["signal"], m["hist"]
    b = bollinger(close)
    out["BB_upper"], out["BB_mid"], out["BB_lower"] = b["upper"], b["mid"], b["lower"]
    out["ATR14"] = atr(out, 14)
    out["VolMA20"] = out["Volume"].rolling(20, min_periods=20).mean()
    out["Ret20"] = close.pct_change(20)
    out["Ret60"] = close.pct_change(60)
    return out
