# indicators/expected_shortfall.py
"""
Expected Shortfall (CVaR / ES) on log-returns.

What it measures:
- Average loss in the worst alpha fraction of returns (tail risk depth).
- A strong regime marker: "how bad are the bad moves".

Inputs:
- candles (OHLCV)

Output:
- "es": [(timestamp_ms, value), ...]

Convention:
- Returns ES as POSITIVE loss magnitude:
    es = - mean(worst_returns)
So higher ES => worse downside tail.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Dict, Any, List

from app.indicators.base import IndicatorBase


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-18))


class ExpectedShortfall(IndicatorBase):
    id = "expected_shortfall"
    display_name = "Expected Shortfall (ES/CVaR)"
    description = "Expected Shortfall on log-returns: average of worst alpha fraction (reported as positive loss)."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 600, "alpha": 0.05}
    output_series_defs = [{"id": "es", "label": "Expected Shortfall (loss)"}]

    def compute(
        self,
        candles,
        timeframe,
        liquidations=None,
        incremental: bool = False,
        last_state=None,
    ) -> Tuple[Dict[str, Any], Optional[dict]]:
        window = int(self.parameters.get("window", 600))
        alpha = float(self.parameters.get("alpha", 0.05))

        alpha = max(1e-6, min(alpha, 0.5))
        if window < 5 or len(candles) < window + 1:
            return ({}, None)

        times = [c["open_time"] for c in candles]
        closes = [float(c["close"]) for c in candles]
        rets = [_safe_log(closes[i]) - _safe_log(closes[i - 1]) for i in range(1, len(closes))]

        out = []
        k = max(1, int(math.ceil(window * alpha)))
        for j in range(window - 1, len(rets)):
            w = rets[j - (window - 1) : j + 1]
            w_sorted = sorted(w)  # ascending: worst losses first
            tail = w_sorted[:k]
            es = - (sum(tail) / len(tail))  # positive magnitude
            out.append((times[j + 1], es))

        return ({"es": out}, None)
