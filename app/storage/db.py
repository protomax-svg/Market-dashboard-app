"""
SQLite storage: candles_1m, liquidations_1m, metrics. Retention pruning.
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}

CANDLE_TABLES = ("1m", "5m", "15m", "1h")  # timeframes stored in separate tables


def _utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


class Database:
    def __init__(self, db_path: str):
        self._path = db_path
        self._lock = threading.RLock()
        Path(os.path.dirname(db_path)).mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=30)

    def _init_schema(self) -> None:
        with self._lock:
            with self._conn() as c:
                for tf in CANDLE_TABLES:
                    table = f"candles_{tf}"
                    c.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            symbol TEXT NOT NULL,
                            open_time INTEGER NOT NULL,
                            open REAL, high REAL, low REAL, close REAL, volume REAL,
                            PRIMARY KEY (symbol, open_time)
                        )
                    """)
                    c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(symbol, open_time)")
                c.execute("""
                    CREATE TABLE IF NOT EXISTS liquidations_1m (
                        symbol TEXT NOT NULL,
                        open_time INTEGER NOT NULL,
                        long_notional REAL, short_notional REAL,
                        total_notional REAL, imbalance REAL,
                        PRIMARY KEY (symbol, open_time)
                    )
                """)
                c.execute("CREATE INDEX IF NOT EXISTS idx_liq_1m_time ON liquidations_1m(symbol, open_time)")
                c.execute("""
                    CREATE TABLE IF NOT EXISTS metrics (
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        metric_name TEXT NOT NULL,
                        value REAL,
                        PRIMARY KEY (symbol, timeframe, timestamp, metric_name)
                    )
                """)
                c.execute("CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(symbol, timeframe, timestamp)")
                c.commit()

    def _candle_table(self, timeframe: str) -> str:
        if timeframe not in CANDLE_TABLES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return f"candles_{timeframe}"

    def get_last_candle_time_ms(self, symbol: str, timeframe: str = "1m") -> Optional[int]:
        table = self._candle_table(timeframe)
        with self._lock:
            with self._conn() as c:
                r = c.execute(
                    f"SELECT MAX(open_time) FROM {table} WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
                return r[0] if r and r[0] is not None else None

    def get_first_candle_time_ms(self, symbol: str, timeframe: str = "1m") -> Optional[int]:
        """Earliest (minimum) open_time for this symbol/timeframe. None if no data."""
        table = self._candle_table(timeframe)
        with self._lock:
            with self._conn() as c:
                r = c.execute(
                    f"SELECT MIN(open_time) FROM {table} WHERE symbol = ?",
                    (symbol,),
                ).fetchone()
                return r[0] if r and r[0] is not None else None

    def clear_all_candles(self, symbol: str) -> None:
        """Delete all candle data for the symbol from every timeframe table. Call before full re-backfill."""
        with self._lock:
            with self._conn() as c:
                for tf in CANDLE_TABLES:
                    table = self._candle_table(tf)
                    c.execute(f"DELETE FROM {table} WHERE symbol = ?", (symbol,))
                c.commit()

    def insert_candles(self, symbol: str, timeframe: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        table = self._candle_table(timeframe)
        with self._lock:
            with self._conn() as c:
                for r in rows:
                    c.execute(
                        f"""INSERT OR REPLACE INTO {table}
                           (symbol, open_time, open, high, low, close, volume)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            symbol,
                            r["open_time"],
                            r.get("open"), r.get("high"), r.get("low"),
                            r.get("close"), r.get("volume"),
                        ),
                    )
                c.commit()

    def insert_candles_1m(self, symbol: str, rows: List[Dict[str, Any]]) -> None:
        """Legacy: insert into 1m table. Prefer insert_candles(symbol, '1m', rows)."""
        self.insert_candles(symbol, "1m", rows)

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Load candles for the given timeframe from the API-backed table (1m, 5m, 15m, 1h)."""
        table = self._candle_table(timeframe)
        with self._lock:
            with self._conn() as c:
                c.row_factory = sqlite3.Row
                q = f"""
                    SELECT open_time, open, high, low, close, volume
                    FROM {table} WHERE symbol = ? AND open_time >= ? AND open_time <= ?
                    ORDER BY open_time
                """
                args: Tuple[Any, ...] = (symbol, start_ms, end_ms)
                if limit:
                    q += " LIMIT ?"
                    args = args + (limit,)
                cur = c.execute(q, args)
                return [
                    {
                        "open_time": row[0],
                        "open": row[1], "high": row[2], "low": row[3],
                        "close": row[4], "volume": row[5],
                    }
                    for row in cur.fetchall()
                ]

    def get_candles_1m(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Legacy: get 1m candles. Prefer get_candles(symbol, '1m', start_ms, end_ms)."""
        return self.get_candles(symbol, "1m", start_ms, end_ms, limit=limit)

    def resample_candles(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        timeframe: str,
    ) -> List[Dict[str, Any]]:
        """Return candles for timeframe. Prefer native API-backed tables; fallback: resample from 1m."""
        if timeframe in CANDLE_TABLES:
            return self.get_candles(symbol, timeframe, start_ms, end_ms)
        interval_ms = INTERVAL_MS.get(timeframe)
        if not interval_ms:
            return []
        start_aligned = (start_ms // interval_ms) * interval_ms
        rows = self.get_candles(symbol, "1m", start_aligned, end_ms, limit=None)
        if not rows:
            return []
        out: List[Dict[str, Any]] = []
        bucket_start = start_aligned
        acc: List[Dict[str, Any]] = []
        for r in rows:
            t = r["open_time"]
            if t >= bucket_start + interval_ms:
                if acc:
                    o = acc[0]["open"]
                    h = max(x["high"] for x in acc)
                    l = min(x["low"] for x in acc)
                    c = acc[-1]["close"]
                    v = sum(x["volume"] for x in acc)
                    out.append({
                        "open_time": bucket_start,
                        "open": o, "high": h, "low": l, "close": c, "volume": v,
                    })
                while bucket_start + interval_ms <= t:
                    bucket_start += interval_ms
                acc = [r] if bucket_start <= t < bucket_start + interval_ms else []
            else:
                acc.append(r)
        if acc:
            o = acc[0]["open"]
            h = max(x["high"] for x in acc)
            l = min(x["low"] for x in acc)
            c = acc[-1]["close"]
            v = sum(x["volume"] for x in acc)
            out.append({
                "open_time": bucket_start,
                "open": o, "high": h, "low": l, "close": c, "volume": v,
            })
        return out

    def upsert_liquidations_1m(
        self,
        symbol: str,
        open_time: int,
        long_notional: float,
        short_notional: float,
        total_notional: float,
        imbalance: float,
    ) -> None:
        with self._lock:
            with self._conn() as c:
                c.execute(
                    """INSERT INTO liquidations_1m
                       (symbol, open_time, long_notional, short_notional, total_notional, imbalance)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(symbol, open_time) DO UPDATE SET
                         long_notional = excluded.long_notional,
                         short_notional = excluded.short_notional,
                         total_notional = excluded.total_notional,
                         imbalance = excluded.imbalance
                    """,
                    (symbol, open_time, long_notional, short_notional, total_notional, imbalance),
                )
                c.commit()

    def get_liquidations_1m(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            with self._conn() as c:
                c.row_factory = sqlite3.Row
                cur = c.execute(
                    """SELECT open_time, long_notional, short_notional, total_notional, imbalance
                       FROM liquidations_1m WHERE symbol = ? AND open_time >= ? AND open_time <= ?
                       ORDER BY open_time""",
                    (symbol, start_ms, end_ms),
                )
                return [
                    {
                        "open_time": row[0],
                        "long_notional": row[1], "short_notional": row[2],
                        "total_notional": row[3], "imbalance": row[4],
                    }
                    for row in cur.fetchall()
                ]

    def insert_metric(self, symbol: str, timeframe: str, timestamp: int, metric_name: str, value: float) -> None:
        with self._lock:
            with self._conn() as c:
                c.execute(
                    """INSERT OR REPLACE INTO metrics (symbol, timeframe, timestamp, metric_name, value)
                       VALUES (?, ?, ?, ?, ?)""",
                    (symbol, timeframe, timestamp, metric_name, value),
                )
                c.commit()

    def get_metrics(
        self,
        symbol: str,
        timeframe: str,
        metric_name: str,
        start_ms: int,
        end_ms: int,
    ) -> List[Tuple[int, float]]:
        with self._lock:
            with self._conn() as c:
                cur = c.execute(
                    """SELECT timestamp, value FROM metrics
                       WHERE symbol = ? AND timeframe = ? AND metric_name = ?
                       AND timestamp >= ? AND timestamp <= ?
                       ORDER BY timestamp""",
                    (symbol, timeframe, metric_name, start_ms, end_ms),
                )
                return list(cur.fetchall())

    def get_db_size_bytes(self) -> int:
        try:
            return os.path.getsize(self._path)
        except OSError:
            return 0

    def prune_by_days(self, keep_days: int) -> int:
        """Delete candles, liquidations, metrics older than keep_days. Returns total rows deleted."""
        cutoff_ms = _utc_now_ms() - (keep_days * 24 * 60 * 60 * 1000)
        deleted = 0
        with self._lock:
            with self._conn() as c:
                for tf in CANDLE_TABLES:
                    table = self._candle_table(tf)
                    cur = c.execute(f"DELETE FROM {table} WHERE open_time < ?", (cutoff_ms,))
                    deleted += cur.rowcount
                cur = c.execute("DELETE FROM liquidations_1m WHERE open_time < ?", (cutoff_ms,))
                deleted += cur.rowcount
                cur = c.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff_ms,))
                deleted += cur.rowcount
                c.commit()
        return deleted

    def prune_by_size_gb(self, max_gb: float) -> int:
        """Prune oldest data until DB is under max_gb. Returns rows deleted."""
        max_bytes = int(max_gb * 1024 * 1024 * 1024)
        deleted = 0
        with self._lock:
            with self._conn() as c:
                while self.get_db_size_bytes() > max_bytes:
                    mins = []
                    for tf in CANDLE_TABLES:
                        table = self._candle_table(tf)
                        r = c.execute(f"SELECT MIN(open_time) FROM {table}").fetchone()
                        if r and r[0] is not None:
                            mins.append(r[0])
                    r = c.execute("SELECT MIN(open_time) FROM liquidations_1m").fetchone()
                    if r and r[0] is not None:
                        mins.append(r[0])
                    r = c.execute("SELECT MIN(timestamp) FROM metrics").fetchone()
                    if r and r[0] is not None:
                        mins.append(r[0])
                    if not mins:
                        break
                    cutoff = min(mins)
                    step = 1000 * 60 * 1000  # 1000 minutes in ms
                    end_cut = cutoff + step
                    for tf in CANDLE_TABLES:
                        table = self._candle_table(tf)
                        cur = c.execute(f"DELETE FROM {table} WHERE open_time < ?", (end_cut,))
                        deleted += cur.rowcount
                    cur = c.execute("DELETE FROM liquidations_1m WHERE open_time < ?", (end_cut,))
                    deleted += cur.rowcount
                    cur = c.execute("DELETE FROM metrics WHERE timestamp < ?", (end_cut,))
                    deleted += cur.rowcount
                    c.commit()
            if deleted > 0:
                with self._conn() as c:
                    c.execute("VACUUM")
                    c.commit()
        return deleted
