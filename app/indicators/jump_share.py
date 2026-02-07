"""Jump share proxy: fraction of variance from 'large' returns."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class JumpShare(IndicatorBase):
    id = "jump_share"
    display_name = "Jump Share Proxy"
    description = "Fraction of variance from returns above threshold (e.g. 2 sigma)"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 96, "sigma_mult": 2.0}
    output_series_defs = [{"id": "jump_share", "label": "Jump Share"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 96))
        sigma_mult = float(self.parameters.get("sigma_mult", 2.0))
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
            std = var ** 0.5 if var > 0 else 0.0
            threshold = sigma_mult * std if std > 0 else 0.0
            total_var = sum((x - mean) ** 2 for x in r)
            jump_var = sum((x - mean) ** 2 for x in r if abs(x - mean) >= threshold)
            js = (jump_var / total_var) if total_var > 0 else 0.0
            out.append((times[i], js))
        return ({"jump_share": out}, None)
