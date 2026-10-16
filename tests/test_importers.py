from pathlib import Path

from stock_search.importers import decode_bytes, is_sbi_holdings, parse_sbi_holdings
from stock_search.portfolio import PortfolioStore

SAMPLE = (Path(__file__).parent / "fixtures" / "sbi_holdings_sample.csv").read_bytes()


def test_detects_and_decodes_shift_jis():
    assert is_sbi_holdings(decode_bytes(SAMPLE))


def test_parse_sbi_holdings():
    stocks, funds = parse_sbi_holdings(SAMPLE)
    assert list(stocks["ticker"]) == ["7203.T", "285A.T", "7203.T"]
    assert list(stocks["account"]) == ["特定口座", "特定口座", "NISA成長投資枠"]
    assert stocks.loc[1, "name"] == "キオクシアHD"  # 全角 → 半角
    assert stocks.loc[1, "current_price"] == 3500.5
    assert len(funds) == 1
    assert funds.loc[0, "name"] == "eMAXIS Slim 米国株式(S&P500)"
    assert funds.loc[0, "units"] == 30000 and funds.loc[0, "pnl"] == 20000
    assert "つみたて" in funds.loc[0, "account"]


def test_sync_keeps_stops_and_removes_sold():
    store = PortfolioStore(":memory:")
    hid = store.add_holding("7203.T", 200, 2400, account="特定口座", stop_loss=2300, memo="押し目")
    store.add_holding("9999.T", 100, 1000, account="特定口座")          # 売却済み扱いで消える
    store.add_holding("8306.T", 100, 1000, account="信用（制度）")      # 信用は触らない
    stocks, funds = parse_sbi_holdings(SAMPLE)
    res = store.sync_holdings(stocks)
    assert res == {"added": 2, "updated": 1, "removed": 1}
    h = store.holdings()
    toyota = h[(h["ticker"] == "7203.T") & (h["account"] == "特定口座")].iloc[0]
    assert toyota["shares"] == 100 and toyota["avg_price"] == 2500
    assert toyota["stop_loss"] == 2300 and toyota["memo"] == "押し目"
    assert "9999.T" not in set(h["ticker"]) and "8306.T" in set(h["ticker"])
    # 2回取り込んでも重複しない
    store.sync_holdings(stocks)
    assert len(store.holdings()) == 4
    store.replace_funds(funds)
    assert len(store.funds()) == 1
