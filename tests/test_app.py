"""Streamlit アプリ全体のスモークテスト（ネットワークを使わず偽データで描画）."""
from datetime import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from stock_search import market
from tests.conftest import make_ohlcv


class FakeMarket:
    def __init__(self):
        pass

    def history(self, ticker, period="1y", interval="1d"):
        return make_ohlcv(n=400, drift=0.002, seed=abs(hash(ticker)) % 1000)

    def histories(self, tickers, period="1y"):
        return {t: self.history(t) for t in tickers}

    def quotes(self, tickers):
        out = {}
        for t in tickers:
            df = self.history(t)
            p, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
            out[t] = market.Quote(t, p, prev, p - prev, (p / prev - 1) * 100, p * 1.01, p * 0.99, 1e6, datetime.now())
        return out

    def profile(self, ticker):
        return {"shortName": f"Fake {ticker}"}

    def next_earnings(self, ticker):
        return None


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_SEARCH_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(market, "MarketData", FakeMarket)
    import streamlit as st

    import stock_search.portfolio as pf
    st.cache_resource.clear()
    st.cache_data.clear()
    pf.PortfolioStore(tmp_path / "t.db").add_holding("7203.T", 100, 900, stop_loss=850)
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)
    return at


def test_app_renders_without_errors(app):
    app.run()
    assert not app.exception, app.exception
    # 保有銘柄のアクション提案表が描画されている
    assert len(app.dataframe) >= 2


def test_screener_button(app):
    app.run()
    app.button[[b.label for b in app.button].index("スクリーニング実行")].click().run()
    assert not app.exception, app.exception


def test_backtest_button(app):
    app.run()
    app.button[[b.label for b in app.button].index("バックテスト実行")].click().run()
    assert not app.exception, app.exception
