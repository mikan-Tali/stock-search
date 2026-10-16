import numpy as np
import pandas as pd

from stock_search.indicators import add_indicators, atr, rsi, sma


def test_sma_simple():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert rsi(up).iloc[-1] == 100.0
    down = pd.Series(np.arange(50, 1, -1, dtype=float))
    assert rsi(down).iloc[-1] < 1


def test_atr_positive(uptrend):
    a = atr(uptrend).dropna()
    assert (a > 0).all()


def test_add_indicators_columns(uptrend):
    d = add_indicators(uptrend)
    for col in ["SMA25", "SMA75", "RSI14", "MACD", "BB_upper", "ATR14", "Ret60"]:
        assert col in d and not np.isnan(d[col].iloc[-1])
