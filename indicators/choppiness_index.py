"""
Choppiness Index on OHLC candles.

TR_t = max(H_t - L_t, abs(H_t - C_{t-1}), abs(L_t - C_{t-1}))
CHOP_t = 100 * log10(sum(TR over n) / (max(H over n) - min(L over n))) / log10(n)

Higher values mean noisier and less directional movement.
Lower values mean cleaner directional movement.
"""

from __future__ import annotations

from collections import deque
import math
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class ChoppinessIndex(IndicatorBase):
    id = "choppiness_index"
    display_name = "Choppiness Index"
    description = "Rolling choppiness score from true range and price span."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300, "eps": 1e-12}
    output_series_defs = [{"id": "chop", "label": "Choppiness"}]

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

        times = [int(candle["open_time"]) for candle in candles]
        highs = [float(candle["high"]) for candle in candles]
        lows = [float(candle["low"]) for candle in candles]
        closes = [float(candle["close"]) for candle in candles]

        log_window = math.log10(window)
        if log_window <= 0.0:
            return ({}, None)

        out: List[Tuple[int, float]] = []
        tr_window: deque[float] = deque()
        tr_sum = 0.0
        rolling_highs: deque[Tuple[int, float]] = deque()
        rolling_lows: deque[Tuple[int, float]] = deque()

        for end_index in range(1, len(candles)):
            high = highs[end_index]
            low = lows[end_index]
            prev_close = closes[end_index - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))

            tr_window.append(tr)
            tr_sum += tr
            if len(tr_window) > window:
                tr_sum -= tr_window.popleft()

            while rolling_highs and rolling_highs[-1][1] <= high:
                rolling_highs.pop()
            rolling_highs.append((end_index, high))

            while rolling_lows and rolling_lows[-1][1] >= low:
                rolling_lows.pop()
            rolling_lows.append((end_index, low))

            start_index = end_index - window + 1
            while rolling_highs and rolling_highs[0][0] < start_index:
                rolling_highs.popleft()
            while rolling_lows and rolling_lows[0][0] < start_index:
                rolling_lows.popleft()

            if len(tr_window) < window:
                continue

            range_span = rolling_highs[0][1] - rolling_lows[0][1]

            if range_span <= eps or tr_sum <= eps:
                chop = 100.0
            else:
                ratio = max(tr_sum / range_span, 1.0)
                chop = 100.0 * math.log10(ratio) / log_window
            if math.isfinite(chop):
                out.append((times[end_index], max(0.0, min(100.0, chop))))

        return ({"chop": out}, None)
