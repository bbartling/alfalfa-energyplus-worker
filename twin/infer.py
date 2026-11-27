"""Infer control setpoints from samples taken while equipment is running.

Supply air temperature, duct static pressure, and water temperatures use a
steady-state percentile method: the mean of the samples that sit between the
10th and 90th percentiles, so startup spikes do not set the value.

Zone heating and cooling use a deadband percentile method. The 10th and 90th
percentiles of occupied (or unoccupied) zone temperature are the two setpoints.
A second estimate, the mean of the lower quartile and the mean of the upper
quartile, checks that the ends of the distribution are real clusters. Confidence
is higher with more samples, a tight steady-state band or a plausible deadband,
and agreement between the two estimates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_SAMPLES = 8


@dataclass(frozen=True)
class Inferred:
    value: float
    confidence: float
    method: str
    modes: tuple[float, ...] | None = None


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _confidence(n: int, spread: float, agreement: bool, plausible: bool, scale: float) -> float:
    n_term = min(1.0, n / 40)
    spread_term = max(0.0, 1.0 - spread / scale)
    score = 0.45 * n_term + 0.35 * spread_term + (0.2 if agreement else 0.08)
    if not plausible:
        score *= 0.45
    return round(min(1.0, max(0.0, score)), 3)


def infer_steady(samples: list[float]) -> Inferred:
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"need at least {MIN_SAMPLES} samples")
    low = percentile(samples, 10)
    high = percentile(samples, 90)
    band = [value for value in samples if low <= value <= high] or list(samples)
    value = sum(band) / len(band)
    spread = _pstdev(band)
    median = percentile(samples, 50)
    scale = max(1.0, abs(value) * 0.1)
    agreement = abs(value - median) <= max(0.3, scale)
    plausible = spread <= scale
    return Inferred(round(value, 3), _confidence(len(samples), spread, agreement, plausible, scale), "steady-state-percentile")


MIN_MODE_HOURS = 8
CONFIDENCE_FLOOR = 0.6


def infer_quantile(summary: dict, *, upper: bool) -> Inferred:
    """Heating uses the upper quantile of heating-active hours. Cooling uses the lower quantile."""
    if summary["hours"] < MIN_MODE_HOURS and summary["n"] < MIN_SAMPLES:
        raise ValueError("mode was not active long enough")
    value = summary["p90"] if upper else summary["p10"]
    spread = abs(summary["p95"] - summary["p05"])
    plausible = spread <= 3.0
    agreement = abs(summary["p50"] - value) <= 1.5
    return Inferred(
        round(float(value), 3),
        _confidence(int(summary["n"]), spread, agreement, plausible, 2.0),
        "mode-quantile",
    )


def infer_reset(modes: list[dict]) -> Inferred:
    centers = [float(mode["p50"]) for mode in modes]
    spread = max(centers) - min(centers) if centers else 0.0
    confidence = _confidence(sum(int(mode["n"]) for mode in modes), spread, True, spread >= 1.0, scale=4.0)
    ordered = tuple(round(value, 3) for value in sorted(centers))
    return Inferred(ordered[0], confidence, "reset", ordered)


def infer_zone(samples: list[float], *, unoccupied: bool = False) -> tuple[Inferred, Inferred]:
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"need at least {MIN_SAMPLES} samples")
    heating = percentile(samples, 10)
    cooling = percentile(samples, 90)
    lower_cut = percentile(samples, 25)
    upper_cut = percentile(samples, 75)
    lower = [value for value in samples if value <= lower_cut]
    upper = [value for value in samples if value >= upper_cut]
    lower_mean = sum(lower) / len(lower)
    upper_mean = sum(upper) / len(upper)
    deadband = cooling - heating
    plausible = (1.5 if unoccupied else 0.8) <= deadband <= (20 if unoccupied else 8)
    agreement = abs(heating - lower_mean) <= 0.75 and abs(cooling - upper_mean) <= 0.75
    spread = _pstdev(samples)
    confidence = _confidence(len(samples), spread, agreement, plausible, scale=4.0)
    method = "deadband-percentile"
    return (
        Inferred(round(heating, 3), confidence, method),
        Inferred(round(cooling, 3), confidence, method),
    )


def _pstdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
