import pytest

from stock_search.market import normalize_ticker
from stock_search.portfolio import PortfolioStore


@pytest.fixture
def store():
    return PortfolioStore(":memory:")


def test_add_and_close(store):
    hid = store.add_holding("7203.T", 200, 3000, name="トヨタ")
    assert len(store.holdings()) == 1
    pnl = store.close_holding(hid, 100, 3300, fee=100)
    assert pnl == 100 * 300 - 100
    assert store.holdings()["shares"].iloc[0] == 100
    store.close_holding(hid, 100, 2900)
    assert store.holdings().empty
    tr = store.trades()
    assert len(tr) == 3 and tr["realized_pnl"].dropna().sum() == 29900 - 10000


def test_short_close_pnl(store):
    hid = store.add_holding("9984.T", 100, 10000, side="売り", account="信用（制度）")
    assert store.close_holding(hid, 100, 9000) == 100000


def test_settings_defaults_and_update(store):
    assert store.settings()["risk_per_trade_pct"] == 1.0
    store.set_setting("capital", 2_000_000)
    assert store.settings()["capital"] == 2_000_000


def test_csv_roundtrip(store):
    store.add_holding("7203.T", 100, 3000, stop_loss=2800)
    csv = store.export_holdings_csv()
    other = PortfolioStore(":memory:")
    assert other.import_holdings_csv(csv) == 1
    assert other.holdings()["stop_loss"].iloc[0] == 2800


def test_csv_missing_columns(store):
    with pytest.raises(ValueError):
        store.import_holdings_csv("ticker,shares\n7203.T,100\n")


def test_watchlist(store):
    store.add_watch("6857.T", "アドバンテスト")
    assert list(store.watchlist()["ticker"]) == ["6857.T"]
    store.remove_watch("6857.T")
    assert store.watchlist().empty


@pytest.mark.parametrize("raw,expected", [("7203", "7203.T"), ("7203.t", "7203.T"), ("aapl", "AAPL"), ("285A", "285A.T")])
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected
