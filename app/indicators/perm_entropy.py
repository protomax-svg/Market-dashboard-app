# indicators/permutation_entropy.py
"""
Permutation Entropy (PE) indicator.

What it measures:
- Market "structure vs noise" using ordinal patterns of price changes.
- Low PE  -> more ordered / trending / structured regime
- High PE -> more random / choppy regime

Implementation notes:
- Uses ordinal patterns of embedding dimension m (default 5) and delay tau (default 1).
- Computes rolling Shannon entropy over a sliding window of patterns.
- Normalized to [0..1] by dividing by log(m!).

Inputs:
- candles (OHLCV) for the selected timeframe (5m/15m/1h)

Output series:
- "pe": [(timestamp_ms, value), ...]

Tuning:
- embed_dim (m): 3..7 is typical (5 is a good default)
- tau: usually 1 for candles
- window: number of patterns in the rolling window (e.g. 200–1000)
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


def _factorials_upto(n: int) -> List[int]:
    f = [1] * (n + 1)
    for i in range(2, n + 1):
        f[i] = f[i - 1] * i
    return f


def _perm_to_lehmer_index(perm: List[int], facts: List[int]) -> int:
    """
    Map a permutation of [0..m-1] to [0..m!-1] via Lehmer code.
    perm is the ranking order (e.g., [2,0,1,3,4] means rank0 at position1, etc.)
    """
    m = len(perm)
    idx = 0
    used = [False] * m
    for i in range(m):
        x = perm[i]
        # count unused < x
        c = 0
        for v in range(x):
            if not used[v]:
                c += 1
        idx += c * facts[m - 1 - i]
        used[x] = True
    return idx


def _ordinal_pattern(values: List[float]) -> List[int]:
    """
    Convert list of m floats into an ordinal pattern (permutation of ranks 0..m-1).
    Tie-breaking: stable by index (rare in prices; stable tie-break avoids crashes).
    """
    # sort by (value, original_index)
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0] * len(values)
    for r, i in enumerate(order):
        ranks[i] = r
    return ranks


def _shannon_entropy_from_counts(counts: List[int], window_size: int, log_base: float) -> float:
    """
    H = -sum(p log p) / log_base
    where log_base = log(m!) if normalized, else 1.
    """
    if window_size <= 0:
        return 0.0
    inv = 1.0 / window_size
    h = 0.0
    for c in counts:
        if c:
            p = c * inv
            h -= p * math.log(p)
    return h / log_base if log_base > 0 else h


class PermutationEntropy(IndicatorBase):
    id = "perm_entropy"
    display_name = "Permutation Entropy"
    description = "Rolling permutation entropy of price ordinal patterns (structure vs noise)."
    required_inputs = [{"name": "candles", "timeframe": "any"}]
    parameters = {
        "embed_dim": 5,     # m
        "delay": 1,         # tau
        "window": 300,      # number of patterns in rolling window
        "use_close": True,  # if False you can switch to e.g. HL2 later
        "normalize": True,
    }
    output_series_defs = [{"id": "pe", "label": "Permutation Entropy"}]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        m = int(self.parameters.get("embed_dim", 5))
        tau = int(self.parameters.get("delay", 1))
        w = int(self.parameters.get("window", 300))
        normalize = bool(self.parameters.get("normalize", True))

        if m < 3 or m > 7:
            # keep factorial bins small; 3..7 is typical
            return ({}, None)
        if tau < 1 or w < 10:
            return ({}, None)

        n = len(candles)
        span = (m - 1) * tau
        if n <= span + w:
            return ({}, None)

        closes = [float(c["close"]) for c in candles]
        times = [int(c["open_time"]) for c in candles]

        facts = _factorials_upto(m)
        bins = facts[m]  # m!
        log_base = math.log(bins) if normalize else 1.0

        # 1) Build pattern ids for all possible pattern positions
        # pattern at i uses closes[i + k*tau] for k=0..m-1
        pat_ids: List[int] = []
        pat_times: List[int] = []
        for i in range(0, n - span):
            vals = [closes[i + k * tau] for k in range(m)]
            ranks = _ordinal_pattern(vals)
            pid = _perm_to_lehmer_index(ranks, facts)
            pat_ids.append(pid)
            # associate pattern time with the last candle in the pattern
            pat_times.append(times[i + span])

        if len(pat_ids) < w:
            return ({}, None)

        # 2) Rolling entropy over pattern ids
        counts = [0] * bins
        window: Deque[int] = deque(maxlen=w)

        # seed first window
        for pid in pat_ids[:w]:
            window.append(pid)
            counts[pid] += 1

        out: List[Tuple[int, float]] = []
        # entropy for first window aligned to pat_times[w-1]
        out.append((pat_times[w - 1], _shannon_entropy_from_counts(counts, w, log_base)))

        for i in range(w, len(pat_ids)):
            # remove oldest
            old = window.popleft()
            counts[old] -= 1
            # add newest
            pid = pat_ids[i]
            window.append(pid)
            counts[pid] += 1

            pe = _shannon_entropy_from_counts(counts, w, log_base)
            out.append((pat_times[i], pe))

        # incremental state could be added later; return None for now
        return ({"pe": out}, None)
