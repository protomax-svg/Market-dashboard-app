"""Efficiency Ratio: (close - open) / sum(|deltas|) over window."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class EfficiencyRatio(IndicatorBase):
    id = "efficiency_ratio"
    display_name = "Efficiency Ratio"
    description = "Net change / sum of absolute changes (Kaufman-style)"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 20}
    output_series_defs = [{"id": "er", "label": "Efficiency Ratio"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 20))
        if len(candles) < window:
            return ({}, None)
        times = [c["open_time"] for c in candles]
        closes = [c["close"] for c in candles]
        out: List[Tuple[int, float]] = []
        for i in range(window - 1, len(closes)):
            seg = closes[i - window + 1 : i + 1]
            net = seg[-1] - seg[0]
            denom = sum(abs(seg[j] - seg[j - 1]) for j in range(1, len(seg)))
            er = (net / denom) if denom > 0 else 0.0
            out.append((times[i], er))
        return ({"er": out}, None)
