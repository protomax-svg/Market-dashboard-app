"""
Application configuration: load/save from JSON file.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_STORAGE_PATH = os.path.join(os.path.expanduser("~"), ".marketmetrics")
DEFAULT_DB_PATH = os.path.join(DEFAULT_STORAGE_PATH, "marketmetrics.db")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_STORAGE_PATH, "config.json")

DEFAULTS = {
    "symbol": "BTCUSDT",
    "timeframes_enabled": ["5m"],
    "storage_path": DEFAULT_STORAGE_PATH,
    "retention_mode": "days",  # "days" | "size_gb"
    "retention_days": 90,
    "retention_size_gb": 5.0,
    "ngrok_liquidations_url": "",
    "liquidations_reconnect_delay_sec": 5,
    "candle_poll_interval_sec": 60,
    "candle_start_date": "",  # YYYY-MM-DD: download candles from this date to now (empty = 90 days ago)
    "date_range_days": 90,
}


def ensure_storage_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(p):
        ensure_storage_dir(os.path.dirname(p))
        return dict(DEFAULTS)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = dict(DEFAULTS)
        for k, v in data.items():
            if k in out:
                out[k] = v
        return out
    except Exception:
        return dict(DEFAULTS)


def save_config(config: Dict[str, Any], path: Optional[str] = None) -> None:
    p = path or DEFAULT_CONFIG_PATH
    ensure_storage_dir(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_db_path(config: Dict[str, Any]) -> str:
    sp = config.get("storage_path") or DEFAULT_STORAGE_PATH
    return os.path.join(sp, "marketmetrics.db")


def get_custom_indicators_dir(config: Dict[str, Any]) -> str:
    """Return <storage_path>/custom_indicators/; ensure it exists."""
    sp = config.get("storage_path") or DEFAULT_STORAGE_PATH
    path = os.path.join(sp, "custom_indicators")
    ensure_storage_dir(path)
    return path
