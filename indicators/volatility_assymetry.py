# indicators/down_up_vol_asymmetry.py
"""
Down/Up Volatility Asymmetry (rolling).

Purpose
- Detects downside risk dominance: how much volatility comes from down moves
  versus up moves over a recent window.
- Useful regime/risk signal:
  - high asymmetry => down moves are "heavier" / more violent (risk-off)
  - low asymmetry  => upside vol dominates (often squeeze / risk-on)
  - near 1.0       => balanced

Design (matches plugin criteria)
- Subclasses IndicatorBase.
- Uses required_inputs with explicit timeframe (default 1m).
- Returns {"asym": [(ts_ms, value), ...]} where ts_ms aligns to the candle at
  the END of each rolling window.
- No look-ahead: each point uses only past/current candles.
- Lightweight O(N) rolling update (fast enough for realtime).

Inputs
- candles: list of dicts {open_time, open, high, low, close, volume}

Output series
- "asym": ratio of downside vol to upside vol (>=0)
- "down_vol": downside volatility (std of negative returns)
- "up_vol": upside volatility (std of positive returns)

Parameters
- window: int, number of returns in rolling window (e.g. 300 for 1m ≈ 5h)
- use_log_returns: bool, True => log returns, False => simple returns
- mode: "ratio" or "diff"
    - ratio: down_vol / up_vol
    - diff:  down_vol - up_vol
- eps: small float to avoid division by zero
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class DownUpVolAsymmetry(IndicatorBase):
    id = "down_up_vol_asym"
    display_name = "Down/Up Vol Asymmetry"
    description = "Rolling downside vs upside volatility (risk skew)."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {
        "window": 300,
        "use_log_returns": True,
        "mode": "ratio",  # "ratio" or "diff"
        "eps": 1e-12,
    }
    output_series_defs = [
        {"id": "asym", "label": "Asymmetry"},
        {"id": "down_vol", "label": "Down Vol"},
        {"id": "up_vol", "label": "Up Vol"},
    ]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        w = int(self.parameters.get("window", 300))
        use_log = bool(self.parameters.get("use_log_returns", True))
        mode = str(self.parameters.get("mode", "ratio")).lower()
        eps = float(self.parameters.get("eps", 1e-12))

        if w < 20 or len(candles) < w + 1:
            return ({}, None)

        closes = [float(c["close"]) for c in candles]
        times = [int(c["open_time"]) for c in candles]

        def ret(i: int) -> float:
            a, b = closes[i - 1], closes[i]
            if a <= 0 or b <= 0:
                return 0.0
            if use_log:
                return math.log(b / a)
            return (b / a) - 1.0

        # For each window we need:
        # down_vol = std(returns where r<0) over window (sample-like; we use population formula for stability)
        # up_vol   = std(returns where r>0) over window
        #
        # Maintain rolling sums for negative and positive returns separately:
        # count, sum, sumsq for each side.
        dn_n = dn_s = dn_s2 = 0.0
        up_n = up_s = up_s2 = 0.0

        # Seed first window: returns indices 1..w
        rets: List[float] = [0.0] * (w + 1)
        for i in range(1, w + 1):
            x = ret(i)
            rets[i] = x
            if x < 0:
                dn_n += 1.0
                dn_s += x
                dn_s2 += x * x
            elif x > 0:
                up_n += 1.0
                up_s += x
                up_s2 += x * x

        def vol(n: float, s: float, s2: float) -> float:
            if n <= 1.0:
                return 0.0
            mean = s / n
            var = (s2 / n) - mean * mean
            return math.sqrt(var) if var > 0 else 0.0

        out_asym: List[Tuple[int, float]] = []
        out_dn: List[Tuple[int, float]] = []
        out_up: List[Tuple[int, float]] = []

        def emit(ts: int) -> None:
            dv = vol(dn_n, dn_s, dn_s2)
            uv = vol(up_n, up_s, up_s2)
            if mode == "diff":
                a = dv - uv
            else:
                a = dv / (uv + eps)
            out_asym.append((ts, a))
            out_dn.append((ts, dv))
            out_up.append((ts, uv))

        # First point aligns to candle index w
        emit(times[w])

        # Slide window forward: remove ret(i-w), add ret(i)
        for i in range(w + 1, len(candles)):
            old = ret(i - w)
            if old < 0:
                dn_n -= 1.0
                dn_s -= old
                dn_s2 -= old * old
            elif old > 0:
                up_n -= 1.0
                up_s -= old
                up_s2 -= old * old

            x = ret(i)
            if x < 0:
                dn_n += 1.0
                dn_s += x
                dn_s2 += x * x
            elif x > 0:
                up_n += 1.0
                up_s += x
                up_s2 += x * x

            emit(times[i])

        return ({"asym": out_asym, "down_vol": out_dn, "up_vol": out_up}, None)
