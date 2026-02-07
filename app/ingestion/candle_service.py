"""
Long-running candle ingestion: backfill from last stored timestamp, then poll for new 1m candles.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from app.storage.db import Database
from app.ingestion.binance_client import (
    INTERVAL_MS,
    request_klines,
    kline_row_to_dict,
)

logger = logging.getLogger(__name__)


class CandleIngestionService:
    def __init__(
        self,
        db: Database,
        symbol: str,
        poll_interval_sec: float = 60.0,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self._db = db
        self._symbol = symbol
        self._poll_interval_sec = poll_interval_sec
        self._on_progress = on_progress
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

    def _backfill(self) -> None:
        last_ms = self._db.get_last_candle_time_ms(self._symbol)
        interval = "1m"
        interval_ms = INTERVAL_MS[interval]
        start_ms = last_ms + interval_ms if last_ms is not None else None
        # If no data, backfill last 7 days
        if start_ms is None:
            start_ms = int((time.time() - 7 * 24 * 3600) * 1000)
        end_ms = int(time.time() * 1000)
        cursor = start_ms
        limit = 1500
        step_ms = interval_ms * limit
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
                self._log(f"Backfill error: {e}")
                time.sleep(5)
                continue
            if not klines:
                break
            rows = [kline_row_to_dict(k) for k in klines]
            self._db.insert_candles_1m(self._symbol, rows)
            total_new += len(rows)
            last_open = int(klines[-1][0])
            cursor = last_open + interval_ms
            self._log(f"Backfill +{len(rows)} (total +{total_new})")
            time.sleep(0.2)
        if total_new:
            self._log(f"Backfill done: {total_new} new candles")

    def _poll_once(self) -> bool:
        last_ms = self._db.get_last_candle_time_ms(self._symbol)
        interval = "1m"
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
            self._log(f"Poll error: {e}")
            return False
        if not klines:
            return True
        rows = [kline_row_to_dict(k) for k in klines]
        self._db.insert_candles_1m(self._symbol, rows)
        self._log(f"Poll +{len(rows)} candles")
        return True

    def _run(self) -> None:
        self._log("Starting backfill")
        self._backfill()
        self._log("Backfill done; entering poll loop")
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
