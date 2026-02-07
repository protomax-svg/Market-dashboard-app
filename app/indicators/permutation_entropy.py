"""Permutation Entropy: ordinal pattern complexity."""
from collections import Counter
from math import log
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


def _permutation_entropy_1d(series: List[float], order: int) -> float:
    if len(series) < order + 1:
        return 0.0
    patterns: List[Tuple[int, ...]] = []
    for i in range(len(series) - order):
        window = series[i : i + order + 1]
        perm = tuple(sorted(range(len(window)), key=lambda j: window[j]))
        patterns.append(perm)
    if not patterns:
        return 0.0
    c = Counter(patterns)
    n = len(patterns)
    pe = 0.0
    for count in c.values():
        p = count / n
        if p > 0:
            pe -= p * log(p)
    return pe / log(2) if order > 0 else 0.0


class PermutationEntropy(IndicatorBase):
    id = "permutation_entropy"
    display_name = "Permutation Entropy"
    description = "Ordinal pattern complexity (permutation entropy)"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 64, "order": 3}
    output_series_defs = [{"id": "pe", "label": "Permutation Entropy"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 64))
        order = int(self.parameters.get("order", 3))
        if len(candles) < window:
            return ({}, None)
        closes = [c["close"] for c in candles]
        times = [c["open_time"] for c in candles]
        out: List[Tuple[int, float]] = []
        for i in range(window - 1, len(closes)):
            seg = closes[i - window + 1 : i + 1]
            pe = _permutation_entropy_1d(seg, order)
            out.append((times[i], pe))
        return ({"pe": out}, None)
