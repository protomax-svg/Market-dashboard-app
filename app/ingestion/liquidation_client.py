"""
Remote liquidation ingestion: fetch from ngrok endpoint (HTTP or WebSocket),
aggregate to 1m buckets (long_notional, short_notional, total, imbalance), store in DB.
"""
import json
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

import requests

from app.storage.db import Database

logger = logging.getLogger(__name__)

INTERVAL_MS_1M = 60_000


def _bucket_1m(ts_ms: int) -> int:
    return (ts_ms // INTERVAL_MS_1M) * INTERVAL_MS_1M


class LiquidationClient:
    """
    Expects ngrok endpoint to return JSON array of events, each like:
    { "time": 1234567890123, "symbol": "BTCUSDT", "side": "LONG"|"SHORT", "notional": 1234.5 }
    Or similar. Aggregates to 1m buckets and upserts to liquidations_1m.
    """

    def __init__(
        self,
        db: Database,
        base_url: str,
        symbol: str = "BTCUSDT",
        reconnect_delay_sec: float = 5.0,
        poll_interval_sec: float = 2.0,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self._db = db
        self._base_url = (base_url or "").rstrip("/")
        self._symbol = symbol
        self._reconnect_delay = reconnect_delay_sec
        self._poll_interval = poll_interval_sec
        self._on_status = on_status
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._buffer: List[Dict[str, Any]] = []

    def _log(self, msg: str) -> None:
        logger.info("[liquidations] %s", msg)
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

    def _fetch_events(self) -> List[Dict[str, Any]]:
        if not self._base_url:
            return []
        try:
            r = requests.get(
                f"{self._base_url}/events",
                timeout=10,
                headers={"Accept": "application/json"},
            )
            if not r.ok:
                return []
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "events" in data:
                return data["events"]
            return []
        except Exception as e:
            self._log(f"Fetch error: {e}")
            return []

    def _normalize_event(self, e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ts = e.get("time") or e.get("timestamp") or e.get("openTime")
        if ts is None:
            return None
        if isinstance(ts, float):
            ts = int(ts)
        if ts < 10_000_000_000_000:
            ts = ts * 1000
        side = (e.get("side") or e.get("positionSide") or "").upper()
        notional = float(e.get("notional") or e.get("qty") or e.get("quantity") or 0)
        if notional <= 0:
            return None
        return {"time_ms": ts, "side": "LONG" if "LONG" in side else "SHORT", "notional": notional}

    def _aggregate_and_flush(self, events: List[Dict[str, Any]]) -> None:
        buckets: Dict[int, Dict[str, float]] = defaultdict(lambda: {"long": 0.0, "short": 0.0})
        for e in events:
            norm = self._normalize_event(e)
            if norm is None:
                continue
            bucket = _bucket_1m(norm["time_ms"])
            if norm["side"] == "LONG":
                buckets[bucket]["long"] += norm["notional"]
            else:
                buckets[bucket]["short"] += norm["notional"]
        for open_time, agg in buckets.items():
            long_n = agg["long"]
            short_n = agg["short"]
            total = long_n + short_n
            imbalance = (long_n - short_n) / total if total else 0.0
            self._db.upsert_liquidations_1m(
                self._symbol,
                open_time,
                long_n,
                short_n,
                total,
                imbalance,
            )

    def _run(self) -> None:
        while self._running:
            try:
                events = self._fetch_events()
                if events:
                    self._buffer.extend(events)
                    self._aggregate_and_flush(self._buffer)
                    self._buffer = []
                    self._log("Flushed liquidation aggregates")
            except Exception as e:
                self._log(f"Error: {e}; reconnecting in {self._reconnect_delay}s")
            for _ in range(int(self._poll_interval * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def start(self) -> None:
        if not self._base_url:
            self._log("No URL configured; liquidations disabled")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log("Started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._log("Stopped")
