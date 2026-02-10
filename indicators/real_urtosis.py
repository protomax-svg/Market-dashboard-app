# indicators/realized_kurtosis.py
"""
Realized Kurtosis (rolling) on returns.

Purpose
- Measures tail risk / "fat tails" in recent returns.
- Higher kurtosis => more extreme moves relative to typical variance.

Design (matches plugin criteria)
- Subclasses IndicatorBase.
- Uses required_inputs with explicit timeframe (default 1m).
- Parameters are configurable.
- Returns {"kurt": [(ts_ms, value), ...]} where ts_ms aligns to the candle at
  the END of each rolling window.
- No look-ahead: each point uses only data up to that timestamp.

Notes
- By default outputs EXCESS kurtosis (kurtosis - 3), so ~0 is "normal-like".
- Uses log-returns by default.
- Uses O(N) rolling raw-moment sums (fast enough for realtime).

Inputs
- candles: list of dicts {open_time, open, high, low, close, volume}

Output series
- "kurt": [(timestamp_ms, value), ...]

Parameters
- window: int, number of returns in rolling window (e.g. 300 for 1m ≈ 5h)
- use_excess: bool, True => excess kurtosis (k-3)
- use_log_returns: bool, True => log returns, False => simple returns
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class RealizedKurtosis(IndicatorBase):
    id = "realized_kurtosis"
    display_name = "Realized Kurtosis"
    description = "Rolling kurtosis of returns (tail risk / fat tails)."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {
        "window": 300,
        "use_excess": True,
        "use_log_returns": True,
    }
    output_series_defs = [{"id": "kurt", "label": "Kurtosis"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        w = int(self.parameters.get("window", 300))
        use_excess = bool(self.parameters.get("use_excess", True))
        use_log = bool(self.parameters.get("use_log_returns", True))

        # Need at least w returns => w+1 candles
        if w < 20 or len(candles) < w + 1:
            return ({}, None)

        closes = [float(c["close"]) for c in candles]
        times = [int(c["open_time"]) for c in candles]

        def ret(i: int) -> float:
            """Return for candle i (uses closes[i-1] -> closes[i])."""
            a, b = closes[i - 1], closes[i]
            if a <= 0 or b <= 0:
                return 0.0
            if use_log:
                return math.log(b / a)
            return (b / a) - 1.0

        # Rolling raw moment sums over window of returns:
        # s1 = sum(x), s2 = sum(x^2), s3 = sum(x^3), s4 = sum(x^4)
        s1 = s2 = s3 = s4 = 0.0

        # Seed with returns for indices 1..w (window size = w)
        for i in range(1, w + 1):
            x = ret(i)
            s1 += x
            s2 += x * x
            s3 += x * x * x
            s4 += x * x * x * x

        def kurt_from_sums() -> float:
            n = float(w)
            mean = s1 / n
            ex2 = s2 / n
            # m2 = E[(x-mean)^2] = E[x^2] - mean^2
            m2 = ex2 - mean * mean
            if m2 <= 1e-18:
                return 0.0
            ex3 = s3 / n
            ex4 = s4 / n
            # m4 = E[(x-mean)^4]
            m4 = ex4 - 4.0 * mean * ex3 + 6.0 * (mean ** 2) * ex2 - 3.0 * (mean ** 4)
            k = m4 / (m2 * m2)
            return (k - 3.0) if use_excess else k

        out: List[Tuple[int, float]] = []
        # First kurtosis point aligns to candle index w (end of first window)
        out.append((times[w], kurt_from_sums()))

        # Slide window forward: for each new candle i, remove return(i-w), add return(i)
        # Returns index corresponds to candle index (uses i-1 -> i), so:
        # - when current end is i, window holds returns [i-w+1 .. i]
        for i in range(w + 1, len(candles)):
            # Remove oldest return in window: index (i - w)
            old = ret(i - w)
            s1 -= old
            s2 -= old * old
            s3 -= old * old * old
            s4 -= old * old * old * old

            # Add newest return: index i
            x = ret(i)
            s1 += x
            s2 += x * x
            s3 += x * x * x
            s4 += x * x * x * x

            out.append((times[i], kurt_from_sums()))

        return ({"kurt": out}, None)
