# MarketMetrics

Native Windows desktop app for candles, liquidations, and plugin-based indicators. Dark theme only (ChatGPT-style), docking panels, persistent layout.

## Stack

- **Python** — UI: PySide6 (QMainWindow + QDockWidget), plotting: PyQtGraph
- **Storage**: SQLite (candles_1m, liquidations_1m, metrics)
- **Candles**: Binance Futures 1m ingestion (backfill + polling)
- **Liquidations**: Remote ngrok endpoint → 1m aggregation → local DB

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python run_app.py
```

Or:

```bash
python -m app.main
```

## Features

- **Indicators** menu: checkboxes to show/hide dock panels; layout is saved on exit
- **Date Range**: how many days of history to display (stored data unchanged)
- **Settings**: symbol (default BTCUSDT), timeframes, storage path, retention (days or size), ngrok liquidation URL
- **Retention**: automatic pruning by days or by DB size (configurable)
- **Plugin indicators**: drop a module in `indicators/` (see `indicators/README.md`) and restart

## Candle ingestion

On start the app:

1. Reads last stored 1m candle time from DB
2. Backfills from that time to now
3. Polls for new 1m candles (interval in Settings)
4. Resamples 1m → 5m/15m/1h in memory when an indicator needs them

Original batch script: `dwnld-candles.py` (CLI; app uses refactored logic in `app/ingestion/`).

## Liquidations

Set **Settings → Ngrok endpoint URL** to your Termux/ngrok HTTP endpoint. The app expects JSON (e.g. list of `{ "time", "symbol", "side", "notional" }`), aggregates to 1m buckets, and stores in `liquidations_1m`. Liquidation Pressure indicator uses this data.

## Layout

Dock state and which indicator panels are visible are saved when you close the app and restored on next start.



## Indicators

1. Vol of Vol
2. Realized Kurtosis
3. Permutation Entropy
4. Amihud Illiiquidity
5. Rolling Hurst Exponent
6. Realized Vol Asymmetry
7. Rolling Max Drawdown
8. Uclear Index
9. Volume Stability