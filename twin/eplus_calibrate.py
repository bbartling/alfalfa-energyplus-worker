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
    "heating_cop": (2.5, 3.8),
}
SWEEP_KEYS = tuple(key for key in COARSE if key != "heating_cop")


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
    masks = _hour_masks(payloads)
    if masks is not None:
        case["weekday_hours"] = masks["weekday"]
        case["weekend_hours"] = masks["weekend"]
        case["occupied_start"], case["occupied_end"] = _span_from_mask(masks["weekday"])
    elif window is not None:
        case["occupied_start"], case["occupied_end"] = window
    return case


def sweep_keys(base: dict) -> tuple[str, ...]:
    if base.get("heating_fuel") == "heat_pump":
        return (*SWEEP_KEYS, "heating_cop")
    return SWEEP_KEYS


def coarse_cases(base: dict) -> list[dict]:
    keys = sweep_keys(base)
    cases = []
    for values in product(*(COARSE[key] for key in keys)):
        updated = dict(base)
        updated.update(dict(zip(keys, values, strict=True)))
        cases.append(updated)
    return cases


def refine_cases(best: dict, seen: set[tuple]) -> list[dict]:
    """One half-step either side of the best coarse point, per parameter."""
    extra = []
    for key in sweep_keys(best):
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
    ranked: list[tuple[dict, float, dict]] = []
    seen: set[tuple] = set()

    def evaluate(case: dict) -> None:
        identity = _identity(case)
        if identity in seen:
            return
        seen.add(identity)
        raw = run_fn(case, span)
        ranked.append((case, _score(raw, months, scale), raw))

    for case in coarse_cases(base):
        evaluate(case)
    ranked.sort(key=lambda item: item[1])
    for case in refine_cases(ranked[0][0], seen):
        evaluate(case)
    ranked.sort(key=lambda item: item[1])
    best, _score_value, raw = ranked[0]
    tuned = len(sweep_keys(best))
    claim = "guideline14" if len(months) >= 12 else "insufficient-data"
    metrics = _metrics(raw, months, scale, "all", claim=claim, tuned=tuned)
    metrics.extend(_loocv(raw, months, scale, tuned))
    promoted = claim == "guideline14" and _passes(metrics, "all")
    passing = []
    for candidate, _candidate_score, candidate_raw in ranked:
        rows = _metrics(candidate_raw, months, scale, "all", claim=claim, tuned=tuned)
        if claim == "guideline14" and _passes(rows, "all"):
            passing.append(candidate)
    return {
        "decision": "promoted" if promoted else ("insufficient-data" if claim == "insufficient-data" else "rejected"),
        "parameters": best,
        "ensemble": passing or [best],
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
            "decision": "promoted" if promoted else ("insufficient-data" if claim == "insufficient-data" else "rejected"),
            "n_tuned_parameters": tuned,
            "p": 1,
            "claim": claim,
            "idf_sha256": raw.get("idf_sha256"),
            "epw_sha256": raw.get("epw_sha256"),
            "energyplus_version": raw.get("energyplus_version"),
            "span": span,
        },
    }


def apply_measures(case: dict, measures: list[dict]) -> dict:
    """Replay ROI measures on the calibrated EnergyPlus case."""
    updated = dict(case)
    for measure in measures:
        if measure["name"] == "raise_cooling_setpoint":
            updated["cooling_setpoint_c"] = float(updated["cooling_setpoint_c"]) + float(measure["delta_c"])
        elif measure["name"] == "lower_heating_setpoint":
            updated["heating_setpoint_c"] = float(updated["heating_setpoint_c"]) - float(measure["delta_c"])
        elif measure["name"] == "trim_run_hours":
            if updated.get("weekday_hours"):
                updated["weekday_hours"] = _trim_mask(updated["weekday_hours"], float(measure["fraction"]))
                updated["occupied_start"], updated["occupied_end"] = _span_from_mask(updated["weekday_hours"])
            else:
                updated["occupied_start"], updated["occupied_end"] = _trim_window(
                    updated["occupied_start"], updated["occupied_end"], float(measure["fraction"])
                )
    return updated


