# indicators/volatility_regime_ratio.py
"""
Volatility Regime Ratio: RV_short / RV_long on log-returns.

What it measures:
- How "hot" current volatility is vs baseline.
- >1 => volatility picked up (regime shift to turbulent)
- <1 => volatility cooled down (regime shift to calm)

Inputs:
- candles (OHLCV)

Output:
- "ratio": [(timestamp_ms, value), ...]

Notes:
- Uses rolling standard deviation of log returns.
- Timestamps align to the candle at the end of the window.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Dict, Any, List

from app.indicators.base import IndicatorBase


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-18))


def _rolling_std(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(var, 0.0))


class VolatilityRegimeRatio(IndicatorBase):
    id = "vol_regime_ratio"
    display_name = "Volatility Regime Ratio (RV short/long)"
    description = "Realized volatility ratio: short window RV divided by long window RV (log-returns)."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"short_window": 60, "long_window": 600}
    output_series_defs = [{"id": "ratio", "label": "RV short / RV long"}]

    def compute(
        self,
        candles,
        timeframe,
        liquidations=None,
        incremental: bool = False,
        last_state=None,
    ) -> Tuple[Dict[str, Any], Optional[dict]]:
        short_w = int(self.parameters.get("short_window", 60))
        long_w = int(self.parameters.get("long_window", 600))

        if long_w < 2 or short_w < 2:
            return ({}, None)
        if short_w > long_w:
            # keep sensible by swapping
            short_w, long_w = long_w, short_w

        if len(candles) < long_w + 1:
            return ({}, None)

        times = [c["open_time"] for c in candles]
        closes = [float(c["close"]) for c in candles]

        # log returns r[i] corresponds to move from close[i-1] -> close[i]
        rets = [_safe_log(closes[i]) - _safe_log(closes[i - 1]) for i in range(1, len(closes))]

        out = []
        # rets index j aligns to candle index i=j+1 in closes/times
        for j in range(long_w - 1, len(rets)):
            short_slice = rets[j - (short_w - 1) : j + 1]
            long_slice = rets[j - (long_w - 1) : j + 1]
            rv_s = _rolling_std(short_slice)
            rv_l = _rolling_std(long_slice)
            ratio = (rv_s / rv_l) if rv_l > 0 else 0.0
            out.append((times[j + 1], ratio))

        return ({"ratio": out}, None)
