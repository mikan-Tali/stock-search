"""個別株スイングトレード提案ツール（Streamlit）.

起動: streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stock_search import advisor
from stock_search.analysis import analyze, buy_plan, market_regime, portfolio_risk, position_size, review_holding
from stock_search.backtest import backtest
from stock_search.indicators import add_indicators
from stock_search.market import BENCHMARK, MARKET_INDICES, MarketData, normalize_ticker
from stock_search.portfolio import ACCOUNT_TYPES, SIDES, PortfolioStore
from stock_search.screener import DEFAULT_UNIVERSE, screen

st.set_page_config(page_title="スイング株提案", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- data access
@st.cache_resource
def get_store() -> PortfolioStore:
    return PortfolioStore()


@st.cache_resource
def get_market() -> MarketData:
    return MarketData()


@st.cache_data(ttl=600, show_spinner=False)
def load_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    return get_market().history(ticker, period=period)


@st.cache_data(ttl=600, show_spinner=False)
def load_histories(tickers: tuple[str, ...], period: str = "2y") -> dict[str, pd.DataFrame]:
    return get_market().histories(tickers, period=period)


@st.cache_data(ttl=20, show_spinner=False)
def load_quotes(tickers: tuple[str, ...]) -> dict:
    return get_market().quotes(tickers)


@st.cache_data(ttl=86400, show_spinner=False)
def load_profile(ticker: str) -> dict:
    return get_market().profile(ticker)


@st.cache_data(ttl=43200, show_spinner=False)
def load_earnings(ticker: str):
    return get_market().next_earnings(ticker)


store = get_store()
settings = store.settings()
capital = settings["capital"]


def name_of(ticker: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    if ticker in DEFAULT_UNIVERSE:
        return DEFAULT_UNIVERSE[ticker]
    p = load_profile(ticker)
    return p.get("shortName") or p.get("longName") or ""


def yen(x: float) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:,.0f}"


def tracked_tickers() -> list[str]:
    h, w = store.holdings(), store.watchlist()
    return list(dict.fromkeys(list(h["ticker"]) + list(w["ticker"])))


@st.cache_data(ttl=3600, show_spinner=False)
def screen_universe(extra: tuple[tuple[str, str], ...] = ()) -> pd.DataFrame:
    universe = dict(DEFAULT_UNIVERSE)
    for t, n in extra:
        universe.setdefault(t, n)
    return screen(load_histories(tuple(universe)), universe)


def regime() -> dict:
    idx = load_history("^N225", "2y")
    vix = load_history("^VIX", "6mo")
    return market_regime(idx if not idx.empty else None, vix if not vix.empty else None)


def price_chart(ticker: str, df: pd.DataFrame, plan: dict | None = None) -> go.Figure:
    d = add_indicators(df).tail(180)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
                                 name="株価", increasing_line_color="#d62728", decreasing_line_color="#1f77b4"),
                  row=1, col=1)
    for col, color in [("SMA5", "#999"), ("SMA25", "#ff7f0e"), ("SMA75", "#2ca02c")]:
        fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, line=dict(width=1.2, color=color)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["BB_upper"], name="BB+2σ", line=dict(width=0.8, dash="dot", color="#888")), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["BB_lower"], name="BB-2σ", line=dict(width=0.8, dash="dot", color="#888")), row=1, col=1)
    if plan:
        for label, val, color in [("損切り", plan.get("stop"), "#1f77b4"), ("目標1", plan.get("target1"), "#d62728"),
                                  ("目標2", plan.get("target2"), "#d62728"), ("取得単価", plan.get("avg"), "#555")]:
            if val is not None and not pd.isna(val):
                fig.add_hline(y=val, line_dash="dash", line_color=color, annotation_text=f"{label} {val:,.0f}", row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["RSI14"], name="RSI14", line=dict(color="#9467bd")), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#d62728", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#1f77b4", row=2, col=1)
    fig.add_trace(go.Bar(x=d.index, y=d["MACD_hist"], name="MACDヒスト", marker_color="#bbb"), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["MACD"], name="MACD", line=dict(color="#ff7f0e")), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["MACD_signal"], name="シグナル", line=dict(color="#1f77b4")), row=3, col=1)
    fig.update_layout(height=650, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10),
                      title=f"{ticker} {name_of(ticker)}", legend=dict(orientation="h", y=1.02))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("⚙️ リスク設定")
    with st.form("settings"):
        new_cap = st.number_input("個別株に回す資金（円）", value=int(capital), step=100000, min_value=0)
        risk = st.number_input("1トレードの許容損失（資金比 %）", value=settings["risk_per_trade_pct"], step=0.25,
                               min_value=0.1, max_value=5.0, help="一般的に 0.5〜2%。損切りに掛かった時に失う金額の上限")
        maxpos = st.number_input("1銘柄の上限（資金比 %）", value=settings["max_position_pct"], step=5.0, min_value=5.0, max_value=100.0)
        maxlev = st.number_input("レバレッジ上限（倍）", value=settings["max_leverage"], step=0.1, min_value=1.0, max_value=3.3,
                                 help="信用取引の法定上限は約3.3倍。スイングでは 1.0〜1.5 倍程度が無難")
        if st.form_submit_button("保存"):
            store.set_setting("capital", new_cap)
            store.set_setting("risk_per_trade_pct", risk)
            store.set_setting("max_position_pct", maxpos)
            store.set_setting("max_leverage", maxlev)
            st.rerun()
    st.caption("株価データ: Yahoo Finance（東証は約15〜20分遅延）")
    st.caption("※ 本ツールは情報提供目的です。投資判断はご自身の責任で行ってください。")

tabs = st.tabs(["🎯 買い候補", "📊 ダッシュボード", "💼 保有銘柄", "⚡ リアルタイム", "🔍 分析・提案", "🧭 スクリーナー",
                "🧪 バックテスト", "🤖 AI提案", "📒 売買記録"])

# ================================================================ 買い候補
with tabs[0]:
    r = regime()
    st.subheader("🎯 今の買い候補と買い方")
    st.caption(f"地合い: **{r['label']}**　／　1〜3か月のスイングトレード前提　／　"
               f"資金 ¥{capital:,.0f}・1トレードの許容損失 {settings['risk_per_trade_pct']:.1f}%（左のサイドバーで変更）")
    c = st.columns([1, 1, 2])
    n_show = c[0].slider("表示する銘柄数", 3, 10, 5)
    hide_held = c[1].toggle("保有中の銘柄は除く", value=True)
    if c[2].button("🔄 最新データで再計算"):
        screen_universe.clear()
    wl = tuple((x["ticker"], x["name"] or "") for x in store.watchlist().to_dict("records"))
    with st.spinner("約80銘柄の株価を分析中...（初回は30秒〜1分ほどかかります）"):
        cand = screen_universe(wl)
    if r["size_factor"] < 1:
        st.warning("市場環境を踏まえて推奨株数を自動で減らしています（×{:.2f}）。無理に買わず、候補を絞るのも選択肢です。\n\n".format(r["size_factor"])
                   + "\n".join(f"- {n}" for n in r["notes"]))
    if cand.empty:
        st.error("株価データを取得できませんでした。時間をおいて「最新データで再計算」を押してください。")
    else:
        held = set(store.holdings()["ticker"])
        pool = cand[(cand["score"] >= 20) & ~cand["setup"].isin(["様子見 / 空売り候補"])]
        if hide_held:
            pool = pool[~pool["ticker"].isin(held)]
        # 明確なセットアップがある銘柄を優先
        pool = pool.assign(_clear=pool["setup"] != "明確なセットアップなし").sort_values(["_clear", "score"], ascending=False)
        if pool.empty:
            st.info("いま条件を満たす買い候補はありません。こういう時は「買わない」のも立派な判断です。")
        hist_all = load_histories(tuple(pool["ticker"].head(n_show)))
        for rank, row in enumerate(pool.head(n_show).to_dict("records"), start=1):
            t = row["ticker"]
            a = analyze(t, hist_all.get(t))
            if a is None:
                continue
            plan = buy_plan(a, capital, settings["risk_per_trade_pct"], settings["max_position_pct"], r["size_factor"])
            with st.container(border=True):
                st.markdown(f"### {rank}. {name_of(t, row['name'])}（{t.replace('.T', '')}）　"
                            f"{a.signal}・スコア {a.score:+.0f}")
                st.markdown(f"**{a.setup}**　｜　{a.trend}　｜　現在値 **{a.price:,.0f}円**")
                pct = lambda v: f"{v / plan.limit_price - 1:+.1%}"
                st.markdown(
                    "| 買う価格帯 | 損切り | 利確①（半分） | 利確②（残り） | 保有期間の目安 |\n|:-:|:-:|:-:|:-:|:-:|\n"
                    f"| **{plan.entry_low:,.0f}〜{plan.entry_high:,.0f}円** "
                    f"| **{plan.stop:,.0f}円**<br>:blue[{pct(plan.stop)}] "
                    f"| **{plan.target1:,.0f}円**<br>:red[{pct(plan.target1)}] "
                    f"| **{plan.target2:,.0f}円**<br>:red[{pct(plan.target2)}] "
                    f"| **{plan.holding_text}**<br>最長3か月 |",
                    unsafe_allow_html=True,
                )
                sz = plan.sizing
                st.markdown(f"**推奨株数: {sz.shares:,}株（約{sz.cost:,.0f}円）**　"
                            f"— 損切りになった場合の損失は約{sz.risk_amount:,.0f}円（資金の{sz.risk_pct_of_capital:.1f}%）")
                if sz.note:
                    st.caption(sz.note)
                st.markdown(f"**買い方:** {plan.entry_method}")
                st.info(plan.order_guide)
                cc = st.columns(2)
                cc[0].markdown("**この銘柄を選んだ理由**\n" + "\n".join(f"- {x}" for x in a.reasons) if a.reasons else "")
                cc[1].markdown("**売り方のルール**\n" + "\n".join(f"- {x}" for x in plan.exit_rules))
                warns = list(a.risks)
                earn = load_earnings(t)
                if earn is not None and pd.Timestamp(earn).date() >= date.today():
                    days_to = (pd.Timestamp(earn).date() - date.today()).days
                    if days_to <= plan.holding_days * 7 / 5:
                        warns.append(f"保有期間中に決算発表（{pd.Timestamp(earn):%m/%d}、あと{days_to}日）があります。"
                                     "決算で株価が大きく飛ぶと損切りが効かないことがあるので、決算前に一部利確するか株数を減らすのが無難")
                if warns:
                    st.warning("**注意点**\n" + "\n".join(f"- {x}" for x in warns))
                ec = st.columns([1, 1, 3])
                if ec[0].button("👀 ウォッチリストへ", key=f"w_{t}"):
                    store.add_watch(t, name_of(t, row["name"]), f"買い候補 {date.today():%m/%d}")
                    st.toast(f"{t} をウォッチリストに追加しました")
                with ec[2].popover("🛒 購入したら記録する"):
                    with st.form(f"buy_{t}"):
                        bs = st.number_input("買った株数", value=float(sz.shares or 100), step=100.0, key=f"bs_{t}")
                        bp = st.number_input("買った単価", value=float(plan.limit_price), step=1.0, key=f"bp_{t}")
                        ba = st.selectbox("口座", ACCOUNT_TYPES, key=f"ba_{t}")
                        if st.form_submit_button("保有銘柄に追加（損切り・利確ラインも登録）"):
                            store.add_holding(t, bs, bp, name=name_of(t, row["name"]), account=ba,
                                              stop_loss=plan.stop, take_profit=plan.target1,
                                              memo=f"{a.setup}／目標② {plan.target2:,.0f}円／{plan.holding_text}")
                            st.success("登録しました。リアルタイムタブで損切り・利確ラインへの到達を監視します。")
        st.caption("※ テクニカル指標に基づく機械的な候補です。業績やニュースは「🤖 AI提案」タブで確認できます。"
                   "投資判断はご自身の責任でお願いします。")

# ================================================================ ダッシュボード
with tabs[1]:
    @st.fragment(run_every=60)
    def dashboard():
        st.subheader("マーケット概況")
        q = load_quotes(tuple(MARKET_INDICES))
        cols = st.columns(len(MARKET_INDICES))
        for col, (t, label) in zip(cols, MARKET_INDICES.items()):
            if t in q:
                col.metric(label, f"{q[t].price:,.2f}", f"{q[t].change_pct:+.2f}%")
            else:
                col.metric(label, "-")
        r = regime()
        st.info(f"**地合い: {r['label']}**（推奨ポジションサイズ係数 ×{r['size_factor']:.2f}）\n\n" + "\n".join(f"- {n}" for n in r["notes"]))

        h = store.holdings()
        if h.empty:
            st.write("保有銘柄が未登録です。「💼 保有銘柄」タブから登録してください。")
            return
        quotes = load_quotes(tuple(h["ticker"]))
        total_pnl, total_mv, day_pnl = 0.0, 0.0, 0.0
        for rec in h.to_dict("records"):
            qt = quotes.get(rec["ticker"])
            if not qt:
                continue
            sign = 1 if rec["side"] == "買い" else -1
            pnl = sign * (qt.price - rec["avg_price"]) * rec["shares"]
            total_pnl += pnl
            total_mv += qt.price * rec["shares"]
            day_pnl += sign * qt.change * rec["shares"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("評価額", f"¥{total_mv:,.0f}")
        c2.metric("含み損益", f"¥{total_pnl:,.0f}")
        c3.metric("本日の損益", f"¥{day_pnl:,.0f}")
        c4.metric("資金に対する投下比率", f"{total_mv / capital * 100:.0f}%" if capital else "-")
        st.caption(f"最終更新: {pd.Timestamp.now():%H:%M:%S}（60秒ごとに自動更新）")

    dashboard()

# ================================================================ 保有銘柄
with tabs[2]:
    st.subheader("保有銘柄の登録")
    with st.form("add_holding", clear_on_submit=True):
        c = st.columns([1.2, 1.5, 1, 1, 1, 1.4])
        code = c[0].text_input("銘柄コード", placeholder="7203 / AAPL")
        nm = c[1].text_input("銘柄名（任意）")
        shares = c[2].number_input("株数", min_value=0.0, step=100.0)
        avg = c[3].number_input("取得単価", min_value=0.0, step=1.0)
        side = c[4].selectbox("売買", SIDES)
        acct = c[5].selectbox("口座", ACCOUNT_TYPES)
        c2 = st.columns([1, 1, 1, 3])
        opened = c2[0].date_input("取得日", value=date.today())
        sl = c2[1].number_input("損切り価格（任意）", min_value=0.0, step=1.0)
        tp = c2[2].number_input("目標価格（任意）", min_value=0.0, step=1.0)
        memo = c2[3].text_input("メモ（購入理由など）")
        if st.form_submit_button("追加") and code and shares > 0 and avg > 0:
            t = normalize_ticker(code)
            store.add_holding(t, shares, avg, name=name_of(t, nm), side=side, account=acct,
                              opened_at=opened.isoformat(), stop_loss=sl or None, take_profit=tp or None, memo=memo)
            st.success(f"{t} を追加しました")
            st.rerun()

    h = store.holdings()
    if not h.empty:
        st.subheader("保有一覧（セルを直接編集できます）")
        edited = st.data_editor(
            h, key="holdings_editor", hide_index=True, width="stretch", disabled=["id"],
            column_config={
                "side": st.column_config.SelectboxColumn("売買", options=SIDES),
                "account": st.column_config.SelectboxColumn("口座", options=ACCOUNT_TYPES),
            },
        )
        if st.button("編集内容を保存"):
            for rec in edited.to_dict("records"):
                rec = {k: (None if pd.isna(v) else v) for k, v in rec.items()}
                store.update_holding(int(rec.pop("id")), **rec)
            st.success("保存しました")
            st.rerun()

        st.subheader("決済（売却・返済）")
        with st.form("close_form"):
            opts = {f"{r['ticker']} {r['name'] or ''} {r['shares']:.0f}株 @{r['avg_price']:,.1f}（#{r['id']}）": r["id"] for r in h.to_dict("records")}
            sel = st.selectbox("銘柄", list(opts))
            c = st.columns(4)
            cs = c[0].number_input("決済株数", min_value=0.0, step=100.0)
            cp = c[1].number_input("決済価格", min_value=0.0, step=1.0)
            fee = c[2].number_input("手数料・金利", min_value=0.0, step=10.0)
            reason = c[3].text_input("理由（損切り/利確など）")
            if st.form_submit_button("決済を記録") and cs > 0 and cp > 0:
                pnl = store.close_holding(int(opts[sel]), cs, cp, fee, reason=reason)
                st.success(f"実現損益: ¥{pnl:,.0f}")
                st.rerun()

    with st.expander("CSV で一括インポート / エクスポート"):
        st.caption("必須列: ticker, shares, avg_price ／ 任意列: name, side, account, opened_at, stop_loss, take_profit, memo")
        up = st.file_uploader("CSV ファイル", type="csv")
        if up is not None and st.button("インポート実行"):
            try:
                n = store.import_holdings_csv(up.getvalue().decode("utf-8-sig"))
                st.success(f"{n} 件を取り込みました")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        st.download_button("保有銘柄を CSV で保存", store.export_holdings_csv(), file_name="holdings.csv", mime="text/csv")

    st.subheader("ウォッチリスト")
    with st.form("watch_form", clear_on_submit=True):
        c = st.columns([1, 2, 3, 1])
        wcode = c[0].text_input("銘柄コード")
        wname = c[1].text_input("銘柄名（任意）")
        wmemo = c[2].text_input("メモ")
        c[3].write("")
        if c[3].form_submit_button("追加") and wcode:
            t = normalize_ticker(wcode)
            store.add_watch(t, name_of(t, wname), wmemo)
            st.rerun()
    w = store.watchlist()
    if not w.empty:
        st.dataframe(w, hide_index=True, width="stretch")
        rm = st.selectbox("削除する銘柄", [""] + list(w["ticker"]))
        if rm and st.button("ウォッチリストから削除"):
            store.remove_watch(rm)
            st.rerun()

# ================================================================ リアルタイム
with tabs[3]:
    c = st.columns([2, 1, 1])
    extra = c[0].text_input("追加で表示する銘柄（カンマ区切り）", placeholder="6857, 8035, NVDA")
    interval = c[1].selectbox("自動更新間隔", [15, 30, 60, 300], index=1, format_func=lambda s: f"{s}秒")
    auto = c[2].toggle("自動更新", value=True)
    tickers = tracked_tickers() + [normalize_ticker(x) for x in extra.split(",") if x.strip()]
    tickers = list(dict.fromkeys(tickers))

    @st.fragment(run_every=interval if auto else None)
    def realtime_board():
        if not tickers:
            st.write("保有銘柄かウォッチリストを登録するか、上の欄に銘柄コードを入力してください。")
            return
        quotes = load_quotes(tuple(tickers))
        h = store.holdings()
        rows, alerts = [], []
        for t in tickers:
            qt = quotes.get(t)
            if not qt:
                rows.append({"銘柄": t, "名称": name_of(t), "現在値": None})
                continue
            row = {"銘柄": t, "名称": name_of(t), "現在値": qt.price, "前日比": qt.change, "騰落率%": qt.change_pct,
                   "高値": qt.day_high, "安値": qt.day_low, "出来高": qt.volume,
                   "時刻": qt.as_of.strftime("%m/%d %H:%M") if qt.as_of else ""}
            for rec in h[h["ticker"] == t].to_dict("records"):
                sign = 1 if rec["side"] == "買い" else -1
                row["含み損益"] = row.get("含み損益", 0) + sign * (qt.price - rec["avg_price"]) * rec["shares"]
                if rec["stop_loss"] and not pd.isna(rec["stop_loss"]) and sign * (qt.price - rec["stop_loss"]) <= 0:
                    alerts.append(f"🔻 {t} {name_of(t)}: 損切りライン {rec['stop_loss']:,.0f} に到達（現在 {qt.price:,.1f}）")
                if rec["take_profit"] and not pd.isna(rec["take_profit"]) and sign * (qt.price - rec["take_profit"]) >= 0:
                    alerts.append(f"🎯 {t} {name_of(t)}: 目標価格 {rec['take_profit']:,.0f} に到達（現在 {qt.price:,.1f}）")
            if abs(qt.change_pct) >= 5:
                alerts.append(f"⚠️ {t} {name_of(t)}: 本日 {qt.change_pct:+.1f}% の大きな値動き")
            rows.append(row)
        for a in alerts:
            st.warning(a)
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.format({"現在値": "{:,.1f}", "前日比": "{:+,.1f}", "騰落率%": "{:+.2f}", "高値": "{:,.1f}",
                             "安値": "{:,.1f}", "出来高": "{:,.0f}", "含み損益": "{:+,.0f}"}, na_rep="-")
            .map(lambda v: "color:#d62728" if isinstance(v, (int, float)) and v > 0 else
                 ("color:#1f77b4" if isinstance(v, (int, float)) and v < 0 else ""), subset=["前日比", "騰落率%"]
                 + (["含み損益"] if "含み損益" in df else [])),
            hide_index=True, width="stretch",
        )
        st.caption(f"最終更新: {pd.Timestamp.now():%H:%M:%S}")

    realtime_board()

    if tickers:
        sel = st.selectbox("チャート表示", tickers, format_func=lambda t: f"{t} {name_of(t)}")
        df = load_history(sel)
        if not df.empty:
            a = analyze(sel, df)
            hrow = store.holdings().query("ticker == @sel")
            plan = {"stop": a.stop, "target1": a.target1, "target2": a.target2} if a else {}
            if not hrow.empty:
                plan["avg"] = float(hrow["avg_price"].iloc[0])
                if not pd.isna(hrow["stop_loss"].iloc[0]):
                    plan["stop"] = float(hrow["stop_loss"].iloc[0])
            st.plotly_chart(price_chart(sel, df, plan), width="stretch")

# ================================================================ 分析・提案
with tabs[4]:
    r = regime()
    st.markdown(f"**地合い: {r['label']}** — 新規ポジションのサイズ係数 ×{r['size_factor']:.2f}")
    h = store.holdings()
    if h.empty:
        st.info("保有銘柄を登録すると、銘柄ごとのアクション提案とポートフォリオ分析が表示されます。")
    else:
        st.subheader("保有銘柄のアクション提案")
        hist = load_histories(tuple(h["ticker"].unique()) + (BENCHMARK,))
        quotes = load_quotes(tuple(h["ticker"].unique()))
        prices = {t: (quotes[t].price if t in quotes else float(hist[t]["Close"].iloc[-1]))
                  for t in h["ticker"].unique() if t in quotes or t in hist}
        review_rows = []
        for rec in h.to_dict("records"):
            t = rec["ticker"]
            if t not in prices:
                continue
            a = analyze(t, hist.get(t), prices[t])
            rv = review_holding(rec, a, prices[t])
            earn = load_earnings(t)
            earn_note = ""
            if earn is not None and pd.Timestamp(earn).date() >= date.today():
                days = (pd.Timestamp(earn).date() - date.today()).days
                earn_note = f"決算 {pd.Timestamp(earn):%m/%d}（あと{days}日）"
            review_rows.append({
                "銘柄": t, "名称": rec["name"], "アクション": rv["action"], "現在値": prices[t],
                "取得単価": rec["avg_price"], "損益%": rv["pnl_pct"], "含み損益": rv["pnl"],
                "スコア": a.score if a else None, "トレンド": a.trend if a else "",
                "損切り": rv["stop"], "トレール案": rv["trail_stop"], "決算": earn_note,
                "理由": " / ".join(rv["reasons"]),
            })
        rv_df = pd.DataFrame(review_rows)
        if not rv_df.empty:
            st.dataframe(rv_df.style.format({"現在値": "{:,.1f}", "取得単価": "{:,.1f}", "損益%": "{:+.1f}",
                                             "含み損益": "{:+,.0f}", "スコア": "{:+.0f}", "損切り": "{:,.0f}",
                                             "トレール案": "{:,.0f}"}, na_rep="-"),
                         hide_index=True, width="stretch")
            st.caption("決算発表を跨ぐと窓開け（ギャップ）で損切りが機能しないことがあります。跨ぐ場合は株数を減らすのが無難です。")

        st.subheader("ポートフォリオのリスク")
        pr = portfolio_risk(h, prices, hist, hist.get(BENCHMARK), capital)
        if pr:
            c = st.columns(5)
            c[0].metric("総建玉（グロス）", f"¥{pr['gross']:,.0f}")
            c[1].metric("実効レバレッジ", f"{pr['leverage']:.2f}倍")
            c[2].metric("年率ボラティリティ", f"{pr['volatility']:.0%}" if pd.notna(pr["volatility"]) else "-")
            c[3].metric("β（対TOPIX）", f"{pr['beta']:.2f}" if pd.notna(pr["beta"]) else "-")
            c[4].metric("最大銘柄比率", f"{pr['max_weight']:.0%}")
            warn = []
            if pr["leverage"] > settings["max_leverage"]:
                warn.append(f"実効レバレッジ {pr['leverage']:.2f}倍 が上限 {settings['max_leverage']:.1f}倍 を超えています")
            if pr["max_weight"] * pr["gross"] > capital * settings["max_position_pct"] / 100:
                warn.append("1銘柄の比率が設定上限を超えています")
            for a_, b_, cval in pr["high_corr_pairs"]:
                warn.append(f"{a_} と {b_} の相関が {cval:.2f} と高く、実質的に同じ値動き（分散効果が薄い）")
            if pd.notna(pr["beta"]) and pr["beta"] > 1.3:
                warn.append(f"β {pr['beta']:.2f}：市場全体の下落に対して大きく下がる構成です")
            for wmsg in warn:
                st.warning(wmsg)
            c1, c2 = st.columns(2)
            c1.bar_chart(pr["weights"], horizontal=True)
            if not pr["corr"].empty:
                c2.plotly_chart(go.Figure(go.Heatmap(z=pr["corr"].values, x=pr["corr"].columns, y=pr["corr"].index,
                                                     zmin=-1, zmax=1, colorscale="RdBu_r")).update_layout(
                    height=350, margin=dict(l=10, r=10, t=30, b=10), title="相関（直近6か月）"), width="stretch")

    st.divider()
    st.subheader("個別銘柄の分析と売買プラン")
    c = st.columns([1, 1])
    code = c[0].text_input("銘柄コード", value=(tracked_tickers() or ["7203.T"])[0], key="analyze_code")
    use_margin = c[1].toggle("信用取引（レバレッジ）を使う前提で株数を計算", value=False)
    t = normalize_ticker(code)
    df = load_history(t)
    if df.empty:
        st.error("データを取得できませんでした。銘柄コードをご確認ください。")
    else:
        q = load_quotes((t,)).get(t)
        a = analyze(t, df, q.price if q else None)
        if a is None:
            st.warning("データ期間が短いため分析できません。")
        else:
            m = st.columns(6)
            m[0].metric("現在値", f"{a.price:,.1f}")
            m[1].metric("総合スコア", f"{a.score:+.0f}", a.signal)
            m[2].metric("トレンド", a.trend)
            m[3].metric("RSI", f"{a.rsi:.0f}")
            m[4].metric("3か月騰落", f"{a.ret60:+.1%}")
            m[5].metric("52週高値比", f"{a.dist_52w_high:+.1%}")
            st.markdown(f"**セットアップ:** {a.setup}")
            cc = st.columns(2)
            cc[0].markdown("**買い材料（テクニカル）**\n" + "\n".join(f"- {x}" for x in a.reasons) if a.reasons else "**買い材料:** 特になし")
            cc[1].markdown("**リスク**\n" + "\n".join(f"- {x}" for x in a.risks) if a.risks else "**リスク:** 特になし")

            if a.score >= 0:
                lev = settings["max_leverage"] if use_margin else 1.0
                ps = position_size(t, a.price, a.stop, capital * r["size_factor"], settings["risk_per_trade_pct"],
                                   settings["max_position_pct"], lev)
                st.markdown("#### 売買プラン（1〜3か月スイング）")
                p = st.columns(5)
                p[0].metric("エントリー目安", f"{a.price:,.0f}")
                p[1].metric("損切り", f"{a.stop:,.0f}", f"{(a.stop / a.price - 1):+.1%}")
                p[2].metric("目標1（R:R 1:2）", f"{a.target1:,.0f}", f"{(a.target1 / a.price - 1):+.1%}")
                p[3].metric("目標2（R:R 1:3）", f"{a.target2:,.0f}", f"{(a.target2 / a.price - 1):+.1%}")
                p[4].metric("推奨株数", f"{ps.shares:,}株", f"¥{ps.cost:,.0f}")
                st.caption(f"損切り時の損失: ¥{ps.risk_amount:,.0f}（資金の {ps.risk_pct_of_capital:.2f}%）／"
                           f"資金に対する比率 {ps.position_pct_of_capital:.0f}%"
                           + ("／信用取引が必要な金額です" if ps.needs_margin else ""))
                if ps.note:
                    st.info(ps.note)
                st.caption("目標1で半分利確し、残りは損切りを建値に引き上げて目標2を狙う、という分割決済が基本形です。")
            else:
                st.info("スコアがマイナスのため新規買いは非推奨です。信用売り（空売り）を検討する場合は、"
                        f"損切り {a.stop:,.0f} を厳守してください。")
            earn = load_earnings(t)
            if earn is not None and pd.Timestamp(earn).date() >= date.today():
                st.warning(f"次回決算予定: {pd.Timestamp(earn):%Y-%m-%d}。保有期間中に決算を跨ぐ可能性があります。")
            prof = load_profile(t)
            if prof:
                with st.expander("ファンダメンタルズ（参考）"):
                    st.json(prof)
            st.plotly_chart(price_chart(t, df, {"stop": a.stop, "target1": a.target1, "target2": a.target2}),
                            width="stretch")

# ================================================================ スクリーナー
with tabs[5]:
    st.subheader("スイング候補のスクリーニング")
    st.caption("東証プライム主要銘柄＋ウォッチリストを分析し、総合スコア順に表示します（初回は1分程度かかります）。")
    c = st.columns([1, 1, 2])
    min_to = c[0].number_input("20日平均売買代金の下限（億円）", value=5.0, step=1.0)
    only_buy = c[1].toggle("買いシグナルのみ", value=True)
    extra_u = c[2].text_input("追加で調べる銘柄（カンマ区切り）")
    if st.button("スクリーニング実行", type="primary"):
        universe = dict(DEFAULT_UNIVERSE)
        for rec in store.watchlist().to_dict("records"):
            universe.setdefault(rec["ticker"], rec["name"] or "")
        for x in extra_u.split(","):
            if x.strip():
                universe.setdefault(normalize_ticker(x), "")
        with st.spinner("株価データを取得・分析中..."):
            hist = load_histories(tuple(universe))
            result = screen(hist, universe, min_turnover=min_to * 1e8)
        st.session_state["screen_result"] = result
    res = st.session_state.get("screen_result")
    if res is not None and not res.empty:
        view = res[res["score"] >= 20] if only_buy else res
        held = set(store.holdings()["ticker"])
        view = view.assign(保有中=view["ticker"].isin(held))
        st.dataframe(view.style.format({"price": "{:,.1f}", "score": "{:+.0f}", "RSI": "{:.0f}", "3か月騰落": "{:+.1%}",
                                        "1か月騰落": "{:+.1%}", "52週高値比": "{:+.1%}", "ATR%": "{:.1%}",
                                        "損切り": "{:,.0f}", "目標1": "{:,.0f}", "目標2": "{:,.0f}",
                                        "売買代金(億)": "{:,.0f}"}),
                     hide_index=True, width="stretch")
        add = st.multiselect("ウォッチリストに追加", list(view["ticker"]),
                             format_func=lambda t: f"{t} {DEFAULT_UNIVERSE.get(t, '')}")
        if add and st.button("追加する"):
            for t in add:
                store.add_watch(t, name_of(t))
            st.success("追加しました")

# ================================================================ バックテスト
with tabs[6]:
    st.subheader("シグナルの検証（簡易バックテスト）")
    st.caption("「スコアが閾値以上で買い → 損切り or 目標2（R:R 1:3）or 最大保有日数で手仕舞い」を過去データで検証します。"
               "銘柄ごとにこの手法が機能しやすいかの目安になります（手数料・税金は考慮していません）。")
    c = st.columns(4)
    bt_code = c[0].text_input("銘柄コード", value="7203", key="bt_code")
    bt_period = c[1].selectbox("期間", ["3y", "5y", "10y"], index=1)
    bt_score = c[2].slider("エントリー閾値（スコア）", 0, 80, 40, 5)
    bt_hold = c[3].slider("最大保有日数（営業日）", 20, 90, 60, 5)
    if st.button("バックテスト実行"):
        t = normalize_ticker(bt_code)
        df = load_history(t, bt_period)
        if df.empty:
            st.error("データを取得できませんでした。")
        else:
            with st.spinner("検証中..."):
                res = backtest(t, df, entry_score=bt_score, max_hold_days=bt_hold, step=2)
            m = st.columns(5)
            m[0].metric("トレード数", res.n_trades)
            m[1].metric("勝率", f"{res.win_rate:.0f}%" if res.n_trades else "-")
            m[2].metric("平均R", f"{res.avg_r:+.2f}" if res.n_trades else "-")
            m[3].metric("累積リターン", f"{res.total_return_pct:+.1f}%")
            m[4].metric("最大ドローダウン", f"{res.max_drawdown_pct:.1f}%")
            bh = (df["Close"].iloc[-1] / df["Close"].iloc[120] - 1) * 100
            st.caption(f"参考: 同期間のバイ＆ホールド {bh:+.1f}%")
            if res.n_trades:
                st.dataframe(res.trades, hide_index=True, width="stretch")

# ================================================================ AI提案
with tabs[7]:
    st.subheader("Claude による総合提案")
    if not advisor.is_available():
        st.info("この機能を使うには環境変数 `ANTHROPIC_API_KEY` を設定して再起動してください。"
                "テクニカル分析・保有状況・地合い・ニュース（Web検索）をまとめて、具体的な売買提案を生成します。")
    else:
        note = st.text_area("補足（任意）", placeholder="例: 半導体を増やしたい／今月は新規エントリーを1銘柄に絞りたい／信用で1.3倍までOK")
        web = st.toggle("ニュース・決算予定を Web 検索して考慮する", value=True)
        if st.button("提案を生成", type="primary"):
            with st.spinner("分析中（1〜3分かかることがあります）..."):
                h = store.holdings()
                tick = tuple(h["ticker"].unique())
                hist = load_histories(tick + (BENCHMARK,)) if tick else {}
                quotes = load_quotes(tick) if tick else {}
                holdings_ctx = []
                for rec in h.to_dict("records"):
                    tt = rec["ticker"]
                    price = quotes[tt].price if tt in quotes else (float(hist[tt]["Close"].iloc[-1]) if tt in hist else None)
                    if price is None:
                        continue
                    a = analyze(tt, hist.get(tt), price)
                    holdings_ctx.append({"holding": rec, "price": price, "analysis": a.to_dict() if a else None,
                                         "review": review_holding(rec, a, price),
                                         "next_earnings": str(load_earnings(tt) or "")})
                prices = {x["holding"]["ticker"]: x["price"] for x in holdings_ctx}
                pr = portfolio_risk(h, prices, hist, hist.get(BENCHMARK), capital) if holdings_ctx else {}
                scr = st.session_state.get("screen_result")
                if scr is None:
                    scr = screen(load_histories(tuple(DEFAULT_UNIVERSE)), DEFAULT_UNIVERSE)
                context = {
                    "today": date.today().isoformat(),
                    "settings": settings,
                    "market_regime": regime(),
                    "holdings": holdings_ctx,
                    "portfolio_risk": {k: v for k, v in pr.items() if k != "corr"},
                    "screen_top": scr.head(15) if not scr.empty else [],
                    "watchlist": store.watchlist(),
                }
                try:
                    st.session_state["advice"] = advisor.generate_advice(context, note, web)
                except Exception as e:  # API エラーは画面に表示
                    st.error(f"提案の生成に失敗しました: {e}")
        if st.session_state.get("advice"):
            st.markdown(st.session_state["advice"])

# ================================================================ 売買記録
with tabs[8]:
    st.subheader("売買記録と成績")
    tr = store.trades()
    if tr.empty:
        st.write("まだ売買記録がありません。")
    else:
        closed = tr.dropna(subset=["realized_pnl"])
        if not closed.empty:
            wins = closed[closed["realized_pnl"] > 0]
            losses = closed[closed["realized_pnl"] <= 0]
            m = st.columns(5)
            m[0].metric("実現損益合計", f"¥{closed['realized_pnl'].sum():,.0f}")
            m[1].metric("決済回数", len(closed))
            m[2].metric("勝率", f"{len(wins) / len(closed) * 100:.0f}%")
            avg_w = wins["realized_pnl"].mean() if not wins.empty else 0
            avg_l = -losses["realized_pnl"].mean() if not losses.empty else 0
            m[3].metric("平均利益 / 平均損失", f"{avg_w:,.0f} / {avg_l:,.0f}")
            m[4].metric("プロフィットファクター", f"{wins['realized_pnl'].sum() / -losses['realized_pnl'].sum():.2f}"
                        if not losses.empty and losses["realized_pnl"].sum() < 0 else "-")
            curve = closed.sort_values("traded_at").assign(累積損益=lambda x: x["realized_pnl"].cumsum())
            st.line_chart(curve.set_index("traded_at")["累積損益"])
        st.dataframe(tr, hide_index=True, width="stretch")
        st.download_button("売買記録を CSV で保存", tr.to_csv(index=False), file_name="trades.csv", mime="text/csv")
