# indicators/amihud_illiquidity.py
"""
Rolling Amihud Illiquidity (ILLIQ)

Definition (proxy, since we have only OHLCV):
- illiq_t = |r_t| / (close_t * volume_t)
  where r_t = ln(close_t / close_{t-1})
  close*volume is a dollar-volume proxy.

Then we output rolling mean over `window` points:
- amihud = mean(illiq over window)

What it measures:
- Price impact per unit of traded value.
- Higher values -> thinner liquidity / higher impact / "stress" regime.

Notes:
- Output timestamps align to the candle at the end of the window.
- If volume <= 0 or close <= 0, that point is skipped (not added).
- Rolling mean is computed over last `window` valid illiq points.

Inputs:
- candles: list of {open_time, open, high, low, close, volume}

Output:
- "amihud": [(timestamp_ms, value), ...]
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple, Any

from app.indicators.base import IndicatorBase, OutputSeries


class AmihudIlliquidity(IndicatorBase):
    id = "amihud_illiquidity"
    display_name = "Amihud Illiquidity"
    description = "Rolling Amihud illiquidity: |log_return| / (close*volume), rolling mean."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]

    parameters = {"window": 300}

    output_series_defs = [{"id": "amihud", "label": "Amihud"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations=None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 300))
        if window < 5:
            window = 5

        if not candles:
            return ({}, last_state)

        def compute_point(prev_close: Optional[float], close: float, vol: float) -> Optional[float]:
            if prev_close is None or prev_close <= 0.0 or close <= 0.0 or vol <= 0.0:
                return None
            r = math.log(close / prev_close)
            dv = close * vol
            if dv <= 0.0:
                return None
            val = abs(r) / dv
            return val if math.isfinite(val) else None

        # Incremental mode
        if incremental and last_state:
            prev_close = last_state.get("prev_close")
            dq: Deque[float] = last_state.get("illiq_dq") or deque(maxlen=window)
            rolling_sum = float(last_state.get("rolling_sum") or 0.0)

            out: List[Tuple[int, float]] = []

            last_ot = last_state.get("last_open_time")
            start_idx = 0
            if last_ot is not None:
                for i, c in enumerate(candles):
                    if c["open_time"] > last_ot:
                        start_idx = i
                        break
                else:
                    return ({}, last_state)

            for c in candles[start_idx:]:
                close = float(c["close"])
                vol = float(c.get("volume", 0.0) or 0.0)
                ot = int(c["open_time"])

                val = compute_point(prev_close, close, vol)
                if val is not None:
                    if len(dq) == window:
                        # deque is full; subtract the element that will be dropped
                        rolling_sum -= dq[0]
                    dq.append(val)
                    rolling_sum += val

                    if len(dq) == window:
                        mean_val = rolling_sum / window
                        if math.isfinite(mean_val):
                            out.append((ot, float(mean_val)))

                prev_close = close
                last_ot = ot

            new_state = {
                "prev_close": prev_close,
                "illiq_dq": dq,
                "rolling_sum": rolling_sum,
                "last_open_time": last_ot,
            }
            return ({"amihud": out} if out else {}, new_state)

        # Full recompute mode
        prev_close: Optional[float] = None
        dq: Deque[float] = deque(maxlen=window)
        rolling_sum = 0.0
        out: List[Tuple[int, float]] = []

        for c in candles:
            close = float(c["close"])
            vol = float(c.get("volume", 0.0) or 0.0)
            ot = int(c["open_time"])

            val = compute_point(prev_close, close, vol)
            if val is not None:
                if len(dq) == window:
                    rolling_sum -= dq[0]
                dq.append(val)
                rolling_sum += val

                if len(dq) == window:
                    mean_val = rolling_sum / window
                    if math.isfinite(mean_val):
                        out.append((ot, float(mean_val)))

            prev_close = close

        state = {
            "prev_close": float(candles[-1]["close"]),
            "illiq_dq": dq,
            "rolling_sum": rolling_sum,
            "last_open_time": int(candles[-1]["open_time"]),
        }
        # Normalize Y to [0, 1] so axis is readable (raw Amihud can be 1e-8 scale)
        if out:
            vals = [v for _, v in out]
            v_min, v_max = min(vals), max(vals)
            span = v_max - v_min
            if span > 0:
                out = [(t, (v - v_min) / span) for t, v in out]
        return ({"amihud": out} if out else {}, state)
