"""Composite Stress Index: weighted z-score mix of several series."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


def _z_scores(series: List[float]) -> List[float]:
    if not series:
        return []
    n = len(series)
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    std = var ** 0.5 if var > 0 else 1.0
    return [(x - mean) / std for x in series]


class CompositeStressIndex(IndicatorBase):
    id = "composite_stress"
    display_name = "Composite Stress Index"
    description = "Weighted z-score mix of volatility and return-based inputs"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 96, "vol_weight": 0.5, "ret_weight": 0.5}
    output_series_defs = [{"id": "stress", "label": "Stress Index"}]

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
        vol_series: List[float] = []
        ret_abs_series: List[float] = []
        for i in range(window, len(returns) + 1):
            r = returns[i - window : i]
            vol = (sum(x * x for x in r) / len(r)) ** 0.5
            vol_series.append(vol)
            ret_abs_series.append(abs(returns[i - 1]))
        v_z = _z_scores(vol_series)
        r_z = _z_scores(ret_abs_series)
        out: List[Tuple[int, float]] = []
        vw = self.parameters.get("vol_weight", 0.5)
        rw = self.parameters.get("ret_weight", 0.5)
        for idx in range(len(v_z)):
            stress = vw * v_z[idx] + rw * r_z[idx]
            t_idx = min(window + idx, len(times) - 1)
            out.append((times[t_idx], stress))
        return ({"stress": out}, None)
