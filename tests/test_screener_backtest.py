from stock_search.backtest import backtest
from stock_search.screener import screen


def test_screen_orders_by_score(uptrend, downtrend):
    res = screen({"UP.T": uptrend, "DN.T": downtrend}, min_turnover=0)
    assert list(res["ticker"]) == ["UP.T", "DN.T"]


def test_screen_liquidity_filter(uptrend):
    assert screen({"UP.T": uptrend}, min_turnover=1e15).empty


def test_backtest_runs(uptrend):
    res = backtest("UP.T", uptrend, entry_score=20, step=5)
    assert res.n_trades >= 1
    assert set(res.trades["exit_reason"]) <= {"損切り", "目標到達", "期間満了"}
