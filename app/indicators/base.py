"""
Base class for indicator plugins: id, display_name, required_inputs, parameters, compute(), output_series.

Composite indicators: set required_indicator_ids = [list of indicator ids]. The app will run those
indicators first and pass their output as indicator_series=Dict[indicator_id, OutputSeries].
Composite compute() receives indicator_series and uses it instead of candles (candles may be []).
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

# Output: list of (timestamp_ms, value) per series name
OutputSeries = Dict[str, List[Tuple[int, float]]]

# For composite indicators: indicator_id -> that indicator's OutputSeries
IndicatorSeriesInput = Dict[str, OutputSeries]


class IndicatorBase(ABC):
    id: str = "base"
    display_name: str = "Base"
    description: str = ""

    # e.g. [{"name": "candles", "timeframe": "1m"}], optional "liquidations"
    required_inputs: List[Dict[str, str]] = []

    # Composite indicators only: list of indicator ids whose output this indicator needs.
    # When set, the app runs those indicators first and passes indicator_series= to compute().
    required_indicator_ids: List[str] = []

    # e.g. {"window": 20, "order": 3}
    parameters: Dict[str, Any] = {}

    # e.g. [{"id": "value", "label": "Value"}]
    output_series_defs: List[Dict[str, str]] = []

    @classmethod
    def get_default_parameters(cls) -> Dict[str, Any]:
        return dict(cls.parameters)

    @abstractmethod
    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
        indicator_series: Optional[IndicatorSeriesInput] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        """
        Compute indicator. Candles have open_time, open, high, low, close, volume.
        For composite indicators, required_indicator_ids is set and the app passes
        indicator_series=Dict[indicator_id, OutputSeries]; candles may be [].
        If incremental=True, only compute latest point.
        Returns (output_series, new_state).
        """
        pass
