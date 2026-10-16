import numpy as np
import pandas as pd
import pytest


def make_ohlcv(n=300, drift=0.001, vol=0.015, start=1000.0, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    volume = rng.integers(1_000_000, 3_000_000, n).astype(float)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


@pytest.fixture
def uptrend():
    return make_ohlcv(drift=0.003, seed=1)


@pytest.fixture
def downtrend():
    return make_ohlcv(drift=-0.003, seed=2)
