# indicators/ulcer_index.py
import math
from app.indicators.base import IndicatorBase, OutputSeries

class UlcerIndex(IndicatorBase):
    id = "ulcer_index"
    display_name = "Ulcer Index"
    description = "Rolling Ulcer Index (drawdown depth + duration) on close."
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 300}
    output_series_defs = [{"id": "ui", "label": "Ulcer"}]

    def compute(self, candles, timeframe, liquidations=None, incremental=False, last_state=None):
        window = int(self.parameters.get("window", 300))
        if window < 10:
            window = 10

        if len(candles) < window:
            return ({}, None)

        times = [int(c["open_time"]) for c in candles]
        closes = [float(c["close"]) for c in candles]

        out = []
        for i in range(window - 1, len(closes)):
            chunk = closes[i - window + 1 : i + 1]
            peak = chunk[0]
            s = 0.0
            ok = True
            for p in chunk:
                if p > peak:
                    peak = p
                if peak <= 0.0:
                    ok = False
                    break
                dd_pct = 100.0 * (p / peak - 1.0)  # <= 0
                s += dd_pct * dd_pct
            if not ok:
                continue
            ui = math.sqrt(s / window)
            if math.isfinite(ui):
                out.append((times[i], float(ui)))

        return ({"ui": out}, None)
