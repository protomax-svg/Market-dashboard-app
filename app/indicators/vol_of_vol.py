"""Vol-of-vol: std of rolling volatility (ATR or realized vol)."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


class VolOfVol(IndicatorBase):
    id = "vol_of_vol"
    display_name = "Vol-of-Vol"
    description = "Std of rolling volatility (ATR-based)"
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
        if len(candles) < vw + vovw:
            return ({}, None)
        times = [c["open_time"] for c in candles]
        atrs: List[float] = []
        for i in range(vw - 1, len(candles)):
            trs = []
            for j in range(i - vw + 1, i + 1):
                h = candles[j]["high"]
                l = candles[j]["low"]
                prev_c = candles[j - 1]["close"] if j > 0 else candles[j]["open"]
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                trs.append(tr)
            atrs.append((times[i], sum(trs) / len(trs)))
        if len(atrs) < vovw:
            return ({}, None)
        out: List[Tuple[int, float]] = []
        vol_vals = [a[1] for a in atrs]
        for i in range(vovw - 1, len(vol_vals)):
            seg = vol_vals[i - vovw + 1 : i + 1]
            mean = sum(seg) / len(seg)
            var = sum((x - mean) ** 2 for x in seg) / len(seg)
            vov = var ** 0.5
            out.append((atrs[i][0], vov))
        return ({"vov": out}, None)
