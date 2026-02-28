# indicators/composite/regime_index.py
"""
Regime Index: composite indicator that uses ONLY other indicators' outputs (no candles).

Goal:
- Single line to detect market regime changes (stress vs calm).
- Not a signal generator; it's a "market changed" gauge.

Composite design (0..1):
- stress_block: turbulence / tails / illiquidity / pain proxies (higher = worse)
- downside_block: downside dominance and tail depth (higher = worse)
- structure_block: predictability / confirmation / anti-chaos (higher = better)

Final:
    regime = w_stress*stress + w_downside*downside + w_anti_structure*(1 - structure)

Normalization:
- Each input series is converted to rolling percentile (0..1) to be comparable.
- Missing components are filled with NEUTRAL=0.5 so early output is possible.

This indicator declares required_indicator_ids; the app runs them first and passes
their output to compute() via indicator_series=.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries

# Large default. Real effective window is auto-reduced based on available history.
INDEX_WINDOW = 500_000
NEUTRAL = 0.5


# Which output series key to take from each dependency indicator.
# Must match those indicators' output_series_defs IDs.
PRIMARY_SERIES: Dict[str, str] = {
    # existing
    "vol_of_vol": "vov",
    "perm_entropy": "pe",
    "realized_kurtosis": "kurt",
    "amihud_illiquidity": "amihud",
    "down_up_vol_asym": "asym",
    "rolling_hurst": "hurst",
    "ulcer_index": "ui",
    "rolling_max_drawdown": "mdd",
    # new (OHLCV-only)
    "vol_regime_ratio": "ratio",
    "downside_dev": "downside",
    "real_skewness": "skew",
    "expected_shortfall": "es",
    "returns_autocorr": "acf",
    "vol_absret_corr": "corr",
}


def _ts_ms(t: Any) -> int:
    """Normalize to milliseconds: if < 1e12 treat as seconds and multiply by 1000."""
    ti = int(t) if t is not None else 0
    return ti * 1000 if ti < 1_000_000_000_000 else ti


def _rolling_percentile(series: List[Tuple[int, float]], norm_window: int) -> List[Tuple[int, float]]:
    """
    Rolling percentile over last norm_window values.
    pct = rank/(n-1) in sorted window. Output in [0,1].
    """
    if norm_window < 2 or len(series) < norm_window:
        return []

    out: List[Tuple[int, float]] = []
    window_vals: deque[float] = deque(maxlen=norm_window)
    sorted_vals: List[float] = []

    for t, val in series:
        if not math.isfinite(val):
            continue

        # remove old
        if len(window_vals) == norm_window:
            old = window_vals.popleft()
            idx = bisect.bisect_left(sorted_vals, old)
            # robust removal for duplicates
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
        pct = rank / (n - 1) if n > 1 else NEUTRAL
        out.append((t, max(0.0, min(1.0, pct))))

    return out


def _align_series(
    series_by_key: Dict[str, List[Tuple[int, float]]],
    all_ts: List[int],
) -> Dict[str, Dict[int, float]]:
    """
    For each key, build t -> value using last known at or before t.
    This lets series with different timestamps still combine cleanly.
    """
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
                result[k][t] = float(last_val)
    return result


def _ema_series(series: List[Tuple[int, float]], period: int) -> List[Tuple[int, float]]:
    """EMA: alpha = 2/(period+1), init with first value."""
    if period < 1 or not series:
        return []
    alpha = 2.0 / (period + 1)
    out: List[Tuple[int, float]] = []
    ema: Optional[float] = None
    for t, x in series:
        if not math.isfinite(x):
            continue
        ema = x if ema is None else (alpha * x + (1.0 - alpha) * ema)
        out.append((t, ema))
    return out


def _get_primary_series(indicator_series: Dict[str, OutputSeries], indicator_id: str) -> List[Tuple[int, float]]:
    """Extract primary series for dependency indicator, timestamps normalized to ms."""
    out = indicator_series.get(indicator_id)
    if not out:
        return []
    key = PRIMARY_SERIES.get(indicator_id)
    if not key:
        return []
    raw = out.get(key)
    if not raw:
        return []
    res: List[Tuple[int, float]] = []
    for t, v in raw:
        try:
            vv = float(v)
        except Exception:
            continue
        if math.isfinite(vv):
            res.append((_ts_ms(t), vv))
    return res


class RegimeIndex(IndicatorBase):
    id = "regime_index"
    display_name = "Regime Index"
    description = "Composite regime from other indicators: stress + downside + anti-structure (0..1)."
    required_inputs = []  # composite: no candles

    required_indicator_ids = [
        # existing
        "vol_of_vol",
        "perm_entropy",
        "realized_kurtosis",
        "amihud_illiquidity",
        "down_up_vol_asym",
        "rolling_hurst",
        "ulcer_index",
        "rolling_max_drawdown",
        # new (OHLCV-only)
        "vol_regime_ratio",
        "downside_dev",
        "real_skewness",
        "expected_shortfall",
        "returns_autocorr",
        "vol_absret_corr",
    ]

    parameters = {
        "norm_window": INDEX_WINDOW,
        # output when at least this many components present (missing filled by NEUTRAL afterwards)
        "min_components": 4,
        "fast_ema_period": 20,
        "slow_ema_period": 200,
        # block weights
        "w_stress": 0.6,
        "w_downside": 0.3,
        "w_anti_structure": 0.1,
    }

    output_series_defs = [
        {"id": "regime", "label": "Regime"},
       # {"id": "regime_fast", "label": "Regime Fast"},
       # {"id": "regime_slow", "label": "Regime Slow"},
        # helpful debug lines
        {"id": "stress", "label": "Stress Block"},
        {"id": "downside", "label": "Downside Block"},
        {"id": "structure", "label": "Structure Block"},
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
        empty = {
            "regime": [],
        #    "regime_fast": [],
        #    "regime_slow": [],
        #    "stress": [],
        #    "downside": [],
        #    "structure": [],
        }
        if not indicator_series:
            return (empty, None)

        norm_window = max(2, int(self.parameters.get("norm_window", INDEX_WINDOW)))
        min_components = int(self.parameters.get("min_components", 4))
        min_components = max(1, min(len(self.required_indicator_ids), min_components))

        fast_ema_period = max(1, min(60, int(self.parameters.get("fast_ema_period", 20))))
        slow_ema_period = max(1, min(600, int(self.parameters.get("slow_ema_period", 200))))

        w_stress = float(self.parameters.get("w_stress", 0.6))
        w_downside = float(self.parameters.get("w_downside", 0.3))
        w_anti_structure = float(self.parameters.get("w_anti_structure", 0.1))

        # --- raw dependency series ---
        vov_raw = _get_primary_series(indicator_series, "vol_of_vol")
        kurt_raw = _get_primary_series(indicator_series, "realized_kurtosis")
        amihud_raw = _get_primary_series(indicator_series, "amihud_illiquidity")
        ui_raw = _get_primary_series(indicator_series, "ulcer_index")
        asym_raw = _get_primary_series(indicator_series, "down_up_vol_asym")
        hurst_raw = _get_primary_series(indicator_series, "rolling_hurst")
        pe_raw = _get_primary_series(indicator_series, "perm_entropy")
        mdd_raw = _get_primary_series(indicator_series, "rolling_max_drawdown")

        vr_raw = _get_primary_series(indicator_series, "vol_regime_ratio")
        downside_dev_raw = _get_primary_series(indicator_series, "downside_dev")
        skew_raw = _get_primary_series(indicator_series, "real_skewness")
        es_raw = _get_primary_series(indicator_series, "expected_shortfall")
        acf_raw = _get_primary_series(indicator_series, "returns_autocorr")
        vretcorr_raw = _get_primary_series(indicator_series, "vol_absret_corr")

        # --- transforms BEFORE percentile ---
        # mdd should be treated as "pain magnitude"
        mdd_pain_raw = [(t, abs(v)) for t, v in mdd_raw if math.isfinite(v)]
        # anti-entropy: more chaos => higher risk; use (1 - pe)
        one_minus_pe_raw = [(t, 1.0 - v) for t, v in pe_raw if math.isfinite(v)]
        # negative skew is "worse"; use (-skew)
        neg_skew_raw = [(t, -v) for t, v in skew_raw if math.isfinite(v)]
        # abs autocorr as "structure strength" (predictability / memory)
        abs_acf_raw = [(t, abs(v)) for t, v in acf_raw if math.isfinite(v)]

        # determine effective normalization window from available histories
        raw_lists = [
            vov_raw, kurt_raw, amihud_raw, ui_raw, asym_raw, hurst_raw, one_minus_pe_raw, mdd_pain_raw,
            vr_raw, downside_dev_raw, neg_skew_raw, es_raw, abs_acf_raw, vretcorr_raw,
        ]
        lengths = [len(s) for s in raw_lists if s]
        if not lengths:
            return (empty, None)

        # take a conservative window so percentiles exist for most inputs
        effective_norm = min(norm_window, max(10, min(lengths) // 2))

        # --- percentiles ---
        vov_pct = _rolling_percentile(vov_raw, effective_norm)
        kurt_pct = _rolling_percentile(kurt_raw, effective_norm)
        amihud_pct = _rolling_percentile(amihud_raw, effective_norm)
        ui_pct = _rolling_percentile(ui_raw, effective_norm)
        asym_pct = _rolling_percentile(asym_raw, effective_norm)
        hurst_pct = _rolling_percentile(hurst_raw, effective_norm)
        one_minus_pe_pct = _rolling_percentile(one_minus_pe_raw, effective_norm)
        mdd_pct = _rolling_percentile(mdd_pain_raw, effective_norm)

        vr_pct = _rolling_percentile(vr_raw, effective_norm)
        downside_dev_pct = _rolling_percentile(downside_dev_raw, effective_norm)
        neg_skew_pct = _rolling_percentile(neg_skew_raw, effective_norm)
        es_pct = _rolling_percentile(es_raw, effective_norm)
        abs_acf_pct = _rolling_percentile(abs_acf_raw, effective_norm)
        vretcorr_pct = _rolling_percentile(vretcorr_raw, effective_norm)

        # union timestamps
        all_ts_set: set[int] = set()
        for lst in [
            vov_pct, kurt_pct, amihud_pct, ui_pct, asym_pct, hurst_pct, one_minus_pe_pct, mdd_pct,
            vr_pct, downside_dev_pct, neg_skew_pct, es_pct, abs_acf_pct, vretcorr_pct,
        ]:
            for t, _ in lst:
                all_ts_set.add(_ts_ms(t))
        all_ts = sorted(all_ts_set)
        if not all_ts:
            return (empty, None)

        aligned = _align_series(
            {
                "vov": vov_pct,
                "kurt": kurt_pct,
                "amihud": amihud_pct,
                "ui": ui_pct,
                "asym": asym_pct,
                "hurst": hurst_pct,
                "one_pe": one_minus_pe_pct,
                "mdd": mdd_pct,
                "vr": vr_pct,
                "down_dev": downside_dev_pct,
                "neg_skew": neg_skew_pct,
                "es": es_pct,
                "abs_acf": abs_acf_pct,
                "vretcorr": vretcorr_pct,
            },
            all_ts,
        )

        regime_raw: List[Tuple[int, float]] = []
        stress_raw: List[Tuple[int, float]] = []
        downside_raw: List[Tuple[int, float]] = []
        structure_raw: List[Tuple[int, float]] = []

        for t in all_ts:
            # pull aligned (may be missing)
            vov = aligned["vov"].get(t)
            kurt = aligned["kurt"].get(t)
            amihud = aligned["amihud"].get(t)
            ui = aligned["ui"].get(t)
            asym = aligned["asym"].get(t)
            hurst = aligned["hurst"].get(t)
            one_pe = aligned["one_pe"].get(t)
            mdd = aligned["mdd"].get(t)

            vr = aligned["vr"].get(t)
            down_dev = aligned["down_dev"].get(t)
            neg_skew = aligned["neg_skew"].get(t)
            es = aligned["es"].get(t)
            abs_acf = aligned["abs_acf"].get(t)
            vretcorr = aligned["vretcorr"].get(t)

            vals = [vov, kurt, amihud, ui, asym, hurst, one_pe, mdd, vr, down_dev, neg_skew, es, abs_acf, vretcorr]
            n_present = sum(1 for v in vals if v is not None and math.isfinite(v))
            if n_present < min_components:
                continue

            # fill missing with neutral so we can output early
            def _f(x: Optional[float]) -> float:
                return x if x is not None and math.isfinite(x) else NEUTRAL

            vov = _f(vov)
            kurt = _f(kurt)
            amihud = _f(amihud)
            ui = _f(ui)
            asym = _f(asym)
            hurst = _f(hurst)
            one_pe = _f(one_pe)
            mdd = _f(mdd)
            vr = _f(vr)
            down_dev = _f(down_dev)
            neg_skew = _f(neg_skew)
            es = _f(es)
            abs_acf = _f(abs_acf)
            vretcorr = _f(vretcorr)

            # --- blocks ---
            # stress: turbulence / tails / illiq / pain-ish proxies
            stress = (vov + kurt + amihud + ui + vr) / 5.0

            # downside: downside dominance and tail depth
            downside = (asym + mdd + down_dev + es + neg_skew) / 5.0

            # structure: predictability / confirmation / anti-chaos
            structure = (one_pe + hurst + abs_acf + vretcorr) / 4.0

            ri = (
                w_stress * stress
                + w_downside * downside
                + w_anti_structure * (1.0 - structure)
            )

            if math.isfinite(ri):
                ri = max(0.0, min(1.0, ri))
                stress = max(0.0, min(1.0, stress))
                downside = max(0.0, min(1.0, downside))
                structure = max(0.0, min(1.0, structure))
                regime_raw.append((t, ri))
                stress_raw.append((t, stress))
                downside_raw.append((t, downside))
                structure_raw.append((t, structure))

        regime_fast = _ema_series(regime_raw, fast_ema_period)
        regime_slow = _ema_series(regime_raw, slow_ema_period)

        return (
            {
                "regime": regime_raw,
            },
            None,
        )
