# indicators/rolling_max_drawdown.py
import math
from app.indicators.base import IndicatorBase, OutputSeries

def _ts_ms(t):
    t = int(t)
    # if seconds -> convert to ms
    return t * 1000 if t < 1_000_000_000_000 else t

class RollingMaxDrawdown(IndicatorBase):
    id = "rolling_max_drawdown"
    display_name = "Rolling Max Drawdown"
    description = "Rolling maximum drawdown (most negative drawdown) on close."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300}
    output_series_defs = [{"id": "mdd", "label": "MDD"}]

    def compute(self, candles, timeframe, liquidations=None, incremental=False, last_state=None):
        window = int(self.parameters.get("window", 300))
        if window < 10:
            window = 10

        if len(candles) < window:
            return ({}, None)

        times = [_ts_ms(c["open_time"]) for c in candles]
        closes = [float(c["close"]) for c in candles]

        out = []
        for i in range(window - 1, len(closes)):
            peak = closes[i - window + 1]
            mdd = 0.0  # drawdown <= 0
            ok = True

            for p in closes[i - window + 1 : i + 1]:
                if p > peak:
                    peak = p
                if peak <= 0.0:
                    ok = False
                    break
                dd = (p / peak) - 1.0
                if dd < mdd:
                    mdd = dd

            if ok and math.isfinite(mdd):
                out.append((times[i], float(mdd)))

        return ({"mdd": out}, None)
