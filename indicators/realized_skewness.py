# indicators/realized_skewness.py
"""
Realized Skewness (rolling) on log-returns.

What it measures:
- Directional tail bias: negative skew often appears in panic/liquidation regimes.

Inputs:
- candles (OHLCV)

Output:
- "skew": [(timestamp_ms, value), ...]

Notes:
- Uses sample skewness:
    skew = (1/n) * sum(((r - mean)/std)^3)
- If std ~ 0 => skew = 0
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Dict, Any, List

from app.indicators.base import IndicatorBase


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-18))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _std(values: List[float], m: float) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(var, 0.0))


class RealizedSkewness(IndicatorBase):
    id = "real_skewness"
    display_name = "Realized Skewness"
    description = "Rolling skewness of log-returns."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300}
    output_series_defs = [{"id": "skew", "label": "Skewness"}]

    def compute(
        self,
        candles,
        timeframe,
        liquidations=None,
        incremental: bool = False,
        last_state=None,
    ) -> Tuple[Dict[str, Any], Optional[dict]]:
        window = int(self.parameters.get("window", 300))
        if window < 3 or len(candles) < window + 1:
            return ({}, None)

        times = [c["open_time"] for c in candles]
        closes = [float(c["close"]) for c in candles]
        rets = [_safe_log(closes[i]) - _safe_log(closes[i - 1]) for i in range(1, len(closes))]

        out = []
        for j in range(window - 1, len(rets)):
            w = rets[j - (window - 1) : j + 1]
            m = _mean(w)
            s = _std(w, m)
            if s <= 1e-18:
                skew = 0.0
            else:
                n = len(w)
                skew = sum(((r - m) / s) ** 3 for r in w) / n
            out.append((times[j + 1], skew))

        return ({"skew": out}, None)
