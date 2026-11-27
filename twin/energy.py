"""Summary energy model used to calibrate schedules and setpoints.

Electricity is lighting (from occupied hours), fans (from run hours), and
cooling (from CDD, the occupied cooling setpoint, outdoor-air fraction, and COP).
Gas is infiltration heating from HDD and the occupied heating setpoint.

This is the model the quickstart calibrates. Guideline 14 itself is computed by
`guideline14` from any paired meter series, including EnergyPlus meter output.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    lighting_w_m2: float
    cooling_cop: float
    infiltration_ach: float

    def as_dict(self) -> dict:
        return {
            "lighting_w_m2": self.lighting_w_m2,
            "cooling_cop": self.cooling_cop,
            "infiltration_ach": self.infiltration_ach,
        }


def electric_kwh(
    params: Params,
    *,
    area: float,
    days: float,
    occupied_hours: float,
    run_hours: float,
    cooling_sp: float,
    oa_fraction: float,
    cdd: float,
) -> float:
    lights = params.lighting_w_m2 * area * occupied_hours / 1000
    fans = 2.0 * area * run_hours / 1000
    drive = max(0.0, 25.0 - cooling_sp)
    cooling = cdd * area * drive * (1 + oa_fraction) / params.cooling_cop / 50
    return lights + fans + cooling


def gas_therms(
    params: Params,
    *,
    area: float,
    heating_sp: float,
    oa_fraction: float,
    hdd: float,
) -> float:
    drive = max(0.0, heating_sp - 16.0)
    return params.infiltration_ach * hdd * area * drive * (1 + oa_fraction) / 8000


LIGHTING_GRID = (6.0, 8.0, 10.0, 12.0, 14.0)
COP_GRID = (2.5, 3.0, 3.5, 4.0, 4.5)
ACH_GRID = (0.2, 0.4, 0.6, 0.8, 1.0)


def search(months: list[dict], area: float, limit: int | None = None) -> list[tuple[Params, float]]:
    """Return parameter sets from best to worst for the training months."""
    ranked: list[tuple[Params, float]] = []
    for lighting in LIGHTING_GRID:
        for cop in COP_GRID:
            for ach in ACH_GRID:
                params = Params(lighting, cop, ach)
                ranked.append((params, _score(params, months, area)))
    ranked.sort(key=lambda item: item[1])
    if limit is not None:
        return ranked[:limit]
    return ranked


def _score(params: Params, months: list[dict], area: float) -> float:
    if not months:
        return 1e9
    electric_error = 0.0
    gas_error = 0.0
    for month in months:
        predicted_e, predicted_g = predict(params, month, area)
        electric_error += _relative(month["electric_kwh"], predicted_e)
        if month.get("gas_therms") is not None:
            gas_error += _relative(month["gas_therms"], predicted_g)
    return electric_error + gas_error


def _relative(actual: float, predicted: float) -> float:
    scale = max(abs(actual), 1.0)
    return ((actual - predicted) / scale) ** 2


def predict(params: Params, month: dict, area: float) -> tuple[float, float]:
    electric = electric_kwh(
        params,
        area=area,
        days=month["days"],
        occupied_hours=month["occupied_hours"],
        run_hours=month["run_hours"],
        cooling_sp=month["cooling_sp"],
        oa_fraction=month["oa_fraction"],
        cdd=month["cdd"],
    )
    gas = gas_therms(
        params,
        area=area,
        heating_sp=month["heating_sp"],
        oa_fraction=month["oa_fraction"],
        hdd=month["hdd"],
    )
    return electric, gas
