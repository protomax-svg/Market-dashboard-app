"""Down-vol vs Up-vol asymmetry: separate volatility for negative vs positive returns."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class DownUpVolAsymmetry(IndicatorBase):
    id = "down_up_vol"
    display_name = "Down-vol vs Up-vol Asymmetry"
    description = "Ratio or difference of downside vol vs upside vol"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 48}
    output_series_defs = [{"id": "down_up_ratio", "label": "Down/Up Vol Ratio"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 48))
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
            down_r = [x for x in r if x < 0]
            up_r = [x for x in r if x > 0]
            down_var = sum(x * x for x in down_r) / len(r) if r else 0
            up_var = sum(x * x for x in up_r) / len(r) if r else 0
            down_vol = down_var ** 0.5
            up_vol = up_var ** 0.5
            ratio = (down_vol / up_vol) if up_vol > 0 else 0.0
            out.append((times[i], ratio))
        return ({"down_up_ratio": out}, None)
