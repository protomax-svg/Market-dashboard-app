"""
Base class for indicator plugins: id, display_name, required_inputs, parameters, compute(), output_series.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

# Output: list of (timestamp_ms, value) per series name
OutputSeries = Dict[str, List[Tuple[int, float]]]


class IndicatorBase(ABC):
    id: str = "base"
    display_name: str = "Base"
    description: str = ""

    # e.g. [{"name": "candles", "timeframe": "1m"}], optional "liquidations"
    required_inputs: List[Dict[str, str]] = []

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
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        """
        Compute indicator. Candles have open_time, open, high, low, close, volume.
        If incremental=True, only compute latest point (candles may be just new ones).
        last_state is previous state for incremental; return new state for next call.
        Returns (output_series, new_state).
        """
        pass
