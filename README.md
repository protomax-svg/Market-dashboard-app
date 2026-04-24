# MarketMetrics

MarketMetrics is a desktop market dashboard for crypto candles, liquidation flow, and custom indicators.

It is built around:
- Native candle storage for `5m`, `15m`, and `1h`
- A composite `Regime Index` chart
- A second `Balanced Regime Index` chart that can replace the lower indicator strip
- Secondary indicator panels for quick scanning
- Optional custom indicators loaded from a user folder
- Local SQLite storage so history survives restarts

## What It Does

- Downloads and stores Binance Futures candles locally
- Polls for new candles in the background
- Supports long backfills from a specific start date
- Falls back to `1h` history first for deep backfills, then fills finer candles where available
- Displays a Regime chart with a Regime line, close-price overlay, and configurable red/green highlight zones
- Can replace the lower compact indicators with a second large `Balanced Regime Index` chart
- Loads indicator plugins from the repo and from your custom indicators folder

## Requirements

- Python 3.11 or 3.12 is recommended on Windows
- A working internet connection for candle downloads
- Windows, macOS, or Linux with a Qt-capable desktop environment

## Install

From the project root:

```powershell
py -3.12 -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
. .\.venv\Scripts\Activate.ps1
```

## Run

```powershell
python run_app.py
```

Main entry points:
- [run_app.py](/d:/QUANT/MarketMetrics/run_app.py:1)
- [app/main.py](/d:/QUANT/MarketMetrics/app/main.py:24)

## First Start

On first launch, the app creates its storage under:
- Database: `~/.marketmetrics/marketmetrics.db`
- Config: `~/.marketmetrics/config.json`
- Custom indicators: `~/.marketmetrics/custom_indicators/`

Default market settings:
- Symbol: `BTCUSDT`
- Poll interval: `60s`
- Default visible range: `90d`

## How History Works

There are two separate ideas:
- Visible range: how much history the chart tries to show
- Download start date: how far back the app should backfill data

Important behavior:
- Setting chart `Range = 500 days` does not mean "start from 2022"
- If you want BTC `1h` candles from 2022, set `Download from date = 2022-01-01` in Settings
- Deep backfills start with `1h` candles, then finer timeframes are filled where available
- If retention mode is `By size (GB)`, very old candles can still be pruned
- If retention mode is `By days`, the app now keeps enough days to cover the selected range and explicit candle start date

Example:
- `Range = 500` on April 24, 2026 means roughly back to December 2024, not 2022

## Regime Index Chart

The Regime panel is the main chart in the app.

It now includes:
- Regime Index line
- Close-price line on a synchronized price axis
- Red price-zone fills when Regime is above the configured high threshold
- Green price-zone fills when Regime is below the configured low threshold

Zone behavior:
- A zone starts where Regime crosses above or below the threshold
- A zone ends where Regime crosses back
- The filled area spans horizontally across that full interval
- The fill is drawn vertically from the chart bottom up to the price curve

Regime settings are available in `Settings > Regime Index`:
- `Low highlight`
- `High highlight`

Default values:
- Low: `0.35`
- High: `0.65`

If you want to see more zones, try:
- Low: `0.45`
- High: `0.55`

## Balanced Regime Index Chart

The app also includes a second composite chart: `Balanced Regime Index`.

Purpose:
- `0.00` means healthier, cleaner, more constructive market conditions
- `1.00` means more stressed, weaker, poor-quality conditions

UI behavior:
- It uses the same synchronized close-price overlay as the main Regime chart
- It has its own green/red highlight zones
- It can replace the lower indicator strip from `Settings > Dashboard`

Balanced Regime settings are available in `Settings > Balanced Regime Index`:
- `Low highlight`
- `High highlight`

Default values:
- Low: `0.35`
- High: `0.65`

## Regime Index Math

The Regime Index is defined in [indicators/composite/regime_index.py](/d:/QUANT/MarketMetrics/indicators/composite/regime_index.py:168).

Important implementation detail:
- Even though several indicator files still declare `1m` in their metadata, the app currently computes all Regime dependencies on the Regime panel's selected timeframe because it passes that chart's candle series into every dependency at refresh time.

### Base Return Used by Most Components

For most inputs, the return series is:

```text
r_t = ln(C_t / C_{t-1})
```

where:
- `C_t` is candle close
- `H_t` is candle high
- `L_t` is candle low
- `V_t` is candle volume

### Dependency Indicators And Formulas

