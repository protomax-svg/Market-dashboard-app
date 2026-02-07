"""Liquidation pressure: from liquidations_1m — total, long/short, imbalance, z-score."""
from typing import Any, Dict, List, Optional, Tuple

from app.indicators.base import IndicatorBase, OutputSeries


def _z_scores(series: List[float]) -> List[float]:
    if not series:
        return []
    n = len(series)
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    std = var ** 0.5 if var > 0 else 1.0
    return [(x - mean) / std for x in series]


class LiquidationPressure(IndicatorBase):
    id = "liquidation_pressure"
    display_name = "Liquidation Pressure"
    description = "Total notional, long/short, imbalance, z-score from liquidation feed"
    required_inputs = [{"name": "candles", "timeframe": "1m"}, {"name": "liquidations"}]
    parameters = {"z_window": 60}
    output_series_defs = [
        {"id": "total_notional", "label": "Total Notional"},
        {"id": "imbalance", "label": "Imbalance"},
        {"id": "z_score", "label": "Total Z-Score"},
    ]

    def compute(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        liquidations: Optional[List[Dict[str, Any]]] = None,
        incremental: bool = False,
        last_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[OutputSeries, Optional[Dict[str, Any]]]:
        if not liquidations:
            return ({}, None)
        z_window = int(self.parameters.get("z_window", 60))
        times = [x["open_time"] for x in liquidations]
        totals = [x.get("total_notional") or 0.0 for x in liquidations]
        imbs = [x.get("imbalance") or 0.0 for x in liquidations]
        if len(totals) < z_window:
            z_scores = [0.0] * len(totals)
        else:
            z_scores = []
            for i in range(len(totals)):
                seg = totals[max(0, i - z_window + 1) : i + 1]
                z_scores.append(_z_scores(seg)[-1])
        out_total = [(t, v) for t, v in zip(times, totals)]
        out_imb = [(t, v) for t, v in zip(times, imbs)]
        out_z = [(t, z) for t, z in zip(times, z_scores)]
        return (
            {"total_notional": out_total, "imbalance": out_imb, "z_score": out_z},
            None,
        )
