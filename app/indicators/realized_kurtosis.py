"""Realized kurtosis (4th moment of returns)."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class RealizedKurtosis(IndicatorBase):
    id = "realized_kurtosis"
    display_name = "Realized Kurtosis"
    description = "Fourth moment of returns over window"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 96}
    output_series_defs = [{"id": "kurt", "label": "Realized Kurtosis"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 96))
        if len(candles) < 2 or len(candles) < window:
            return ({}, None)
        times = [c["open_time"] for c in candles]
        closes = [c["close"] for c in candles]
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] and closes[i - 1] != 0:
                returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
            else:
                returns.append(0.0)
        out: List[Tuple[int, float]] = []
        for i in range(window, len(returns) + 1):
            r = returns[i - window : i]
            n = len(r)
            mean = sum(r) / n
            var = sum((x - mean) ** 2 for x in r) / n
            if var <= 0:
                kurt = 0.0
            else:
                kurt = sum((x - mean) ** 4 for x in r) / n / (var ** 2) - 3.0  # excess kurtosis
            out.append((times[i], kurt))
        return ({"kurt": out}, None)
