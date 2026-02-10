"""Vol-of-vol: rolling std of rolling volatility (ATR via Wilder smoothing)."""
from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class VolOfVol(IndicatorBase):
    id = "vol_of_vol"
    display_name = "Vol-of-Vol"
    description = "Std of rolling volatility (ATR-based, Wilder smoothing)"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"vol_window": 20, "vov_window": 30}
    output_series_defs = [{"id": "vov", "label": "Vol-of-Vol"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        vw = int(self.parameters.get("vol_window", 20))
        vovw = int(self.parameters.get("vov_window", 30))

        if vw < 2 or vovw < 2:
            return ({}, None)

        n = len(candles)
        if n < (vw + vovw):
            return ({}, None)

        # ---------- Helpers ----------
        def _tr(curr: Dict[str, Any], prev_close: float) -> float:
            h = float(curr["high"])
            l = float(curr["low"])
            return max(h - l, abs(h - prev_close), abs(l - prev_close))

        # ---------- Incremental path ----------
        # State schema (stored at end of compute for next call):
        # {
        #   "last_open_time": int,
        #   "atr": float,
        #   "atr_initialized": bool,
        #   "init_tr_sum": float,      # only used until atr_initialized becomes True
        #   "init_tr_count": int,      # number of TRs accumulated for initialization
        #   "prev_close": float,
        #   "atr_buf": [float, ...],   # last vovw ATR values (for rolling std)
        #   "sum_atr": float,
        #   "sumsq_atr": float
        # }
        if incremental and last_state:
            last_t = last_state.get("last_open_time")
            if isinstance(last_t, int):
                # Find where new candles start (assumes candles are sorted by open_time)
                start_idx = None
                for i, c in enumerate(candles):
                    if int(c["open_time"]) > last_t:
                        start_idx = i
                        break

                # If nothing new, return empty update but keep state
                if start_idx is None:
                    return ({"vov": []}, last_state)

                # If the caller passed a truncated history (missing the previous candle),
                # incremental TR can't be computed safely → fallback to full recompute.
                if start_idx == 0:
                    incremental = False
                else:
                    # Continue from saved state
                    prev_close = float(last_state["prev_close"])
                    atr = float(last_state.get("atr", 0.0))
                    atr_initialized = bool(last_state.get("atr_initialized", False))
                    init_tr_sum = float(last_state.get("init_tr_sum", 0.0))
                    init_tr_count = int(last_state.get("init_tr_count", 0))

                    atr_buf = deque(last_state.get("atr_buf", []), maxlen=vovw)  # type: ignore[arg-type]
                    sum_atr = float(last_state.get("sum_atr", 0.0))
                    sumsq_atr = float(last_state.get("sumsq_atr", 0.0))

                    out: List[Tuple[int, float]] = []

                    for i in range(start_idx, n):
                        c = candles[i]
                        t = int(c["open_time"])
                        tr = _tr(c, prev_close)
                        prev_close = float(c["close"])

                        if not atr_initialized:
                            init_tr_sum += tr
                            init_tr_count += 1
                            if init_tr_count == vw:
                                atr = init_tr_sum / vw
                                atr_initialized = True
                            else:
                                # ATR not ready yet -> can't emit VOV
                                last_t = t
                                continue
                        else:
                            # Wilder ATR update
                            atr = ((atr * (vw - 1)) + tr) / vw

                        # Update rolling buffer for std(ATR)
                        if len(atr_buf) == vovw:
                            old = atr_buf[0]
                            sum_atr -= old
                            sumsq_atr -= old * old

                        atr_buf.append(atr)
                        sum_atr += atr
                        sumsq_atr += atr * atr

                        if len(atr_buf) == vovw:
                            mean = sum_atr / vovw
                            var = (sumsq_atr / vovw) - (mean * mean)
                            vov = (var if var > 0 else 0.0) ** 0.5
                            out.append((t, vov))

                        last_t = t

                    new_state = {
                        "last_open_time": int(candles[-1]["open_time"]),
                        "atr": atr,
                        "atr_initialized": atr_initialized,
                        "init_tr_sum": init_tr_sum,
                        "init_tr_count": init_tr_count,
                        "prev_close": prev_close,
                        "atr_buf": list(atr_buf),
                        "sum_atr": sum_atr,
                        "sumsq_atr": sumsq_atr,
                    }
                    return ({"vov": out}, new_state)

        # ---------- Full recompute path (fast O(N)) ----------
        # 1) TR series
        trs: List[float] = [0.0] * n
        prev_close = float(candles[0].get("open", candles[0]["close"]))
        for i in range(n):
            trs[i] = _tr(candles[i], prev_close)
            prev_close = float(candles[i]["close"])

        # 2) ATR via Wilder: first ATR = SMA of first vw TRs (ending at index vw-1)
        atrs: List[Tuple[int, float]] = []
        tr_sum = sum(trs[0:vw])
        atr = tr_sum / vw
        atrs.append((int(candles[vw - 1]["open_time"]), atr))

        for i in range(vw, n):
            atr = ((atr * (vw - 1)) + trs[i]) / vw
            atrs.append((int(candles[i]["open_time"]), atr))

        # 3) Vol-of-Vol: rolling std over ATR values (window vovw) using sum/sumsq
        out: List[Tuple[int, float]] = []
        buf: Deque[float] = deque(maxlen=vovw)
        sum_atr = 0.0
        sumsq_atr = 0.0

        for t, a in atrs:
            if len(buf) == vovw:
                old = buf[0]
                sum_atr -= old
                sumsq_atr -= old * old

            buf.append(a)
            sum_atr += a
            sumsq_atr += a * a

            if len(buf) == vovw:
                mean = sum_atr / vovw
                var = (sumsq_atr / vovw) - (mean * mean)
                vov = (var if var > 0 else 0.0) ** 0.5
                out.append((t, vov))

        # Build state for future incremental updates
        final_prev_close = float(candles[-1]["close"])
        state = {
            "last_open_time": int(candles[-1]["open_time"]),
            "atr": atr,
            "atr_initialized": True,
            "init_tr_sum": float(tr_sum),
            "init_tr_count": vw,
            "prev_close": final_prev_close,
            "atr_buf": list(buf),
            "sum_atr": sum_atr,
            "sumsq_atr": sumsq_atr,
        }

        return ({"vov": out}, state)
