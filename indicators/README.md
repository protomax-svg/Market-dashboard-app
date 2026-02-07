# User indicator plugins

Drop a new Python module file here to add custom indicators. The app discovers any class that subclasses `IndicatorBase` from `app.indicators.base`.

**Example** (`indicators/my_custom.py`):

```python
from typing import Any, Dict, List, Optional, Tuple
from app.indicators.base import IndicatorBase, OutputSeries

class MyCustom(IndicatorBase):
    id = "my_custom"
    display_name = "My Custom"
    description = "Custom indicator"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 20}
    output_series_defs = [{"id": "value", "label": "Value"}]

    def compute(self, candles, timeframe, liquidations=None, incremental=False, last_state=None):
        # candles: list of {open_time, open, high, low, close, volume}
        # return ({"value": [(ts_ms, value), ...]}, state)
        window = self.parameters.get("window", 20)
        if len(candles) < window:
            return ({}, None)
        times = [c["open_time"] for c in candles]
        closes = [c["close"] for c in candles]
        out = [(times[i], sum(closes[i-window+1:i+1])/window) for i in range(window-1, len(closes))]
        return ({"value": out}, None)
```

Restart the app to see the new indicator in the **Indicators** menu and as a dock panel.
