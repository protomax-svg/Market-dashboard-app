# indicators/composite/regime_index.py
"""
Regime Index: composite indicator that uses ONLY other indicators' data (no candles).

What it measures:
- A single composite line combining stress, downside risk, and anti-structure.
- Higher values => more stress / downside dominance / disorder (risk-off).
- Lower values => calmer / more structure / less downside (risk-on).

Interpretation:
- Regime level low (e.g. 0.2–0.4): calm, structured, low stress.
- Regime level mid (e.g. 0.4–0.6): normal.
- Regime level high (e.g. 0.6–0.9): stress, downside skew, disorder.

Data: This indicator lives in indicators/composite/ and declares required_indicator_ids.
The app runs those indicators first and passes their output as indicator_series=.
No candle-based computation; all inputs come from other indicators.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


# Default percentile window; increase for longer lookback. Reload indicators after editing.
INDEX_WINDOW = 100000
# Neutral value for missing components so we can draw from earliest available data
NEUTRAL = 0.5

# Which series key to take from each dependency indicator
PRIMARY_SERIES: Dict[str, str] = {
    "vol_of_vol": "vov",
    "perm_entropy": "pe",
    "realized_kurtosis": "kurt",
    "amihud_illiquidity": "amihud",
    "down_up_vol_asym": "asym",
    "rolling_hurst": "hurst",
    "ulcer_index": "ui",
    "rolling_max_drawdown": "mdd",
}


def _ts_ms(t: Any) -> int:
    """Normalize to milliseconds: if < 1e12, multiply by 1000."""
    ti = int(t) if t is not None else 0
    return ti * 1000 if ti < 1_000_000_000_000 else ti


def _rolling_percentile(
    series: List[Tuple[int, float]], norm_window: int
) -> List[Tuple[int, float]]:
    """Percentile over last norm_window values; rank/(n-1). Uses sorted list + bisect."""
    if norm_window < 2 or len(series) < norm_window:
        return []
    out: List[Tuple[int, float]] = []
    window_vals: deque = deque(maxlen=norm_window)
    sorted_vals: List[float] = []

    for t, val in series:
        if not math.isfinite(val):
            continue
        if len(window_vals) == norm_window:
            old = window_vals.popleft()
            idx = bisect.bisect_left(sorted_vals, old)
            if idx < len(sorted_vals) and sorted_vals[idx] == old:
                del sorted_vals[idx]
            elif idx > 0 and sorted_vals[idx - 1] == old:
                del sorted_vals[idx - 1]
        window_vals.append(val)
        bisect.insort(sorted_vals, val)
        if len(sorted_vals) < norm_window:
            continue
        n = len(sorted_vals)
        rank = bisect.bisect_right(sorted_vals, val) - 1
        pct = rank / (n - 1) if n > 1 else 0.5
        out.append((t, max(0.0, min(1.0, pct))))
    return out


def _align_series(
    series_by_key: Dict[str, List[Tuple[int, float]]],
    all_ts: List[int],
) -> Dict[str, Dict[int, float]]:
    """For each key, build t -> value (last known at or before t)."""
    result: Dict[str, Dict[int, float]] = {k: {} for k in series_by_key}
    for k, lst in series_by_key.items():
        if not lst:
            continue
        lst = sorted(lst, key=lambda x: x[0])
        j = 0
        last_val: Optional[float] = None
        for t in all_ts:
            while j < len(lst) and lst[j][0] <= t:
                last_val = lst[j][1]
                j += 1
            if last_val is not None and math.isfinite(last_val):
                result[k][t] = last_val
    return result


def _ema_series(
    series: List[Tuple[int, float]], period: int
) -> List[Tuple[int, float]]:
    """EMA: alpha = 2/(period+1), init with first value."""
    if period < 1 or not series:
        return []
    alpha = 2.0 / (period + 1)
    out: List[Tuple[int, float]] = []
    ema: Optional[float] = None
    for t, x in series:
        if not math.isfinite(x):
            continue
        if ema is None:
            ema = x
        else:
            ema = alpha * x + (1.0 - alpha) * ema
        out.append((t, ema))
    return out


def _get_primary_series(
    indicator_series: Dict[str, OutputSeries], indicator_id: str
) -> List[Tuple[int, float]]:
    """Get the primary series for one dependency. Normalize timestamps to ms (if t < 1e12 treat as seconds)."""
    out = indicator_series.get(indicator_id)
    if not out:
        return []
    key = PRIMARY_SERIES.get(indicator_id)
    if not key:
        return []
    raw = out.get(key)
    if not raw:
        return []
    return [(_ts_ms(t), float(v)) for t, v in raw if math.isfinite(float(v))]


class RegimeIndex(IndicatorBase):
    id = "regime_index"
    display_name = "Regime Index"
    description = "Composite regime from other indicators: stress + downside + anti-structure (calm/normal/stress)."
    required_inputs = []  # composite: no candles
    required_indicator_ids = [
        "vol_of_vol",
        "perm_entropy",
        "realized_kurtosis",
        "amihud_illiquidity",
        "down_up_vol_asym",
        "rolling_hurst",
        "ulcer_index",
        "rolling_max_drawdown",
    ]
    parameters = {
        "norm_window": INDEX_WINDOW,
        "min_components": 1,  # output when at least this many components available (1–7); missing = NEUTRAL
        "fast_ema_period": 20,
        "slow_ema_period": 200,
        "w_stress": 0.6,
        "w_downside": 0.3,
        "w_anti_structure": 0.1,
    }
    output_series_defs = [
        {"id": "regime", "label": "Regime"},
        {"id": "regime_fast", "label": "Regime Fast"},
        {"id": "regime_slow", "label": "Regime Slow"},
    ]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
        indicator_series: Optional[Dict[str, OutputSeries]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        if not indicator_series or len(indicator_series) < len(self.required_indicator_ids):
            return ({"regime": [], "regime_fast": [], "regime_slow": []}, None)

        norm_window = max(2, int(self.parameters.get("norm_window", INDEX_WINDOW)))
        min_components = max(1, min(8, int(self.parameters.get("min_components", 1))))
        fast_ema_period = max(1, min(30, int(self.parameters.get("fast_ema_period", 20))))
        slow_ema_period = max(1, min(300, int(self.parameters.get("slow_ema_period", 200))))
        w_stress = float(self.parameters.get("w_stress", 0.6))
        w_downside = float(self.parameters.get("w_downside", 0.3))
        w_anti_structure = float(self.parameters.get("w_anti_structure", 0.1))

        vov_raw = _get_primary_series(indicator_series, "vol_of_vol")
        kurt_raw = _get_primary_series(indicator_series, "realized_kurtosis")
        amihud_raw = _get_primary_series(indicator_series, "amihud_illiquidity")
        ui_raw = _get_primary_series(indicator_series, "ulcer_index")
        asym_raw = _get_primary_series(indicator_series, "down_up_vol_asym")
        hurst_raw = _get_primary_series(indicator_series, "rolling_hurst")
        pe_raw = _get_primary_series(indicator_series, "perm_entropy")
        mdd_raw = _get_primary_series(indicator_series, "rolling_max_drawdown")
        

        mdd_pain_raw = [(t, abs(v)) for t, v in mdd_raw if math.isfinite(v)]
        lengths = [len(s) for s in [vov_raw, kurt_raw, amihud_raw, ui_raw, asym_raw, hurst_raw, pe_raw] if s]
        effective_norm = min(norm_window, max(10, min(lengths) // 2)) if lengths else norm_window

        vov_pct = _rolling_percentile(vov_raw, effective_norm)
        mdd_pct = _rolling_percentile(mdd_pain_raw, effective_norm)
        kurt_pct = _rolling_percentile(kurt_raw, effective_norm)
        amihud_pct = _rolling_percentile(amihud_raw, effective_norm)
        ui_pct = _rolling_percentile(ui_raw, effective_norm)
        asym_pct = _rolling_percentile(asym_raw, effective_norm)
        hurst_pct = _rolling_percentile(hurst_raw, effective_norm)
        one_minus_pe_raw = [(t, 1.0 - v) for t, v in pe_raw if math.isfinite(v)]
        one_minus_pe_pct = _rolling_percentile(one_minus_pe_raw, effective_norm)


        # Union of all timestamps in ms (normalize again in case any dependency used seconds)
        all_ts_set: set[int] = set()
        for lst in [vov_pct, kurt_pct, amihud_pct, ui_pct, mdd_pct, asym_pct, hurst_pct, one_minus_pe_pct]:
            for t, _ in lst:
                all_ts_set.add(_ts_ms(t))
        all_ts = sorted(all_ts_set)

        aligned = _align_series(
            {
                "vov": vov_pct,
                "kurt": kurt_pct,
                "amihud": amihud_pct,
                "ui": ui_pct,
                "mdd": mdd_pct,
                "asym": asym_pct,
                "hurst": hurst_pct,
                "one_pe": one_minus_pe_pct,
            },
            all_ts,
        )

        regime_raw: List[Tuple[int, float]] = []
        for t in all_ts:
            vov = aligned["vov"].get(t)
            kurt = aligned["kurt"].get(t)
            amihud = aligned["amihud"].get(t)
            ui = aligned["ui"].get(t)
            mdd = aligned["mdd"].get(t)
            asym = aligned["asym"].get(t)
            hurst = aligned["hurst"].get(t)
            one_pe = aligned["one_pe"].get(t)
            vals = [vov, kurt, amihud, ui, mdd, asym, hurst, one_pe]
            n_present = sum(1 for v in vals if v is not None and math.isfinite(v))
            if n_present < min_components:
                continue
            vov = vov if vov is not None and math.isfinite(vov) else NEUTRAL
            kurt = kurt if kurt is not None and math.isfinite(kurt) else NEUTRAL
            amihud = amihud if amihud is not None and math.isfinite(amihud) else NEUTRAL
            ui = ui if ui is not None and math.isfinite(ui) else NEUTRAL
            mdd = mdd if mdd is not None and math.isfinite(mdd) else NEUTRAL
            asym = asym if asym is not None and math.isfinite(asym) else NEUTRAL
            hurst = hurst if hurst is not None and math.isfinite(hurst) else NEUTRAL
            one_pe = one_pe if one_pe is not None and math.isfinite(one_pe) else NEUTRAL
            stress = (vov + kurt + amihud + ui) / 4.0
            structure = (one_pe + hurst) / 2.0
            downside = (asym + mdd) / 2.0
            ri = w_stress * stress + w_downside * downside + w_anti_structure * (1.0 - structure)
            if math.isfinite(ri):
                ri = max(0.0, min(1.0, ri))
                regime_raw.append((t, ri))

        regime_fast = _ema_series(regime_raw, fast_ema_period)
        regime_slow = _ema_series(regime_raw, slow_ema_period)

        return (
            {
                "regime": regime_raw,
                "regime_fast": regime_fast,
                "regime_slow": regime_slow,
            },
            None,
        )
