# indicators/downside_deviation.py
"""
Downside Deviation (Semivolatility) on log-returns.

What it measures:
- Volatility of negative returns only (fear / crashiness).
- Useful to detect regime where downside risk increases even if total vol looks similar.

Inputs:
- candles (OHLCV)

Output:
- "downside": [(timestamp_ms, value), ...]

Definition:
- downside = sqrt(mean(r^2 for r<0)) over rolling window
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Dict, Any, List

from app.indicators.base import IndicatorBase


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-18))


class DownsideDeviation(IndicatorBase):
    id = "downside_dev"
    display_name = "Downside Deviation"
    description = "Downside deviation (semivolatility): sqrt(mean(r^2 for r<0)) on log-returns."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300}
    output_series_defs = [{"id": "downside", "label": "Downside deviation"}]

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
        rets = [_safe_log(closes[i]) - _safe_log(closes[i - 1]) for i in range(1, len(closes))]

        out = []
        for j in range(window - 1, len(rets)):
            w = rets[j - (window - 1) : j + 1]
            neg_sq = [r * r for r in w if r < 0.0]
            if not neg_sq:
                downside = 0.0
            else:
                downside = math.sqrt(sum(neg_sq) / len(neg_sq))
            out.append((times[j + 1], downside))

        return ({"downside": out}, None)
