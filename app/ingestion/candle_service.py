"""
Long-running candle ingestion: backfill from last stored timestamp, then poll for new 1m candles.

Thread safety: on_progress is invoked from the ingestion thread. Do NOT update Qt widgets
directly from this callback (causes freezes/crashes). Either:
  - use it only for logging, or
  - pass a callback that emits a Qt signal so the main thread can update the UI.
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

from app.storage.db import Database, CANDLE_TABLES
from app.ingestion.binance_client import (
    INTERVAL_MS,
    request_klines,
    kline_row_to_dict,
)

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 90


def _parse_start_date_ms(date_str: str) -> Optional[int]:
    """Parse YYYY-MM-DD to UTC midnight timestamp in ms. Returns None if invalid or empty."""
    s = (date_str or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


class CandleIngestionService:
    def __init__(
        self,
        db: Database,
        symbol: str,
        poll_interval_sec: float = 60.0,
        on_progress: Optional[Callable[[str], None]] = None,
        start_date: Optional[str] = None,
    ):
        """
        on_progress(msg) is called from the ingestion thread. Do not touch Qt widgets
        in this callback; only log or emit a signal for the main thread to handle.
        start_date: YYYY-MM-DD; when DB has no candles, backfill from this date. Empty = 90 days ago.
        """
        self._db = db
        self._symbol = symbol
        self._poll_interval_sec = poll_interval_sec
        self._on_progress = on_progress
        self._start_date = (start_date or "").strip()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._session = requests.Session()

    def _log(self, msg: str) -> None:
        logger.info("[candle] %s", msg)
        if self._on_progress:
            try:
                self._on_progress(msg)
            except Exception:
                pass

    def _backfill_range(self, interval: str, start_ms: int, end_ms: int, limit: int = 1500) -> int:
        """Fetch and insert candles for [start_ms, end_ms]. Returns count inserted."""
        interval_ms = INTERVAL_MS[interval]
        step_ms = interval_ms * limit
        cursor = start_ms
        total_new = 0
        while cursor < end_ms:
            batch_end = min(end_ms, cursor + step_ms - interval_ms)
            try:
                klines = request_klines(
                    self._session,
                    self._symbol,
                    interval,
                    cursor,
                    batch_end,
                    limit=limit,
                )
            except Exception as e:
                self._log(f"Backfill {interval} error: {e}")
                time.sleep(5)
                continue
            if not klines:
                break
            rows = [kline_row_to_dict(k) for k in klines]
            self._db.insert_candles(self._symbol, interval, rows)
            total_new += len(rows)
            last_open = int(klines[-1][0])
            cursor = last_open + interval_ms
            self._log(f"Backfill {interval} +{len(rows)} (total +{total_new})")
            time.sleep(0.2)
        return total_new

    def _backfill_one(self, interval: str) -> int:
        """Backfill one timeframe: fill gap from start_date to earliest stored, then from last stored to now."""
        last_ms = self._db.get_last_candle_time_ms(self._symbol, interval)
        earliest_ms = self._db.get_first_candle_time_ms(self._symbol, interval)
        interval_ms = INTERVAL_MS[interval]
        end_ms = int(time.time() * 1000)
        start_date_ms = _parse_start_date_ms(self._start_date)
        total_new = 0

        # 1) Gap at the beginning: if user set start_date and existing data starts after it, fill from start_date to first candle
        if (
            start_date_ms is not None
            and earliest_ms is not None
            and earliest_ms > start_date_ms
        ):
            gap_end_ms = earliest_ms - interval_ms
            if gap_end_ms > start_date_ms:
                self._log(f"Backfill {interval} gap from start_date to first candle...")
                total_new += self._backfill_range(interval, start_date_ms, gap_end_ms)

        # 2) Forward from last candle to now
        start_forward = (last_ms + interval_ms) if last_ms is not None else None
        if start_forward is None:
            start_forward = (
                start_date_ms
                if start_date_ms is not None
                else int((time.time() - BACKFILL_DAYS * 24 * 3600) * 1000)
            )
        if start_forward < end_ms:
            total_new += self._backfill_range(interval, start_forward, end_ms)
        return total_new

    def _has_any_candles(self) -> bool:
        """True if DB already has at least one candle for this symbol (1m)."""
        return self._db.get_last_candle_time_ms(self._symbol, "1m") is not None

    def _backfill(self) -> None:
        for interval in CANDLE_TABLES:
            self._log(f"Backfilling {interval}...")
            n = self._backfill_one(interval)
            if n:
                self._log(f"Backfill {interval} done: {n} candles")
        self._log("Backfill done (all TFs)")

    def _poll_one(self, interval: str) -> bool:
        last_ms = self._db.get_last_candle_time_ms(self._symbol, interval)
        interval_ms = INTERVAL_MS[interval]
        start_ms = (last_ms + interval_ms) if last_ms else (int(time.time() * 1000) - interval_ms * 2)
        end_ms = int(time.time() * 1000)
        if start_ms >= end_ms:
            return True
        try:
            klines = request_klines(
                self._session,
                self._symbol,
                interval,
                start_ms,
                end_ms,
                limit=1500,
            )
        except Exception as e:
            self._log(f"Poll {interval} error: {e}")
            return False
        if not klines:
            return True
        rows = [kline_row_to_dict(k) for k in klines]
        self._db.insert_candles(self._symbol, interval, rows)
        self._log(f"Poll {interval} +{len(rows)} candles")
        return True

    def _poll_once(self) -> None:
        for interval in CANDLE_TABLES:
            self._poll_one(interval)

    def _run(self) -> None:
        if self._has_any_candles():
            self._log("Backfilling (gap from start_date + catch-up); then polling...")
        else:
            self._log("Empty DB; backfilling (1m, 5m, 15m, 1h)...")
        self._backfill()
        self._log("Backfill done")
        while self._running:
            self._poll_once()
            for _ in range(int(self._poll_interval_sec * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._log("Stopped")