def price_energyplus(case: dict, measures: list[dict], costs: dict, area: float, run_fn, ensemble: list[dict] | None = None) -> dict:
    """Price a what-if from each passing member's own baseline and altered run."""
    scale = area / MODEL_AREA_M2
    members = []
    seen = set()
    for member in [case, *(ensemble or [])]:
        identity = _identity(member)
        if identity in seen:
            continue
        seen.add(identity)
        members.append(member)
    dollars = []
    headline = None
    runs = 0
    for member in members:
        baseline = run_fn(member, "year")
        altered = run_fn(apply_measures(member, measures), "year")
        runs += 2
        save_kwh, save_therms = _annual_delta(baseline, altered, scale)
        usd = _dollars(save_kwh, save_therms, costs)
        dollars.append(usd)
        if headline is None:
            headline = (save_kwh, save_therms, usd)
    save_kwh, save_therms, usd = headline
    payback = None if usd <= 0 else costs["implementation_usd"] / usd
    return {
        "annual_kwh_savings": save_kwh,
        "annual_therm_savings": save_therms,
        "annual_cost_savings_usd": usd,
        "simple_payback_years": payback,
        "npv_usd": _npv(costs["implementation_usd"], usd, costs["discount_rate"], costs["horizon_years"]),
        "cost_savings_band_usd": [_percentile(dollars, 0.1), _percentile(dollars, 0.9)],
        "engine": "energyplus",
        "label": "EnergyPlus",
        "runs": runs,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _annual_delta(baseline: dict, altered: dict, scale: float) -> tuple[float, float]:
    return (
        _annual(baseline, "electric", scale) - _annual(altered, "electric", scale),
        _annual(baseline, "gas", scale) - _annual(altered, "gas", scale),
    )


def _annual(raw: dict, key: str, scale: float) -> float:
    return sum((raw.get(key) or {}).values()) * scale


def _dollars(kwh: float, therms: float, costs: dict) -> float:
    return kwh * costs["electricity_usd_per_kwh"] + therms * costs["gas_usd_per_therm"]


def _npv(initial: float, annual: float, rate: float, years: int) -> float:
    total = -initial
    for year in range(1, years + 1):
        total += annual / ((1 + rate) ** year)
    return total


def _trim_window(start: str, end: str, fraction: float) -> tuple[str, str]:
    start_m = _minutes(start)
    end_m = _minutes(end)
    if end_m <= start_m:
        return start, end
    kept = (end_m - start_m) * (1 - fraction)
    finish = start_m + kept
    return start, f"{int(finish // 60):02d}:{int(finish % 60):02d}"


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _score(raw: dict, months: list[dict], scale: float) -> float:
    total = 0.0
    for month in months:
        number = _month_number(month["start"])
        total += _relative(month["electric_kwh"], _lookup(raw["electric"], number) * scale)
        if month.get("gas_therms") is not None and raw.get("gas"):
            total += _relative(month["gas_therms"], _lookup(raw["gas"], number) * scale)
    return total


def _loocv(raw: dict, months: list[dict], scale: float, tuned: int) -> list[dict]:
    """Leave each month out of the score. Parameters are not refit. Diagnostic only."""
    if len(months) < 4:
        return []
    electric = []
    for index in range(len(months)):
        sample = months[:index] + months[index + 1 :]
        electric.append(_metrics(raw, sample, scale, "loocv", claim="diagnostic", tuned=tuned)[0]["cv_rmse_pct"])
    return [
        {
            "split": "loocv",
            "fuel": "electricity",
            "n": len(months),
            "p": 1,
            "n_tuned_parameters": tuned,
            "cv_rmse_pct": max(electric),
            "nmbe_pct": 0.0,
            "granularity": "monthly",
            "limits": None,
            "pass": None,
            "claim": "diagnostic",
        }
    ]


def _metrics(raw: dict, months: list[dict], scale: float, split: str, claim: str | None = None, tuned: int = 1) -> list[dict]:
    electric_m, electric_s, gas_m, gas_s = [], [], [], []
    for month in months:
        number = _month_number(month["start"])
        electric_m.append(month["electric_kwh"])
        electric_s.append(_lookup(raw["electric"], number) * scale)
        if month.get("gas_therms") is not None and number in raw.get("gas", {}):
            gas_m.append(month["gas_therms"])
            gas_s.append(raw["gas"][number] * scale)
    rows = [_row(split, "electricity", electric_m, electric_s, claim, tuned)]
    if len(gas_m) >= 2:
        rows.append(_row(split, "natural_gas", gas_m, gas_s, claim, tuned))
    return rows


def _row(split: str, fuel: str, measured: list[float], simulated: list[float], claim: str | None, tuned: int) -> dict:
    stats = assess(measured, simulated, "monthly")
    stats["n_tuned_parameters"] = tuned
    if claim and claim != "guideline14":
        stats["claim"] = claim
        stats["pass"] = None
        stats["limits"] = None
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


def prototype_match(site) -> str | None:
    """422 detail when this site cannot use the checked-in small-office RTU."""
    stories = site.stories or 1
    if site.building_type != "small-office" or site.system_type != "psz-ac":
        return "EnergyPlus v1 is a small-office packaged RTU (psz-ac)"
    if not 250 <= site.floor_area_m2 <= 2500 or not 1 <= stories <= 2:
        return "EnergyPlus v1 covers small offices of 250 to 2,500 m² and one or two storeys"
    if site.heating_fuel not in {"gas", "electric", "heat_pump"}:
        return "heating_fuel must be gas, electric, or heat_pump"
    return None


def _identity(case: dict) -> tuple:
    return tuple(round(float(case[key]), 6) for key in sweep_keys(case))


def _setpoints(payloads: list[dict], kind: str, period: str) -> list[float]:
    found = []
    for payload in payloads:
        points = payload.get("setpoints") or []
        actual = [
            item
            for item in points
            if item.get("kind") == kind and item.get("source") == "actual" and item.get("period") in {period, "always"}
        ]
        if actual:
            found.extend(float(item["value"]) for item in actual)
            continue
        for item in points:
            if item.get("kind") != kind or item.get("period") != period:
                continue
            if item.get("source") == "inferred" and (item.get("confidence") or 0) < 0.6:
                continue
            found.append(float(item["value"]))
    return found


def _hour_masks(payloads: list[dict]) -> dict[str, list[bool]] | None:
    profiles = []
    for payload in payloads:
        for item in payload.get("run_hours") or []:
            profile = item.get("hour_of_week")
            if profile and len(profile) == 168:
                profiles.append([float(value) for value in profile])
    if not profiles:
        return None
    average = [sum(profile[index] for profile in profiles) / len(profiles) for index in range(168)]

    def mask(days: range) -> list[bool]:
        hours = []
        for hour in range(24):
            values = [average[day * 24 + hour] for day in days]
            hours.append(sum(values) / len(values) >= 0.5)
        return hours

    return {"weekday": mask(range(5)), "weekend": mask(range(5, 7))}


def _span_from_mask(mask: list[bool]) -> tuple[str, str]:
    if not any(mask):
        return "00:00", "00:00"
    first = next(hour for hour, on in enumerate(mask) if on)
    last = max(hour for hour, on in enumerate(mask) if on)
    return f"{first:02d}:00", f"{last + 1:02d}:00"


def _trim_mask(mask: list[bool], fraction: float) -> list[bool]:
    occupied = [hour for hour, on in enumerate(mask) if on]
    keep = max(0, int(round(len(occupied) * (1 - fraction))))
    drop = set(occupied[keep:])
    return [on and hour not in drop for hour, on in enumerate(mask)]


def _window(payloads: list[dict]) -> tuple[str, str] | None:
    for payload in payloads:
        for schedule in payload.get("schedules") or []:
            for window in schedule.get("windows") or []:
                if window.get("days") in {"weekday", "all"}:
                    return window["start"], window["end"]
    return None
