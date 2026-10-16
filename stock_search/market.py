"""株価データの取得（Yahoo Finance / yfinance）.

注意: 東証銘柄の Yahoo Finance データは通常 15〜20 分程度遅延します。
完全なリアルタイム板情報が必要な場合は証券会社の API（kabuステーション API 等）への差し替えを想定し、
取得処理はこのモジュールに閉じ込めています。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

MARKET_INDICES = {
    "^N225": "日経平均",
    "1306.T": "TOPIX連動ETF",
    "^GSPC": "S&P500",
    "^SOX": "フィラデルフィア半導体",
    "JPY=X": "ドル円",
    "^VIX": "VIX（恐怖指数）",
}

BENCHMARK = "1306.T"


def normalize_ticker(code: str) -> str:
    """'7203' や '7203.t' を '7203.T' に。英字の米国株はそのまま大文字化."""
    code = code.strip().upper()
    if re.fullmatch(r"\d{4}|\d{3}[A-Z]", code):
        return f"{code}.T"
    return code


def is_japanese(ticker: str) -> bool:
    return ticker.endswith(".T")


def lot_size(ticker: str) -> int:
    return 100 if is_japanese(ticker) else 1


@dataclass
class Quote:
    ticker: str
    price: float
    prev_close: float
    change: float
    change_pct: float
    day_high: float
    day_low: float
    volume: float
    as_of: datetime | None

    @property
    def is_up(self) -> bool:
        return self.change >= 0


def _single(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yf.download の戻り値（MultiIndex 列の場合あり）から 1 銘柄分を取り出す."""
    if isinstance(df.columns, pd.MultiIndex):
        if ticker in df.columns.get_level_values(0):
            df = df[ticker]
        elif ticker in df.columns.get_level_values(1):
            df = df.xs(ticker, axis=1, level=1)
        else:
            return pd.DataFrame()
    return df.dropna(how="all")


class MarketData:
    """yfinance をラップしたデータ取得クラス。テストでは差し替え可能."""

    def __init__(self):
        import yfinance as yf

        self._yf = yf

    def history(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        df = self._yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])

    def histories(self, tickers: Iterable[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        tickers = list(dict.fromkeys(tickers))
        if not tickers:
            return {}
        raw = self._yf.download(tickers, period=period, interval="1d", group_by="ticker",
                                auto_adjust=False, progress=False, threads=True)
        out = {}
        for t in tickers:
            df = _single(raw, t)
            if not df.empty and "Close" in df:
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                df.index = pd.to_datetime(df.index).tz_localize(None)
                out[t] = df
        return out

    def quotes(self, tickers: Iterable[str]) -> dict[str, Quote]:
        """直近値（1分足ベース）と前日終値から騰落を算出."""
        tickers = list(dict.fromkeys(tickers))
        if not tickers:
            return {}
        intraday = self._yf.download(tickers, period="1d", interval="1m", group_by="ticker",
                                     auto_adjust=False, progress=False, threads=True)
        daily = self._yf.download(tickers, period="5d", interval="1d", group_by="ticker",
                                  auto_adjust=False, progress=False, threads=True)
        out: dict[str, Quote] = {}
        for t in tickers:
            d = _single(daily, t)
            i = _single(intraday, t)
            if d.empty or "Close" not in d:
                continue
            d = d.dropna(subset=["Close"])
            if d.empty:
                continue
            if not i.empty and "Close" in i and i["Close"].notna().any():
                i = i.dropna(subset=["Close"])
                price = float(i["Close"].iloc[-1])
                as_of = pd.Timestamp(i.index[-1]).to_pydatetime()
                day_high, day_low = float(i["High"].max()), float(i["Low"].min())
                volume = float(i["Volume"].sum())
                today = pd.Timestamp(i.index[-1]).date()
            else:
                price = float(d["Close"].iloc[-1])
                as_of = pd.Timestamp(d.index[-1]).to_pydatetime()
                day_high, day_low = float(d["High"].iloc[-1]), float(d["Low"].iloc[-1])
                volume = float(d["Volume"].iloc[-1])
                today = pd.Timestamp(d.index[-1]).date()
            prior = d[[pd.Timestamp(x).date() < today for x in d.index]]
            prev_close = float(prior["Close"].iloc[-1]) if not prior.empty else float(d["Close"].iloc[0])
            change = price - prev_close
            out[t] = Quote(t, price, prev_close, change, change / prev_close * 100 if prev_close else 0.0,
                           day_high, day_low, volume, as_of)
        return out

    def profile(self, ticker: str) -> dict:
        """社名・セクター・PER など（取得失敗時は空 dict）."""
        try:
            info = self._yf.Ticker(ticker).info or {}
        except Exception:
            return {}
        keys = ["shortName", "longName", "sector", "industry", "trailingPE", "forwardPE", "priceToBook",
                "dividendYield", "marketCap", "returnOnEquity", "revenueGrowth", "earningsGrowth"]
        return {k: info.get(k) for k in keys if info.get(k) is not None}

    def next_earnings(self, ticker: str) -> pd.Timestamp | None:
        try:
            cal = self._yf.Ticker(ticker).calendar
        except Exception:
            return None
        dates = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date")
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            dates = list(cal.loc["Earnings Date"])
        if not dates:
            return None
        if not isinstance(dates, (list, tuple)):
            dates = [dates]
        future = [pd.Timestamp(x) for x in dates if x is not None]
        return min(future) if future else None
