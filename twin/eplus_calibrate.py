"""Coarse-grid then half-step refinement on the DOE SmallOffice model.

Each point is one EnergyPlus run. The quick-estimate model is a separate path.
Monthly Electricity:Facility and NaturalGas:Facility from the SQL output are
scaled by site area / prototype area and scored with Guideline 14.
"""

from __future__ import annotations

from itertools import product

from twin.guideline14 import assess
from twin.idfedit import MODEL_AREA_M2, MODEL_NAME, REFERENCE

COARSE = {
    "lighting_w_m2": (8.0, 12.0),
    "plug_w_m2": (6.0, 10.0),
    "fan_efficiency": (0.45, 0.65),
    "cooling_cop": (3.0, 4.2),
    "infiltration_multiplier": (0.7, 1.4),
    "setpoint_offset_c": (-1.0, 1.0),
}
SWEEP_KEYS = tuple(COARSE)


def base_case(**overrides) -> dict:
    case = {
        "lighting_w_m2": REFERENCE["lighting_w_m2"],
        "plug_w_m2": REFERENCE["plug_w_m2"],
        "fan_efficiency": REFERENCE["fan_efficiency"],
        "cooling_cop": REFERENCE["cooling_cop"],
        "infiltration_multiplier": REFERENCE["infiltration_multiplier"],
        "setpoint_offset_c": 0.0,
        "heating_setpoint_c": 21.0,
        "cooling_setpoint_c": 24.0,
        "unoccupied_heating_c": 15.6,
        "unoccupied_cooling_c": 29.4,
        "occupied_start": "08:00",
        "occupied_end": "18:00",
    }
    case.update(overrides)
    return case


def conditions_from_payloads(payloads: list[dict]) -> dict:
    """Occupied window and setpoints taken from the stored summaries."""
    case = base_case()
    heating = _setpoints(payloads, "zone_heating", "occupied")
    cooling = _setpoints(payloads, "zone_cooling", "occupied")
    heating_off = _setpoints(payloads, "zone_heating", "unoccupied")
    cooling_off = _setpoints(payloads, "zone_cooling", "unoccupied")
    window = _window(payloads)
    if heating:
        case["heating_setpoint_c"] = sum(heating) / len(heating)
    if cooling:
        case["cooling_setpoint_c"] = sum(cooling) / len(cooling)
    if heating_off:
        case["unoccupied_heating_c"] = sum(heating_off) / len(heating_off)
    elif heating:
        case["unoccupied_heating_c"] = case["heating_setpoint_c"] - 3
    if cooling_off:
        case["unoccupied_cooling_c"] = sum(cooling_off) / len(cooling_off)
    elif cooling:
        case["unoccupied_cooling_c"] = case["cooling_setpoint_c"] + 3
    if window is not None:
        case["occupied_start"], case["occupied_end"] = window
    return case


def coarse_cases(base: dict) -> list[dict]:
    keys = SWEEP_KEYS
    cases = []
    for values in product(*(COARSE[key] for key in keys)):
        updated = dict(base)
        updated.update(dict(zip(keys, values, strict=True)))
        cases.append(updated)
    return cases


def refine_cases(best: dict, seen: set[tuple]) -> list[dict]:
    """One half-step either side of the best coarse point, per parameter."""
    extra = []
    for key in SWEEP_KEYS:
        step = _half_step(COARSE[key])
        if step == 0:
            continue
        for direction in (-1, 1):
            updated = dict(best)
            updated[key] = round(float(best[key]) + direction * step, 6)
            if _identity(updated) in seen:
                continue
            extra.append(updated)
    return extra


