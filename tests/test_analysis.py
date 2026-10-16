import pandas as pd

from stock_search.analysis import analyze, market_regime, portfolio_risk, position_size, review_holding


def test_uptrend_scores_positive(uptrend):
    a = analyze("7203.T", uptrend)
    assert a.score > 20 and a.trend == "上昇トレンド"
    assert a.stop < a.price < a.target1 < a.target2
    # リスクリワード 1:2
    assert abs((a.target1 - a.price) - 2 * (a.price - a.stop)) < 0.2


def test_downtrend_scores_negative(downtrend):
    a = analyze("7203.T", downtrend)
    assert a.score < 0 and a.signal in ("売り", "強い売り")


def test_short_history_returns_none(uptrend):
    assert analyze("7203.T", uptrend.head(50)) is None


def test_position_size_respects_risk_and_lot():
    ps = position_size("7203.T", entry=3000, stop=2850, capital=3_000_000, risk_pct=1.0, max_position_pct=50)
    assert ps.shares % 100 == 0
    assert ps.risk_amount <= 30_000
    assert ps.shares == 200


def test_position_size_capped_by_max_position():
    ps = position_size("7203.T", entry=1000, stop=999, capital=1_000_000, risk_pct=1.0, max_position_pct=20)
    assert ps.cost <= 200_000


def test_position_size_below_one_lot_suggests_fractional():
    ps = position_size("6861.T", entry=60000, stop=57000, capital=1_000_000)
    assert "単元未満" in ps.note


def test_review_stop_hit():
    rv = review_holding({"avg_price": 1000, "shares": 100, "side": "買い", "stop_loss": 950, "take_profit": None}, None, 940)
    assert rv["action"] == "損切り" and rv["pnl"] == -6000


def test_review_target_hit():
    rv = review_holding({"avg_price": 1000, "shares": 100, "side": "買い", "stop_loss": 950, "take_profit": 1200}, None, 1210)
    assert rv["action"] == "利確検討"


def test_review_short_side_pnl():
    rv = review_holding({"avg_price": 1000, "shares": 100, "side": "売り", "stop_loss": None, "take_profit": None}, None, 900)
    assert rv["pnl"] == 10000


def test_portfolio_risk(uptrend, downtrend):
    h = pd.DataFrame([
        {"ticker": "A.T", "shares": 100, "avg_price": 900, "side": "買い", "account": "特定口座"},
        {"ticker": "B.T", "shares": 100, "avg_price": 900, "side": "買い", "account": "信用（制度）"},
    ])
    prices = {"A.T": float(uptrend["Close"].iloc[-1]), "B.T": float(downtrend["Close"].iloc[-1])}
    pr = portfolio_risk(h, prices, {"A.T": uptrend, "B.T": downtrend}, uptrend, capital=1_000_000)
    assert pr["gross"] > 0 and abs(pr["weights"].sum() - 1) < 1e-9
    assert pr["margin_mv"] == prices["B.T"] * 100
    assert pr["corr"].shape == (2, 2)


def test_market_regime(uptrend, downtrend):
    assert market_regime(uptrend)["size_factor"] == 1.0
    assert market_regime(downtrend)["size_factor"] == 0.5


def test_buy_plan(uptrend):
    from stock_search.analysis import MAX_HOLD_DAYS, buy_plan

    a = analyze("7203.T", uptrend)
    p = buy_plan(a, capital=3_000_000)
    assert p.stop < p.entry_low <= p.limit_price <= p.entry_high
    assert p.target1 > p.limit_price and p.target2 > p.target1
    assert abs((p.target1 - p.limit_price) - 2 * (p.limit_price - p.stop)) <= 1
    assert 10 <= p.holding_days <= MAX_HOLD_DAYS and ("週間" in p.holding_text or "か月" in p.holding_text)
    assert "IFDOCO" in p.order_guide
    assert p.sizing.shares % 100 == 0


def test_buy_plan_weak_market_halves_size(uptrend):
    from stock_search.analysis import buy_plan

    a = analyze("7203.T", uptrend)
    full = buy_plan(a, capital=10_000_000, max_position_pct=100).sizing.shares
    half = buy_plan(a, capital=10_000_000, max_position_pct=100, size_factor=0.5).sizing.shares
    assert half < full
