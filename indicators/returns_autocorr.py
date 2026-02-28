# indicators/returns_autocorr.py
"""
Autocorrelation of returns (rolling).

What it measures:
- Micro-structure regime:
  - positive autocorr => momentum-ish
  - negative autocorr => mean-reversion / bounce-ish

Inputs:
- candles (OHLCV)

Output:
- "acf": [(timestamp_ms, value), ...]

Notes:
- Computes Pearson corr between r_t and r_{t-lag} over window.
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


class ReturnsAutocorr(IndicatorBase):
    id = "returns_autocorr"
    display_name = "Returns Autocorrelation"
    description = "Rolling autocorrelation of log-returns at lag k."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300, "lag": 1}
    output_series_defs = [{"id": "acf", "label": "Autocorr"}]

    def compute(
        self,
        candles,
        timeframe,
        liquidations=None,
        incremental: bool = False,
        last_state=None,
    ) -> Tuple[Dict[str, Any], Optional[dict]]:
        window = int(self.parameters.get("window", 300))
        lag = int(self.parameters.get("lag", 1))

        if window < lag + 2 or lag < 1:
            return ({}, None)
        if len(candles) < window + 1:
            return ({}, None)

        times = [c["open_time"] for c in candles]
        closes = [float(c["close"]) for c in candles]
        rets = [_safe_log(closes[i]) - _safe_log(closes[i - 1]) for i in range(1, len(closes))]

        out = []
        for j in range(window - 1, len(rets)):
            w = rets[j - (window - 1) : j + 1]
            # align pairs: x = r[lag:], y = r[:-lag]
            x = w[lag:]
            y = w[:-lag]
            acf = _corr(x, y)
            out.append((times[j + 1], acf))

        return ({"acf": out}, None)
