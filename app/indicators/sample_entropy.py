"""Sample Entropy: regularity measure (lower = more regular)."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


def _max_dist(x: List[float], y: List[float]) -> float:
    return max(abs(a - b) for a, b in zip(x, y))


def _sample_entropy(series: List[float], m: int, r: float) -> float:
    import math
    n = len(series)
    if n < m + 2:
        return 0.0
    std = (sum((x - sum(series) / n) ** 2 for x in series) / n) ** 0.5
    r = r * std if std > 0 else 0.001
    if r <= 0:
        r = 0.001

    def _count_matches(m_len: int) -> int:
        patterns = [tuple(series[i : i + m_len]) for i in range(n - m_len + 1)]
        matches = 0
        for i in range(len(patterns)):
            for j in range(len(patterns)):
                if i != j and _max_dist(list(patterns[i]), list(patterns[j])) <= r:
                    matches += 1
        return matches

    B = _count_matches(m)
    A = _count_matches(m + 1)
    if B == 0 or A == 0:
        return 0.0
    return -math.log(A / B)

class SampleEntropy(IndicatorBase):
    id = "sample_entropy"
    display_name = "Sample Entropy"
    description = "Regularity measure (Lempel–Ziv style complexity)"
    required_inputs = [{"name": "candles", "timeframe": "1m"}]
    parameters = {"window": 64, "m": 2, "r": 0.15}
    output_series_defs = [{"id": "sampen", "label": "Sample Entropy"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        window = int(self.parameters.get("window", 64))
        m = int(self.parameters.get("m", 2))
        r = float(self.parameters.get("r", 0.15))
        if len(candles) < window:
            return ({}, None)
        closes = [c["close"] for c in candles]
        times = [c["open_time"] for c in candles]
        out: List[Tuple[int, float]] = []
        for i in range(window - 1, len(closes)):
            seg = closes[i - window + 1 : i + 1]
            se = _sample_entropy(seg, m, r)
            out.append((times[i], se))
        return ({"sampen": out}, None)