1. `vol_of_vol` from [app/indicators/vol_of_vol.py](/d:/QUANT/MarketMetrics/app/indicators/vol_of_vol.py:10)

Default parameters:
- `vol_window = 20`
- `vov_window = 30`

Formula:

```text
TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

ATR_init = mean(TR_1 ... TR_vol_window)
ATR_t = ((vol_window - 1) * ATR_{t-1} + TR_t) / vol_window

VOV_t = std(ATR over the last vov_window points)
```

2. `perm_entropy` from [app/indicators/perm_entropy.py](/d:/QUANT/MarketMetrics/app/indicators/perm_entropy.py:92)

Default parameters:
- `embed_dim = 5`
- `delay = 1`
- `window = 300`

Formula:

```text
Build ordinal patterns from:
[C_i, C_{i+tau}, ..., C_{i+(m-1)tau}]

PE_t = -sum(p_j * log(p_j)) / log(m!)
```

where `p_j` is the empirical frequency of each ordinal pattern in the rolling window.

3. `realized_kurtosis` from [indicators/real_urtosis.py](/d:/QUANT/MarketMetrics/indicators/real_urtosis.py:42)

Default parameters:
- `window = 300`
- `use_excess = True`

Formula:

```text
m2 = E[(r - mean(r))^2]
m4 = E[(r - mean(r))^4]
kurt_t = m4 / (m2^2) - 3
```

The default output is excess kurtosis.

4. `amihud_illiquidity` from [indicators/amihud_illiquidity.py](/d:/QUANT/MarketMetrics/indicators/amihud_illiquidity.py:38)

Default parameters:
- `window = 300`

Formula:

```text
illiq_t = |r_t| / (C_t * V_t)
Amihud_t = mean(illiq over the last window valid points)
```

5. `down_up_vol_asym` from [indicators/volatility_assymetry.py](/d:/QUANT/MarketMetrics/indicators/volatility_assymetry.py:46)

Default parameters:
- `window = 300`
- `mode = ratio`
- `eps = 1e-12`

Formula:

```text
down_vol_t = std({r_i in window where r_i < 0})
up_vol_t   = std({r_i in window where r_i > 0})

asym_t = down_vol_t / (up_vol_t + eps)
```

6. `rolling_hurst` from [indicators/hurst_exponent.py](/d:/QUANT/MarketMetrics/indicators/hurst_exponent.py:36)

Default parameters:
- `window = 300`

Formula:

```text
mean_r = mean(r over window)
X_k = sum_{i=1..k}(r_i - mean_r)
R = max(X_k) - min(X_k)
S = std(r over window)

H_t = log(R / S) / log(N)
```

where `N` is the number of returns in the rolling window.

7. `ulcer_index` from [indicators/ulcer_index.py](/d:/QUANT/MarketMetrics/indicators/ulcer_index.py:5)

Default parameters:
- `window = 300`

Formula:

```text
peak_i = running max close inside the rolling window
dd_pct_i = 100 * (P_i / peak_i - 1)

UI_t = sqrt((1 / window) * sum(dd_pct_i^2))
```

8. `rolling_max_drawdown` from [indicators/rolling_max_drawdown.py](/d:/QUANT/MarketMetrics/indicators/rolling_max_drawdown.py:10)

Default parameters:
- `window = 300`

Formula:

```text
peak_i = running max close inside the rolling window
dd_i = P_i / peak_i - 1

MDD_t = min(dd_i over the rolling window)
```

9. `vol_regime_ratio` from [indicators/vol_regime.py](/d:/QUANT/MarketMetrics/indicators/vol_regime.py:42)

Default parameters:
- `short_window = 60`
- `long_window = 600`

Formula:

```text
RV_short_t = std(r over short_window)
RV_long_t  = std(r over long_window)

VR_t = RV_short_t / RV_long_t
```

10. `downside_dev` from [indicators/downside_diviation.py](/d:/QUANT/MarketMetrics/indicators/downside_diviation.py:31)

Default parameters:
- `window = 300`

Formula:

```text
DownsideDev_t = sqrt(mean(r_i^2 for r_i < 0 inside the rolling window))
```

11. `real_skewness` from [indicators/realized_skewness.py](/d:/QUANT/MarketMetrics/indicators/realized_skewness.py:44)

Default parameters:
- `window = 300`

Formula:

```text
Skew_t = (1 / n) * sum(((r_i - mean(r)) / std(r))^3)
```

