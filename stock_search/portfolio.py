"""保有銘柄・売買記録・ウォッチリスト・設定を SQLite に保存する."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "portfolio.db"


def default_db_path() -> Path:
    """環境変数 STOCK_SEARCH_DB で保存先を変更できる（例: クラウド同期フォルダ）."""
    return Path(os.environ.get("STOCK_SEARCH_DB") or DEFAULT_DB)

ACCOUNT_TYPES = ["特定口座", "NISA成長投資枠", "一般口座", "信用（制度）", "信用（一般）"]
SIDES = ["買い", "売り"]

DEFAULT_SETTINGS = {
    "capital": "1000000",          # 個別株に回す資金（円）
    "risk_per_trade_pct": "1.0",   # 1トレードで許容する損失（資金比 %）
    "max_position_pct": "25",      # 1銘柄の上限（資金比 %）
    "max_leverage": "1.5",         # 信用を使う場合の実効レバレッジ上限
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    name TEXT,
    shares REAL NOT NULL,
    avg_price REAL NOT NULL,
    side TEXT NOT NULL DEFAULT '買い',
    account TEXT NOT NULL DEFAULT '特定口座',
    opened_at TEXT,
    stop_loss REAL,
    take_profit REAL,
    memo TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,          -- 新規買 / 返済売 / 新規売 / 返済買
    shares REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    traded_at TEXT NOT NULL,
    account TEXT,
    reason TEXT,
    realized_pnl REAL
);
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    memo TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class PortfolioStore:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- holdings -------------------------------------------------------
    def add_holding(
        self,
        ticker: str,
        shares: float,
        avg_price: float,
        name: str = "",
        side: str = "買い",
        account: str = "特定口座",
        opened_at: str | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        memo: str = "",
        record_trade: bool = True,
    ) -> int:
        opened_at = opened_at or date.today().isoformat()
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO holdings (ticker, name, shares, avg_price, side, account, opened_at, stop_loss, take_profit, memo)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ticker, name, shares, avg_price, side, account, opened_at, stop_loss, take_profit, memo),
            )
            if record_trade:
                c.execute(
                    "INSERT INTO trades (ticker, action, shares, price, traded_at, account, reason) VALUES (?,?,?,?,?,?,?)",
                    (ticker, "新規買" if side == "買い" else "新規売", shares, avg_price, opened_at, account, memo),
                )
            return int(cur.lastrowid)

    def update_holding(self, holding_id: int, **fields) -> None:
        allowed = {"ticker", "name", "shares", "avg_price", "side", "account", "opened_at", "stop_loss", "take_profit", "memo"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE holdings SET {sets} WHERE id=?", (*fields.values(), holding_id))

    def delete_holding(self, holding_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM holdings WHERE id=?", (holding_id,))

    def close_holding(self, holding_id: int, shares: float, price: float, fee: float = 0.0,
                      traded_at: str | None = None, reason: str = "") -> float:
        """保有の一部または全部を決済し、実現損益を返す."""
        row = self._conn.execute("SELECT * FROM holdings WHERE id=?", (holding_id,)).fetchone()
        if row is None:
            raise KeyError(holding_id)
        shares = min(shares, row["shares"])
        sign = 1 if row["side"] == "買い" else -1
        pnl = sign * (price - row["avg_price"]) * shares - fee
        traded_at = traded_at or date.today().isoformat()
        with self._tx() as c:
            c.execute(
                "INSERT INTO trades (ticker, action, shares, price, fee, traded_at, account, reason, realized_pnl)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (row["ticker"], "返済売" if sign == 1 else "返済買", shares, price, fee, traded_at,
                 row["account"], reason, pnl),
            )
            remaining = row["shares"] - shares
            if remaining <= 1e-9:
                c.execute("DELETE FROM holdings WHERE id=?", (holding_id,))
            else:
                c.execute("UPDATE holdings SET shares=? WHERE id=?", (remaining, holding_id))
        return pnl

    def holdings(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM holdings ORDER BY ticker", self._conn)

    def trades(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM trades ORDER BY traded_at DESC, id DESC", self._conn)

    # ---- watchlist ------------------------------------------------------
    def add_watch(self, ticker: str, name: str = "", memo: str = "") -> None:
        with self._tx() as c:
            c.execute("INSERT OR REPLACE INTO watchlist (ticker, name, memo) VALUES (?,?,?)", (ticker, name, memo))

    def remove_watch(self, ticker: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))

    def watchlist(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM watchlist ORDER BY ticker", self._conn)

    # ---- settings -------------------------------------------------------
    def settings(self) -> dict[str, float]:
        rows = {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM settings")}
        merged = {**DEFAULT_SETTINGS, **rows}
        return {k: float(v) for k, v in merged.items()}

    def set_setting(self, key: str, value: float) -> None:
        with self._tx() as c:
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))

    # ---- import / export -----------------------------------------------
    def export_holdings_csv(self) -> str:
        return self.holdings().drop(columns=["id"]).to_csv(index=False)

    def import_holdings_csv(self, csv_text: str) -> int:
        """ticker, shares, avg_price 列は必須。その他の列は任意."""
        from io import StringIO

        df = pd.read_csv(StringIO(csv_text))
        missing = {"ticker", "shares", "avg_price"} - set(df.columns)
        if missing:
            raise ValueError(f"必須列がありません: {', '.join(sorted(missing))}")
        n = 0
        for rec in df.to_dict("records"):
            clean = {k: (None if pd.isna(v) else v) for k, v in rec.items()}
            self.add_holding(
                ticker=str(clean["ticker"]),
                shares=float(clean["shares"]),
                avg_price=float(clean["avg_price"]),
                name=clean.get("name") or "",
                side=clean.get("side") or "買い",
                account=clean.get("account") or "特定口座",
                opened_at=clean.get("opened_at"),
                stop_loss=clean.get("stop_loss"),
                take_profit=clean.get("take_profit"),
                memo=clean.get("memo") or "",
                record_trade=False,
            )
            n += 1
        return n
