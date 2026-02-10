# indicators/hurst_exponent.py
"""
Rolling Hurst Exponent (R/S) on log-returns of close.

What it measures:
- Market "memory"/regime: trending vs mean-reverting vs random.
- H ~ 0.5: random walk
- H > 0.5: persistent / trend-following regime
- H < 0.5: anti-persistent / mean-reverting regime

Method:
- R/S (rescaled range) over a window of N returns:
  H = log(R/S) / log(N)

Notes:
- Output timestamps align to the candle at the end of the window.
- Uses log-returns: r_t = ln(close_t / close_{t-1})
- For stability: if std == 0 or R == 0 -> returns None for that point.

Inputs:
- candles: list of {open_time, open, high, low, close, volume}

Output:
- "hurst": [(timestamp_ms, value), ...]
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple, Any

from app.indicators.base import IndicatorBase, OutputSeries


class RollingHurstExponent(IndicatorBase):
    id = "rolling_hurst"
    display_name = "Rolling Hurst Exponent"
    description = "Rolling Hurst exponent (R/S) on log-returns of close."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]

    # window = number of returns (needs window+1 closes)
    parameters = {"window": 300}

    output_series_defs = [{"id": "hurst", "label": "Hurst"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations=None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 300))
        if window < 20:
            # too small windows produce noisy / unstable estimates
            window = 20

        if not candles:
            return ({}, last_state)

        def rs_hurst(returns: List[float]) -> Optional[float]:
            n = len(returns)
            if n < 2:
                return None
            mean_r = sum(returns) / n

            # cumulative dev from mean
            cum = 0.0
            min_c = 0.0
            max_c = 0.0
            for r in returns:
                cum += (r - mean_r)
                if cum < min_c:
                    min_c = cum
                if cum > max_c:
                    max_c = cum
            R = max_c - min_c

            # std of returns
            var = 0.0
            for r in returns:
                d = r - mean_r
                var += d * d
            var /= n
            S = math.sqrt(var)

            if S <= 0.0 or R <= 0.0:
                return None

            return math.log(R / S) / math.log(float(n))

        # Incremental mode: update only with new candles
        if incremental and last_state:
            prev_close = last_state.get("prev_close")
            dq: Deque[float] = last_state.get("returns_dq") or deque(maxlen=window)

            out: List[Tuple[int, float]] = []

            # Process only new candles since last_state's "last_open_time"
            last_ot = last_state.get("last_open_time")
            start_idx = 0
            if last_ot is not None:
                # find first candle strictly after last_ot
                # (candles are typically sorted)
                for i, c in enumerate(candles):
                    if c["open_time"] > last_ot:
                        start_idx = i
                        break
                else:
                    # nothing new
                    return ({}, last_state)

            for c in candles[start_idx:]:
                close = float(c["close"])
                ot = int(c["open_time"])

                if prev_close is not None and prev_close > 0.0 and close > 0.0:
                    r = math.log(close / prev_close)
                    dq.append(r)

                    if len(dq) == window:
                        h = rs_hurst(list(dq))
                        if h is not None and math.isfinite(h):
                            out.append((ot, float(h)))

                prev_close = close
                last_ot = ot

            new_state = {
                "prev_close": prev_close,
                "returns_dq": dq,
                "last_open_time": last_ot,
            }
            return ({"hurst": out} if out else {}, new_state)

        # Full recompute mode
        if len(candles) < window + 1:
            return ({}, {"prev_close": float(candles[-1]["close"]), "returns_dq": deque(maxlen=window), "last_open_time": int(candles[-1]["open_time"])})

        closes = [float(c["close"]) for c in candles]
        times = [int(c["open_time"]) for c in candles]

        # build log-returns
        returns: List[float] = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0.0 and closes[i] > 0.0:
                returns.append(math.log(closes[i] / closes[i - 1]))
            else:
                returns.append(0.0)

        out: List[Tuple[int, float]] = []
        for i in range(window - 1, len(returns)):
            chunk = returns[i - window + 1 : i + 1]
            h = rs_hurst(chunk)
            if h is not None and math.isfinite(h):
                # returns index i corresponds to candle index i+1 in closes/times
                out.append((times[i + 1], float(h)))

        state = {
            "prev_close": float(candles[-1]["close"]),
            "returns_dq": deque(returns[-window:], maxlen=window),
            "last_open_time": int(candles[-1]["open_time"]),
        }
        return ({"hurst": out} if out else {}, state)
