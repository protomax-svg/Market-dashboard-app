"""
Balanced Regime Index: composite market-health indicator built from other indicators.

Design goal:
- 0.0 => healthy / constructive / cleaner market
- 1.0 => unhealthy / stressed / poor-quality market

Compared with Regime Index, this version still tracks stress and downside,
but also rewards clean movement quality instead of focusing purely on damage.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries

INDEX_WINDOW = 500_000
NEUTRAL = 0.5

PRIMARY_SERIES: Dict[str, str] = {
    "vol_of_vol": "vov",
    "perm_entropy": "pe",
    "realized_kurtosis": "kurt",
    "amihud_illiquidity": "amihud",
    "down_up_vol_asym": "asym",
    "rolling_hurst": "hurst",
    "ulcer_index": "ui",
    "rolling_max_drawdown": "mdd",
    "vol_regime_ratio": "ratio",
    "downside_dev": "downside",
    "real_skewness": "skew",
    "expected_shortfall": "es",
    "returns_autocorr": "acf",
    "vol_absret_corr": "corr",
    "efficiency_ratio": "er",
    "choppiness_index": "chop",
}


def _ts_ms(timestamp: Any) -> int:
    value = int(timestamp) if timestamp is not None else 0
    return value * 1000 if value < 1_000_000_000_000 else value


def _rolling_percentile(series: List[Tuple[int, float]], norm_window: int) -> List[Tuple[int, float]]:
    if norm_window < 2 or len(series) < norm_window:
        return []

    out: List[Tuple[int, float]] = []
    window_vals: deque[float] = deque(maxlen=norm_window)
    sorted_vals: List[float] = []

    for timestamp, value in series:
        if not math.isfinite(value):
            continue

        if len(window_vals) == norm_window:
            old = window_vals.popleft()
            idx = bisect.bisect_left(sorted_vals, old)
            if idx < len(sorted_vals) and sorted_vals[idx] == old:
                del sorted_vals[idx]
            elif idx > 0 and sorted_vals[idx - 1] == old:
                del sorted_vals[idx - 1]

        window_vals.append(value)
        bisect.insort(sorted_vals, value)

        if len(sorted_vals) < norm_window:
            continue

        rank = bisect.bisect_right(sorted_vals, value) - 1
        pct = rank / (len(sorted_vals) - 1) if len(sorted_vals) > 1 else NEUTRAL
        out.append((timestamp, max(0.0, min(1.0, pct))))

    return out


def _align_series(
    series_by_key: Dict[str, List[Tuple[int, float]]],
    all_ts: List[int],
) -> Dict[str, Dict[int, float]]:
    result: Dict[str, Dict[int, float]] = {key: {} for key in series_by_key}
    for key, raw_series in series_by_key.items():
        if not raw_series:
            continue
        ordered = sorted(raw_series, key=lambda item: item[0])
        idx = 0
        last_value: Optional[float] = None
        for timestamp in all_ts:
            while idx < len(ordered) and ordered[idx][0] <= timestamp:
                last_value = ordered[idx][1]
                idx += 1
            if last_value is not None and math.isfinite(last_value):
                result[key][timestamp] = float(last_value)
    return result


def _ema_series(series: List[Tuple[int, float]], period: int) -> List[Tuple[int, float]]:
    if period < 1 or not series:
        return []
    alpha = 2.0 / (period + 1)
    out: List[Tuple[int, float]] = []
    ema: Optional[float] = None
    for timestamp, value in series:
        if not math.isfinite(value):
            continue
        ema = value if ema is None else alpha * value + (1.0 - alpha) * ema
        out.append((timestamp, ema))
    return out


def _get_primary_series(indicator_series: Dict[str, OutputSeries], indicator_id: str) -> List[Tuple[int, float]]:
    output = indicator_series.get(indicator_id)
    if not output:
        return []
    key = PRIMARY_SERIES.get(indicator_id)
    if not key:
        return []
    raw = output.get(key)
    if not raw:
        return []
    cleaned: List[Tuple[int, float]] = []
    for timestamp, value in raw:
        try:
            numeric_value = float(value)
        except Exception:
            continue
        if math.isfinite(numeric_value):
            cleaned.append((_ts_ms(timestamp), numeric_value))
    return cleaned


class BalancedRegimeIndex(IndicatorBase):
    id = "balanced_regime_index"
    display_name = "Balanced Regime Index"
    description = "Balanced market-health composite: stress, downside, structure, and movement quality."
    required_inputs = []
    required_indicator_ids = [
        "vol_of_vol",
        "perm_entropy",
        "realized_kurtosis",
        "amihud_illiquidity",
        "down_up_vol_asym",
        "rolling_hurst",
        "ulcer_index",
        "rolling_max_drawdown",
        "vol_regime_ratio",
        "downside_dev",
        "real_skewness",
        "expected_shortfall",
        "returns_autocorr",
        "vol_absret_corr",
        "efficiency_ratio",
        "choppiness_index",
    ]
    parameters = {
        "norm_window": INDEX_WINDOW,
        "min_components": 4,
        "fast_ema_period": 20,
        "slow_ema_period": 200,
        "w_stress": 0.35,
        "w_downside": 0.25,
        "w_anti_quality": 0.25,
        "w_anti_structure": 0.15,
    }
    output_series_defs = [
        {"id": "balanced_regime", "label": "Balanced Regime"},
        {"id": "balanced_regime_fast", "label": "Balanced Regime Fast"},
        {"id": "balanced_regime_slow", "label": "Balanced Regime Slow"},
        {"id": "stress", "label": "Stress Block"},
        {"id": "downside", "label": "Downside Block"},
        {"id": "structure", "label": "Structure Block"},
        {"id": "quality", "label": "Quality Block"},
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
            "balanced_regime": [],
            "balanced_regime_fast": [],
            "balanced_regime_slow": [],
            "stress": [],
            "downside": [],
            "structure": [],
            "quality": [],
        }
        if not indicator_series:
            return (empty, None)

        norm_window = max(2, int(self.parameters.get("norm_window", INDEX_WINDOW)))
        min_components = int(self.parameters.get("min_components", 4))
        min_components = max(1, min(len(self.required_indicator_ids), min_components))

        fast_ema_period = max(1, min(60, int(self.parameters.get("fast_ema_period", 20))))
        slow_ema_period = max(1, min(600, int(self.parameters.get("slow_ema_period", 200))))

        w_stress = float(self.parameters.get("w_stress", 0.35))
        w_downside = float(self.parameters.get("w_downside", 0.25))
        w_anti_quality = float(self.parameters.get("w_anti_quality", 0.25))
        w_anti_structure = float(self.parameters.get("w_anti_structure", 0.15))

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
        er_raw = _get_primary_series(indicator_series, "efficiency_ratio")
        chop_raw = _get_primary_series(indicator_series, "choppiness_index")

        mdd_pain_raw = [(timestamp, abs(value)) for timestamp, value in mdd_raw if math.isfinite(value)]
        one_minus_pe_raw = [(timestamp, 1.0 - value) for timestamp, value in pe_raw if math.isfinite(value)]
        neg_skew_raw = [(timestamp, -value) for timestamp, value in skew_raw if math.isfinite(value)]
        abs_acf_raw = [(timestamp, abs(value)) for timestamp, value in acf_raw if math.isfinite(value)]

        raw_lists = [
            vov_raw,
            kurt_raw,
            amihud_raw,
            ui_raw,
            asym_raw,
            hurst_raw,
            one_minus_pe_raw,
            mdd_pain_raw,
            vr_raw,
            downside_dev_raw,
            neg_skew_raw,
            es_raw,
            abs_acf_raw,
            vretcorr_raw,
            er_raw,
            chop_raw,
        ]
        lengths = [len(series) for series in raw_lists if series]
        if not lengths:
            return (empty, None)

        effective_norm = min(norm_window, max(10, min(lengths) // 2))

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
        er_pct = _rolling_percentile(er_raw, effective_norm)
        chop_pct = _rolling_percentile(chop_raw, effective_norm)

        all_ts_set: set[int] = set()
        for series in [
            vov_pct,
            kurt_pct,
            amihud_pct,
            ui_pct,
            asym_pct,
            hurst_pct,
            one_minus_pe_pct,
            mdd_pct,
            vr_pct,
            downside_dev_pct,
            neg_skew_pct,
            es_pct,
            abs_acf_pct,
            vretcorr_pct,
            er_pct,
            chop_pct,
        ]:
            for timestamp, _ in series:
                all_ts_set.add(_ts_ms(timestamp))
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
                "er": er_pct,
                "chop": chop_pct,
            },
            all_ts,
        )

        balanced_regime_raw: List[Tuple[int, float]] = []
        stress_raw: List[Tuple[int, float]] = []
        downside_raw: List[Tuple[int, float]] = []
        structure_raw: List[Tuple[int, float]] = []
        quality_raw: List[Tuple[int, float]] = []

        def _filled(value: Optional[float]) -> float:
            return value if value is not None and math.isfinite(value) else NEUTRAL

        for timestamp in all_ts:
            vov = aligned["vov"].get(timestamp)
            kurt = aligned["kurt"].get(timestamp)
            amihud = aligned["amihud"].get(timestamp)
            ui = aligned["ui"].get(timestamp)
            asym = aligned["asym"].get(timestamp)
            hurst = aligned["hurst"].get(timestamp)
            one_pe = aligned["one_pe"].get(timestamp)
            mdd = aligned["mdd"].get(timestamp)
            vr = aligned["vr"].get(timestamp)
            down_dev = aligned["down_dev"].get(timestamp)
            neg_skew = aligned["neg_skew"].get(timestamp)
            es = aligned["es"].get(timestamp)
            abs_acf = aligned["abs_acf"].get(timestamp)
            vretcorr = aligned["vretcorr"].get(timestamp)
            er = aligned["er"].get(timestamp)
            chop = aligned["chop"].get(timestamp)

            values = [
                vov,
                kurt,
                amihud,
                ui,
                asym,
                hurst,
                one_pe,
                mdd,
                vr,
                down_dev,
                neg_skew,
                es,
                abs_acf,
                vretcorr,
                er,
                chop,
            ]
            n_present = sum(1 for value in values if value is not None and math.isfinite(value))
            if n_present < min_components:
                continue

            vov = _filled(vov)
            kurt = _filled(kurt)
            amihud = _filled(amihud)
            ui = _filled(ui)
            asym = _filled(asym)
            hurst = _filled(hurst)
            one_pe = _filled(one_pe)
            mdd = _filled(mdd)
            vr = _filled(vr)
            down_dev = _filled(down_dev)
            neg_skew = _filled(neg_skew)
            es = _filled(es)
            abs_acf = _filled(abs_acf)
            vretcorr = _filled(vretcorr)
            er = _filled(er)
            chop_quality = 1.0 - _filled(chop)

            stress = (vov + kurt + amihud + ui + vr) / 5.0
            downside = (asym + mdd + down_dev + es + neg_skew) / 5.0
            structure = (one_pe + hurst + abs_acf + vretcorr) / 4.0
            quality = (er + chop_quality + structure + (1.0 - stress)) / 4.0

            balanced = (
                w_stress * stress
                + w_downside * downside
                + w_anti_quality * (1.0 - quality)
                + w_anti_structure * (1.0 - structure)
            )

            if not math.isfinite(balanced):
                continue

            balanced = max(0.0, min(1.0, balanced))
            stress = max(0.0, min(1.0, stress))
            downside = max(0.0, min(1.0, downside))
            structure = max(0.0, min(1.0, structure))
            quality = max(0.0, min(1.0, quality))

            balanced_regime_raw.append((timestamp, balanced))
            stress_raw.append((timestamp, stress))
            downside_raw.append((timestamp, downside))
            structure_raw.append((timestamp, structure))
            quality_raw.append((timestamp, quality))

        balanced_fast = _ema_series(balanced_regime_raw, fast_ema_period)
        balanced_slow = _ema_series(balanced_regime_raw, slow_ema_period)

        return (
            {
                "balanced_regime": balanced_regime_raw,
                "balanced_regime_fast": balanced_fast,
                "balanced_regime_slow": balanced_slow,
                "stress": stress_raw,
                "downside": downside_raw,
                "structure": structure_raw,
                "quality": quality_raw,
            },
            None,
        )