12. `expected_shortfall` from [indicators/expect_shortfall.py](/d:/QUANT/MarketMetrics/indicators/expect_shortfall.py:33)

Default parameters:
- `window = 600`
- `alpha = 0.05`

Formula:

```text
k = ceil(alpha * window)
tail = k worst returns in the rolling window

ES_t = -mean(tail)
```

This is returned as a positive loss magnitude.

13. `returns_autocorr` from [indicators/returns_autocorr.py](/d:/QUANT/MarketMetrics/indicators/returns_autocorr.py:46)

Default parameters:
- `window = 300`
- `lag = 1`

Formula:

```text
ACF_t = corr(r_t, r_{t-lag})
```

implemented as Pearson correlation between `w[lag:]` and `w[:-lag]` inside the rolling window.

14. `vol_absret_corr` from [indicators/vol_absret_corr.py](/d:/QUANT/MarketMetrics/indicators/vol_absret_corr.py:45)

Default parameters:
- `window = 300`

Formula:

```text
VolRetCorr_t = corr(V_t, |r_t|)
```

using Pearson correlation between rolling candle volume and rolling absolute log return.

### Pre-Normalization Transforms

Before converting inputs into percentiles, the composite modifies a few raw series:

```text
mdd_pain_t = |MDD_t|
one_minus_pe_t = 1 - PE_t
neg_skew_t = -Skew_t
abs_acf_t = |ACF_t|
```

Why:
- `|MDD|` turns drawdown depth into a positive pain magnitude
- `1 - PE` treats low entropy as stronger structure
- `-skew` makes negative skew "worse"
- `|ACF|` measures memory regardless of sign

### Rolling Percentile Normalization

Every transformed input is converted to a rolling percentile in `[0, 1]`:

```text
pct_t = rank(x_t in sorted rolling window) / (n - 1)
```

The normalization window is not fixed at `500000` in practice. The code uses:

```text
effective_norm = min(norm_window, max(10, floor(min_available_length / 2)))
```

with:
- `norm_window = 500000` by default
- `min_available_length` = shortest available dependency history among the active inputs

### Alignment And Missing Data Rules

Before combining components:
- all normalized series are aligned on the union of their timestamps
- each component uses the last known value at or before timestamp `t`
- at least `min_components = 4` finite components must be present
- missing components are filled with `0.5`

That neutral fill value is:

```text
NEUTRAL = 0.5
```

### Block Construction

After normalization and alignment, the Regime Index is built from three blocks.

Stress block:

```text
stress_t = (vov_pct + kurt_pct + amihud_pct + ui_pct + vr_pct) / 5
```

Downside block:

```text
downside_t = (asym_pct + mdd_pct + downside_dev_pct + es_pct + neg_skew_pct) / 5
```

Structure block:

```text
structure_t = (one_minus_pe_pct + hurst_pct + abs_acf_pct + vretcorr_pct) / 4
```

### Final Regime Formula

Default weights from the code:
- `w_stress = 0.6`
- `w_downside = 0.3`
- `w_anti_structure = 0.1`

Final formula:

```text
regime_t = 0.6 * stress_t
         + 0.3 * downside_t
         + 0.1 * (1 - structure_t)
```

Then the result is clamped into `[0, 1]`.

### Smoothed Variants

The composite also computes:

```text
regime_fast = EMA(regime_raw, period=20)
regime_slow = EMA(regime_raw, period=200)
```

but the app currently returns and plots only:

```text
regime = regime_raw
```

So the visible Regime line is the raw composite, not the EMA-smoothed one.

## Balanced Regime Index Math

The Balanced Regime Index is defined in [indicators/composite/balanced_regime_index.py](/d:/QUANT/MarketMetrics/indicators/composite/balanced_regime_index.py:138).

It reuses the same normalized `stress`, `downside`, and `structure` blocks as the original `Regime Index`, then adds a market-quality block.

### Extra Dependency Indicators

1. `efficiency_ratio` from [indicators/efficiency_ratio.py](/d:/QUANT/MarketMetrics/indicators/efficiency_ratio.py:17)

Default parameters:
- `window = 300`
- `eps = 1e-12`

Formula:

```text
ER_t = |C_t - C_{t-n}| / sum(|C_i - C_{i-1}| for i=t-n+1..t)
```

Interpretation:
- high `ER` = cleaner / more directed path
- low `ER` = choppier / noisier path

