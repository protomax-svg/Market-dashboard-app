"""Amihud illiquidity: |return| / volume (average over window)."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class AmihudIlliquidity(IndicatorBase):
    id = "amihud_illiquidity"
    display_name = "Amihud Illiquidity"
    description = "Average |return|/volume over window"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 20}
    output_series_defs = [{"id": "amihud", "label": "Amihud"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 20))
        if len(candles) < 2 or len(candles) < window:
            return ({}, None)
        times = [c["open_time"] for c in candles]
        closes = [c["close"] for c in candles]
        volumes = [max(c.get("volume") or 0, 1e-10) for c in candles]
        out: List[Tuple[int, float]] = []
        for i in range(1, len(closes)):
            ret = abs((closes[i] - closes[i - 1]) / closes[i - 1]) if closes[i - 1] else 0.0
            illiq = ret / volumes[i]
            if i >= window:
                window_illiq = sum(
                    abs((closes[j] - closes[j - 1]) / closes[j - 1]) / volumes[j]
                    for j in range(i - window + 1, i + 1)
                    if closes[j - 1]
                ) / window
                out.append((times[i], window_illiq))
        return ({"amihud": out}, None)
