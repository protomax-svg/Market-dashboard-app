# indicators/vol_absret_corr.py
"""
Correlation(volume, |return|) (rolling).

What it measures:
- "Quality" of moves: does size of move come with volume?
- Regime marker: trend confirmation vs empty/whippy market.

Inputs:
- candles (OHLCV)

Output:
- "corr": [(timestamp_ms, value), ...]

Notes:
- Uses Pearson correlation between candle volume and absolute log return.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Dict, Any, List

from app.indicators.base import IndicatorBase


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-18))


def _corr(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 1e-18 or vy <= 1e-18:
        return 0.0
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / math.sqrt(vx * vy)


class VolumeAbsReturnCorr(IndicatorBase):
    id = "vol_absret_corr"
    display_name = "Corr(Volume, |Return|)"
    description = "Rolling correlation between volume and absolute log-return."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300}
    output_series_defs = [{"id": "corr", "label": "Corr(vol, |ret|)"}]

    def compute(
        self,
        candles,
        timeframe,
        liquidations=None,
        incremental: bool = False,
        last_state=None,
    ) -> Tuple[Dict[str, Any], Optional[dict]]:
        window = int(self.parameters.get("window", 300))
        if window < 2 or len(candles) < window + 1:
            return ({}, None)

        times = [c["open_time"] for c in candles]
        closes = [float(c["close"]) for c in candles]
        vols = [float(c.get("volume", 0.0)) for c in candles]

        rets = [abs(_safe_log(closes[i]) - _safe_log(closes[i - 1])) for i in range(1, len(closes))]
        vol_aligned = vols[1:]  # align volume with return from i-1 -> i

        out = []
        for j in range(window - 1, len(rets)):
            w_ret = rets[j - (window - 1) : j + 1]
            w_vol = vol_aligned[j - (window - 1) : j + 1]
            c = _corr(w_vol, w_ret)
            out.append((times[j + 1], c))

        return ({"corr": out}, None)