2. `choppiness_index` from [indicators/choppiness_index.py](/d:/QUANT/MarketMetrics/indicators/choppiness_index.py:18)

Default parameters:
- `window = 300`
- `eps = 1e-12`

Formula:

```text
TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

CHOP_t = 100 * log10(sum(TR over n) / (max(H over n) - min(L over n))) / log10(n)
```

Normalized quality transform:

```text
chop_quality_t = 1 - chop_pct_t
```

### Balanced Blocks

The shared blocks are the same as in `Regime Index`:

```text
stress_t = (vov_pct + kurt_pct + amihud_pct + ui_pct + vr_pct) / 5

downside_t = (asym_pct + mdd_pct + downside_dev_pct + es_pct + neg_skew_pct) / 5

structure_t = (one_minus_pe_pct + hurst_pct + abs_acf_pct + vretcorr_pct) / 4
```

New quality block:

```text
quality_t = (er_pct + chop_quality_pct + structure_t + (1 - stress_t)) / 4
```

### Final Balanced Regime Formula

```text
balanced_regime_raw_t =
    0.35 * stress_t
  + 0.25 * downside_t
  + 0.25 * (1 - quality_t)
  + 0.15 * (1 - structure_t)
```

The result is clamped to `[0, 1]`.

EMA variants are also computed:

```text
balanced_regime_fast = EMA(balanced_regime_raw, 20)
balanced_regime_slow = EMA(balanced_regime_raw, 200)
```

The UI currently plots:

```text
balanced_regime = balanced_regime_raw
```

Interpretation:
- `balanced_regime < 0.35` = healthy / clean / constructive market
- `0.35 <= balanced_regime <= 0.65` = mixed / neutral
- `balanced_regime > 0.65` = unhealthy / stress / poor-quality market

## Using the UI

Each chart panel has:
- `TF` for timeframe: `5m`, `15m`, `1h`
- `Range` for visible history in days
- Draggable splitter handles so you can resize chart heights and lower-panel widths manually

Main menus:
- `Date Range` to change the global history window
- `Settings` to change symbol, storage, retention, candle download start date, and Regime thresholds
- `Indicators` to reload plugins or open the indicators folder

## Custom Indicators

The app discovers indicators from:
- Repo indicators folder: `indicators/`
- Composite indicators folder: `indicators/composite/`
- User folder: `~/.marketmetrics/custom_indicators/`

Useful actions:
- `Indicators > Reload Indicators`
- `Indicators > Open Indicators Folder`

## Project Layout

- [app/main.py](/d:/QUANT/MarketMetrics/app/main.py:24): Qt application entry
- [app/ui/main_window.py](/d:/QUANT/MarketMetrics/app/ui/main_window.py:180): main dashboard, services, refresh logic
- [app/ui/chart_panel.py](/d:/QUANT/MarketMetrics/app/ui/chart_panel.py:45): reusable chart widget, including Regime price overlay
- [app/ingestion/candle_service.py](/d:/QUANT/MarketMetrics/app/ingestion/candle_service.py:42): candle backfill and polling
- [app/storage/db.py](/d:/QUANT/MarketMetrics/app/storage/db.py:1): SQLite storage
- [app/config.py](/d:/QUANT/MarketMetrics/app/config.py:13): default config values
- [indicators/composite/regime_index.py](/d:/QUANT/MarketMetrics/indicators/composite/regime_index.py:168): Regime Index composite

## Troubleshooting

### `python` or `py` is not recognized

Install Python 3 first, then reopen the terminal.

### Qt or PySide install problems

Use Python 3.11 or 3.12 and reinstall inside a clean virtual environment:

```powershell
py -3.12 -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### I do not see old history

Check:
- `Settings > Candles > Download from date`
- Retention mode
- Selected chart timeframe

For very long history:
- Prefer `1h`
- Set an explicit start date such as `2022-01-01`
- Leave the app running until backfill completes

### I do not see Regime highlight zones

Check:
- The Regime panel has enough history loaded
- Your thresholds are not too extreme
- Try `Low = 0.45` and `High = 0.55`

### The Regime chart updates slowly

The Regime panel is intentionally throttled and is not recalculated every second. Timeframe changes and settings changes force a fresh refresh.

## Notes

- The app uses local storage heavily; large history windows can make the database grow quickly
- The Regime Index is a composite, slow-moving indicator by design
- Plotly is used by the optional 3D surface view, while the main dashboard charts use `pyqtgraph`
