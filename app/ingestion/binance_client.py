"""
Binance Futures klines API client (used by candle ingestion service).
"""
import time
from typing import Any, Dict, List, Optional

import requests

FAPI_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}


def safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def request_klines(
    session: requests.Session,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: Optional[int],
    limit: int = 1500,
    timeout: int = 30,
    max_retries: int = 10,
) -> List[List[Any]]:
    params: Dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    }
    if end_ms is not None:
        params["endTime"] = end_ms

    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        r = session.get(FAPI_KLINES_URL, params=params, timeout=timeout)

        if r.status_code in (418, 429):
            retry_after = r.headers.get("Retry-After")
            wait_s = float(retry_after) if (retry_after and str(retry_after).isdigit()) else backoff
            time.sleep(wait_s)
            backoff = min(backoff * 2, 60.0)
            continue

        if not r.ok:
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue

        data = r.json()
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected response: {data}")
        return data

    raise RuntimeError("Max retries exceeded while requesting klines")


def kline_row_to_dict(k: List[Any]) -> Dict[str, Any]:
    open_time_ms = int(k[0])
    return {
        "open_time": open_time_ms,
        "open": safe_float(k[1]),
        "high": safe_float(k[2]),
        "low": safe_float(k[3]),
        "close": safe_float(k[4]),
        "volume": safe_float(k[5]),
    }
