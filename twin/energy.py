"""Screening change-point model for monthly bills.

Electricity is a baseload (occupied hours), a fan term from average run hours,
and cooling proportional to cooling degree-days at a balance point that moves
with the occupied cooling setpoint. Gas is heating degree-days at a balance
point that moves with the heating setpoint. This is an ASHRAE-style inverse
model for a quick screening estimate. It is not a Guideline 14 calibration.
"""

from __future__ import annotations

from dataclasses import dataclass

FAN_W_M2 = 1.5
COOL_BALANCE_C = 24.0
HEAT_BALANCE_C = 21.0


@dataclass(frozen=True)
class Params:
    base_w_m2: float
    cooling_kwh_per_cdd_m2: float
    heating_therm_per_hdd_m2: float

    def as_dict(self) -> dict:
        return {
            "base_w_m2": self.base_w_m2,
            "cooling_kwh_per_cdd_m2": self.cooling_kwh_per_cdd_m2,
            "heating_therm_per_hdd_m2": self.heating_therm_per_hdd_m2,
        }


def adjusted_cdd(cdd: float, days: float, cooling_sp: float) -> float:
    """Degree-days at base 18 °C, shifted when the cooling setpoint leaves 24 °C."""
    return max(0.0, cdd - days * (cooling_sp - COOL_BALANCE_C))


def adjusted_hdd(hdd: float, days: float, heating_sp: float) -> float:
    """Degree-days at base 18 °C, shifted when the heating setpoint leaves 21 °C."""
    return max(0.0, hdd + days * (heating_sp - HEAT_BALANCE_C))


def electric_kwh(params: Params, *, area: float, month: dict) -> float:
    baseload = params.base_w_m2 * area * month["occupied_hours"] / 1000
    fans = FAN_W_M2 * area * month["run_hours"] / 1000
    cooling = params.cooling_kwh_per_cdd_m2 * area * adjusted_cdd(month["cdd"], month["days"], month["cooling_sp"])
    return baseload + fans + cooling


def gas_therms(params: Params, *, area: float, month: dict) -> float:
    heating = params.heating_therm_per_hdd_m2 * area * adjusted_hdd(month["hdd"], month["days"], month["heating_sp"])
    return heating


def predict(params: Params, month: dict, area: float) -> tuple[float, float]:
    return electric_kwh(params, area=area, month=month), gas_therms(params, area=area, month=month)


def fit(months: list[dict], area: float) -> Params:
    """Least squares for baseload, cooling slope, and heating slope."""
    if len(months) < 3:
        raise ValueError("need at least three months to fit a change-point model")
    xs, zs, ys, ws, gs = [], [], [], [], []
    for month in months:
        fans = FAN_W_M2 * area * month["run_hours"] / 1000
        xs.append(area * month["occupied_hours"] / 1000)
        zs.append(area * adjusted_cdd(month["cdd"], month["days"], month["cooling_sp"]))
        ys.append(month["electric_kwh"] - fans)
        ws.append(area * adjusted_hdd(month["hdd"], month["days"], month["heating_sp"]))
        gs.append(month.get("gas_therms") or 0.0)
    base, cooling = _solve2(xs, zs, ys)
    heating = _solve1(ws, gs) if any(item > 0 for item in gs) else 0.0
    return Params(max(0.0, base), max(0.0, cooling), max(0.0, heating))


def leave_one_out(months: list[dict], area: float) -> list[Params]:
    fitted = []
    for index in range(len(months)):
        sample = months[:index] + months[index + 1 :]
        try:
            fitted.append(fit(sample, area))
        except ValueError:
            continue
    return fitted


def _solve2(xs: list[float], zs: list[float], ys: list[float]) -> tuple[float, float]:
    sxx = sum(x * x for x in xs)
    szz = sum(z * z for z in zs)
    sxz = sum(x * z for x, z in zip(xs, zs, strict=True))
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    szy = sum(z * y for z, y in zip(zs, ys, strict=True))
    det = sxx * szz - sxz * sxz
    if abs(det) < 1e-9:
        raise ValueError("change-point design is singular")
    base = (sxy * szz - szy * sxz) / det
    cooling = (sxx * szy - sxz * sxy) / det
    return base, cooling


def _solve1(xs: list[float], ys: list[float]) -> float:
    sxx = sum(x * x for x in xs)
    if sxx < 1e-9:
        return 0.0
    return sum(x * y for x, y in zip(xs, ys, strict=True)) / sxx