def fit(base: dict, months: list[dict], area: float, run_fn, span: str = "year") -> dict:
    """Sweep, score train months, and build Guideline 14 metrics.

    `run_fn(case, span)` returns `{"electric": {month: kWh}, "gas": {month: therm}}`
    for the prototype, before area scaling.
    """
    if len(months) < 4:
        raise ValueError("need at least four usable months to calibrate")
    scale = area / MODEL_AREA_M2
    train, holdout = months[:-2], months[-2:]
    ranked: list[tuple[dict, float, dict]] = []
    seen: set[tuple] = set()

    def evaluate(case: dict) -> None:
        identity = _identity(case)
        if identity in seen:
            return
        seen.add(identity)
        raw = run_fn(case, span)
        ranked.append((case, _score(raw, train, scale), raw))

    for case in coarse_cases(base):
        evaluate(case)
    ranked.sort(key=lambda item: item[1])
    for case in refine_cases(ranked[0][0], seen):
        evaluate(case)
    ranked.sort(key=lambda item: item[1])
    best, _score_value, raw = ranked[0]
    metrics = _metrics(raw, train, scale, "train") + _metrics(raw, holdout, scale, "holdout")
    promoted = _passes(metrics, "train") and _passes(metrics, "holdout")
    return {
        "decision": "promoted" if promoted else "rejected",
        "parameters": best,
        "ensemble": [item[0] for item in ranked[:5]],
        "metrics": metrics,
        "runs": len(ranked),
        "engine": {
            "name": "energyplus",
            "label": "EnergyPlus",
            "openstudio": "3.9.0",
            "energyplus": "24.2.0",
            "model": MODEL_NAME,
            "prototype_floor_area_m2": MODEL_AREA_M2,
            "area_scale": scale,
            "decision": "promoted" if promoted else "rejected",
            "span": span,
        },
    }


def _score(raw: dict, months: list[dict], scale: float) -> float:
    total = 0.0
    for month in months:
        number = _month_number(month["start"])
        total += _relative(month["electric_kwh"], _lookup(raw["electric"], number) * scale)
        if month.get("gas_therms") is not None and raw.get("gas"):
            total += _relative(month["gas_therms"], _lookup(raw["gas"], number) * scale)
    return total


def _metrics(raw: dict, months: list[dict], scale: float, split: str) -> list[dict]:
    electric_m, electric_s, gas_m, gas_s = [], [], [], []
    for month in months:
        number = _month_number(month["start"])
        electric_m.append(month["electric_kwh"])
        electric_s.append(_lookup(raw["electric"], number) * scale)
        if month.get("gas_therms") is not None and number in raw.get("gas", {}):
            gas_m.append(month["gas_therms"])
            gas_s.append(raw["gas"][number] * scale)
    rows = [_row(split, "electricity", electric_m, electric_s)]
    if len(gas_m) >= 2:
        rows.append(_row(split, "natural_gas", gas_m, gas_s))
    return rows


def _row(split: str, fuel: str, measured: list[float], simulated: list[float]) -> dict:
    stats = assess(measured, simulated, "monthly")
    return {"split": split, "fuel": fuel, **stats}


def _passes(metrics: list[dict], split: str) -> bool:
    rows = [item for item in metrics if item["split"] == split and item["claim"] == "guideline14"]
    return bool(rows) and all(item["pass"] for item in rows)


def _lookup(series: dict, month: int) -> float:
    if month not in series:
        raise ValueError(f"EnergyPlus produced no energy for month {month}")
    return series[month]


def _relative(actual: float, predicted: float) -> float:
    scale = max(abs(actual), 1.0)
    return ((actual - predicted) / scale) ** 2


def _month_number(start: str) -> int:
    return int(str(start)[5:7])


def _half_step(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    return abs(values[1] - values[0]) / 2


def _identity(case: dict) -> tuple:
    return tuple(round(float(case[key]), 6) for key in SWEEP_KEYS)


def _setpoints(payloads: list[dict], kind: str, period: str) -> list[float]:
    found = []
    for payload in payloads:
        for item in payload.get("setpoints") or []:
            if item.get("kind") == kind and item.get("period") == period:
                found.append(float(item["value"]))
    return found


def _window(payloads: list[dict]) -> tuple[str, str] | None:
    for payload in payloads:
        for schedule in payload.get("schedules") or []:
            for window in schedule.get("windows") or []:
                if window.get("days") in {"weekday", "all"}:
                    return window["start"], window["end"]
    return None
