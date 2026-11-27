"""Build monthly HVAC summaries for two offices.

Meters come from a small generating process in this file, with about ±4% noise
and coefficients that are not a grid point of any search. The calibrator fits
its own change-point model and is expected to recover the coefficients within
a tolerance. The generator does not call the calibrator.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from twin.schemas import OperationsBatch
from twin.service import apply_inference, month_from_payload

SITES = (
    {
        "site_id": "site-cold-office",
        "timezone": "America/Denver",
        "latitude": 39.74,
        "longitude": -104.99,
        "floor_area_m2": 1600,
        "building_type": "small-office",
        "truth": {"base_w_m2": 9.3, "cooling_kwh_per_cdd_m2": 0.0085, "heating_therm_per_hdd_m2": 0.00042},
        "heating": 21.0,
        "cooling": 24.0,
        "sat": 13.0,
    },
    {
        "site_id": "site-mixed-office",
        "timezone": "America/New_York",
        "latitude": 40.71,
        "longitude": -74.01,
        "floor_area_m2": 8000,
        "building_type": "medium-office",
        "truth": {"base_w_m2": 11.7, "cooling_kwh_per_cdd_m2": 0.0064, "heating_therm_per_hdd_m2": 0.00031},
        "heating": 20.5,
        "cooling": 23.5,
        "sat": 12.5,
    },
)

# Twelve usable backfill months (January is excluded as a fault), then one incremental month.
MONTHS = (
    (2025, 4, 180, 20),
    (2025, 5, 70, 60),
    (2025, 6, 15, 140),
    (2025, 7, 5, 200),
    (2025, 8, 8, 180),
    (2025, 9, 40, 90),
    (2025, 10, 120, 30),
    (2025, 11, 280, 8),
    (2025, 12, 420, 6),
    (2026, 1, 480, 5),
    (2026, 2, 390, 7),
    (2026, 3, 260, 18),
    (2026, 4, 140, 40),
    (2026, 5, 60, 90),
)
FAULT_MONTH = (2026, 1)


def site_record(spec: dict) -> dict:
    return {key: spec[key] for key in ("site_id", "timezone", "latitude", "longitude", "floor_area_m2", "building_type")}


def batches_for(spec: dict, *, include_incremental: bool) -> list[dict]:
    months = MONTHS if include_incremental else MONTHS[:-1]
    return [build_batch(spec, year, month, hdd, cdd) for year, month, hdd, cdd in months]


def build_batch(spec: dict, year: int, month: int, hdd: float, cdd: float) -> dict:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    fault = (year, month) == FAULT_MONTH
    equipment = "rtu-1" if spec["building_type"] == "small-office" else "ahu-1"
    body = {
        "schema_version": "1.0",
        "batch_id": str(uuid5(NAMESPACE_URL, f"{spec['site_id']}:{start.date()}")),
        "site_id": spec["site_id"],
        "generated_at": start.isoformat(),
        "period": {"start": start.isoformat(), "end": end.isoformat(), "label": "month"},
        "run_hours": [{"equipment_id": equipment, "hours": 220, "hour_of_week": _week_profile(), "method": "status>0.5"}],
        "schedules": [
            {
                "equipment_id": equipment,
                "name": "occupied",
                "windows": [{"days": "weekday", "start": "07:00", "end": "18:00"}],
            }
        ],
        "setpoints": [
            {
                "equipment_id": equipment,
                "kind": "duct_static",
                "period": "always",
                "unit": "Pa",
                "value": 375,
                "source": "actual",
            }
        ],
        "sensors": [
            {
                "equipment_id": equipment,
                "kind": "supply_air_temp",
                "unit": "degC",
                "samples_while_running": [spec["sat"]] * 24,
            },
            {
                "equipment_id": equipment,
                "kind": "zone_temp",
                "unit": "degC",
                "occupied_samples": [spec["heating"]] * 40 + [spec["cooling"]] * 40,
                "unoccupied_samples": [spec["heating"] - 2] * 20 + [spec["cooling"] + 3] * 20,
            },
            {
                "equipment_id": equipment,
                "kind": "duct_static",
                "unit": "Pa",
                "samples_while_running": [100] * 12,
            },
        ],
        "outdoor_air": [
            {"equipment_id": equipment, "oa_fraction_mean": 0.15, "economizer_hours": 12, "economizer_enabled": True}
        ],
        "faults": [
            {
                "equipment_id": equipment,
                "rule_id": "economizer-stuck",
                "count": 4 if fault else 0,
                "exclude_from_calibration": fault,
            }
        ],
        "meters": [],
        "weather": {"source": "site-summary", "drybulb_mean_c": 10, "hdd_base_18c": hdd, "cdd_base_18c": cdd},
    }
    normalized = apply_inference(OperationsBatch.model_validate(body))
    month_inputs = month_from_payload(normalized.model_dump(mode="json"))
    electric, gas = _generated_meters(spec, month_inputs, year, month)
    if fault:
        electric = 9_000_000
    body["meters"] = [
        _meter(spec["site_id"], "elec-main", "electricity", "kWh", start, end, round(electric, 3)),
        _meter(spec["site_id"], "gas-main", "natural_gas", "therm", start, end, round(gas, 3)),
    ]
    return body


def _generated_meters(spec: dict, month: dict, year: int, month_number: int) -> tuple[float, float]:
    """A balance-point bill plus a small plug load. Not the calibrator's predict()."""
    area = spec["floor_area_m2"]
    truth = spec["truth"]
    days = month["days"]
    cdd = max(0.0, month["cdd"] - days * (month["cooling_sp"] - 24.0))
    hdd = max(0.0, month["hdd"] + days * (month["heating_sp"] - 21.0))
    lights = truth["base_w_m2"] * area * month["occupied_hours"] / 1000
    fans = 1.5 * area * month["run_hours"] / 1000
    plug = 0.03 * lights
    cooling = truth["cooling_kwh_per_cdd_m2"] * area * cdd
    heating = truth["heating_therm_per_hdd_m2"] * area * hdd
    electric_noise = _noise(spec["site_id"], year, month_number, "electricity")
    gas_noise = _noise(spec["site_id"], year, month_number, "gas")
    return (lights + fans + plug + cooling) * electric_noise, heating * gas_noise


def _noise(site_id: str, year: int, month: int, fuel: str) -> float:
    digest = hashlib.sha256(f"{site_id}:{year}:{month}:{fuel}".encode()).hexdigest()
    unit = int(digest[:8], 16) / 0xFFFFFFFF
    return 1.0 + 0.04 * (unit * 2 - 1)


def _meter(site_id, meter_id, fuel, unit, start, end, value) -> dict:
    return {
        "meter_id": meter_id,
        "fuel": fuel,
        "unit": unit,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "value": value,
        "granularity": "month",
    }


def _week_profile() -> list[float]:
    profile = []
    for day in range(7):
        for hour in range(24):
            occupied = day < 5 and 7 <= hour < 18
            profile.append(0.85 if occupied else 0.05)
    return profile
