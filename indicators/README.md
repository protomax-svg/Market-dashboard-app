# User indicator plugins (project)

Drop a new Python module file here to add custom indicators. The app discovers any class that subclasses `IndicatorBase` from `app.indicators.base`.

**Hot reload:** Use **Indicators → Reload Indicators** to re-scan and reload plugins without restarting the app. **Indicators → Open Indicators Folder** opens the user plugin directory (`<storage_path>/custom_indicators/`), which is also scanned on startup and reload.

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

Use **Indicators → Reload Indicators** to see the new indicator immediately, or restart the app.
