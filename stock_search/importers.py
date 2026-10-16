"""証券会社からダウンロードした保有一覧 CSV の取り込み."""
from __future__ import annotations

import csv
import io
import re
import unicodedata

import pandas as pd

from .market import normalize_ticker

SBI_ACCOUNT_MAP = {
    "特定": "特定口座",
    "NISA": "NISA成長投資枠",
    "一般": "一般口座",
}


def decode_bytes(data: bytes) -> str:
    """UTF-8（BOM 付き含む）→ Shift-JIS(cp932) の順で文字コードを判定してデコード."""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp932", errors="replace")


def is_sbi_holdings(text: str) -> bool:
    return "保有証券一覧" in text[:200] or ("銘柄コード" in text and "保有株数" in text)


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "").replace("+", "")
    s = re.sub(r"[口株円]$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _account(section: str) -> str:
    for key, acct in SBI_ACCOUNT_MAP.items():
        if key in section:
            return acct
    return "特定口座"


def parse_sbi_holdings(data: bytes | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """SBI証券「保有証券一覧」CSV を (個別株, 投資信託) の DataFrame に変換する.

    個別株の列: ticker, name, shares, avg_price, account, current_price
    投資信託の列: name, units, avg_price, nav, market_value, pnl, account
    """
    text = decode_bytes(data) if isinstance(data, bytes) else data
    stocks, funds = [], []
    section, header = "", None
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if not any(cells):
            header = None
            continue
        first = cells[0]
        if len([c for c in cells if c]) == 1 and not first.startswith(("銘柄", "ファンド")):
            # 「株式（特定預り）」のようなセクション見出し
            section = first
            header = None
            continue
        if first in ("銘柄コード", "ファンド名") or first.startswith("評価額合計"):
            header = cells if not first.startswith("評価額合計") else None
            continue
        if header is None or section.endswith("合計"):
            continue
        rec = dict(zip(header, cells))
        if header[0] == "銘柄コード" and section.startswith("株式"):
            shares, avg = _num(rec.get("保有株数")), _num(rec.get("取得単価"))
            if not rec.get("銘柄コード") or not shares or avg is None:
                continue
            stocks.append({
                "ticker": normalize_ticker(rec["銘柄コード"]),
                "name": unicodedata.normalize("NFKC", rec.get("銘柄名称", "")),
                "shares": shares,
                "avg_price": avg,
                "account": _account(section),
                "current_price": _num(rec.get("現在値")),
            })
        elif header[0] == "ファンド名":
            m = re.search(r"（(.+)）", section)
            funds.append({
                "name": unicodedata.normalize("NFKC", rec.get("ファンド名", "")),
                "units": _num(rec.get("保有口数")),
                "avg_price": _num(rec.get("取得単価")),
                "nav": _num(rec.get("基準価額")),
                "market_value": _num(rec.get("評価額")),
                "pnl": _num(rec.get("評価損益")),
                "account": m.group(1) if m else section,
            })
    return pd.DataFrame(stocks), pd.DataFrame(funds)
