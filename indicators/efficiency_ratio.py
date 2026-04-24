"""
Efficiency Ratio on close prices.

ER_t = abs(C_t - C_{t-n}) / sum(abs(C_i - C_{i-1}) for i=t-n+1..t)

Higher values mean price moved in a cleaner, more directed way.
Lower values mean the market spent more of that path chopping around.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class EfficiencyRatio(IndicatorBase):
    id = "efficiency_ratio"
    display_name = "Efficiency Ratio"
    description = "Path efficiency of close-price movement over a rolling window."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300, "eps": 1e-12}
    output_series_defs = [{"id": "er", "label": "Efficiency Ratio"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 300))
        eps = float(self.parameters.get("eps", 1e-12))

        if window < 2 or len(candles) < window + 1:
            return ({}, None)

        closes = [float(candle["close"]) for candle in candles]
        times = [int(candle["open_time"]) for candle in candles]

        step_moves = [abs(closes[index] - closes[index - 1]) for index in range(1, len(closes))]
        rolling_path = sum(step_moves[:window])

        out: List[Tuple[int, float]] = []
        for end_index in range(window, len(closes)):
            if end_index > window:
                rolling_path += step_moves[end_index - 1]
                rolling_path -= step_moves[end_index - window - 1]

            net_move = abs(closes[end_index] - closes[end_index - window])
            er = (net_move / rolling_path) if rolling_path > eps else 0.0
            if math.isfinite(er):
                out.append((times[end_index], max(0.0, er)))

        return ({"er": out}, None)
