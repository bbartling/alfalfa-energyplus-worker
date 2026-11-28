"""Representative-week time-series export from EnergyPlus SQLite output."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Literal

from .points import POINT_CATALOG

Resolution = Literal["hourly", "minute"]

REP_WEEK = {"begin_month": 1, "begin_day": 6, "end_month": 1, "end_day": 12}

# EnergyPlus 24.2 SQLite label for Output:Variable …, timestep
ZONE_TIMESTEP_FREQ = "Zone Timestep"


def catalog_variable_names() -> set[str]:
    return {meta["variable"] for meta in POINT_CATALOG.values()}


def layout_key_tokens(layout: dict) -> list[str]:
    tokens: list[str] = []
    for ahu in layout.get("ahus", []):
        tokens.append(str(ahu["id"]).upper().replace("-", "-"))
        for vav in ahu.get("vavs", []):
            tokens.append(str(vav.get("zone", vav["id"])).upper())
    return tokens


def _key_matches(key_value: str, tokens: list[str]) -> bool:
    upper = (key_value or "").upper()
    return any(tok in upper for tok in tokens)


def export_timeseries_week(
    run_dir: Path,
    layout: dict,
    out_csv: Path,
    *,
    resolution: Resolution = "hourly",
) -> int:
    """
    Export catalog-aligned AHU/VAV points for the representative winter week (Jan 6–12).

    ``hourly`` averages zone-timestep samples to the clock hour (default annual-run path).
    ``minute`` emits every zone timestep (use with ``timesteps_per_hour``: 60).
    """
    sql = run_dir / "eplusout.sql"
    if not sql.is_file():
        raise FileNotFoundError("eplusout.sql not found; enable Output:SQLite")
    variables = sorted(catalog_variable_names())
    tokens = layout_key_tokens(layout)
    placeholders = ",".join("?" for _ in variables)
    week = REP_WEEK
    with sqlite3.connect(sql) as conn:
        period = conn.execute(
            "SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods "
            "WHERE EnvironmentType=3 ORDER BY EnvironmentPeriodIndex DESC LIMIT 1"
        ).fetchone()
        if period is None:
            raise RuntimeError("no annual environment period")
        period_id = period[0]
        base_where = (
            f"t.EnvironmentPeriodIndex = ? AND COALESCE(t.WarmupFlag,0)=0 "
            f"AND t.Month = {week['begin_month']} AND t.Day BETWEEN {week['begin_day']} AND {week['end_day']} "
            f"AND d.ReportingFrequency = ? AND d.Name IN ({placeholders})"
        )
        params = [period_id, ZONE_TIMESTEP_FREQ, *variables]
        if resolution == "minute":
            rows = conn.execute(
                f"""
                SELECT t.Month, t.Day, t.Hour, t.Minute, d.KeyValue, d.Name, r.Value
                FROM ReportData r
                JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
                JOIN Time t ON r.TimeIndex = t.TimeIndex
                WHERE {base_where}
                ORDER BY t.TimeIndex, d.Name, d.KeyValue
                """,
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT t.Month, t.Day, t.Hour, 0, d.KeyValue, d.Name, AVG(r.Value)
                FROM ReportData r
                JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
                JOIN Time t ON r.TimeIndex = t.TimeIndex
                WHERE {base_where}
                GROUP BY t.Month, t.Day, t.Hour, d.KeyValue, d.Name
                ORDER BY t.Month, t.Day, t.Hour, d.Name, d.KeyValue
                """,
                params,
            ).fetchall()
    filtered = [row for row in rows if _key_matches(row[4], tokens)]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["month", "day", "hour", "minute", "key", "variable", "value"])
        writer.writerows(filtered)
    return len(filtered)


def minute_week_design_overrides() -> dict:
    """Design JSON fragment for a 1-minute-timestep representative-week-only run."""
    return {
        "timesteps_per_hour": 60,
        "run_period": {
            "name": "RepresentativeWeek",
            **REP_WEEK,
        },
        # Autosized HVACTemplate fields still require zone/system sizing; skip design-day runs only.
        "simulation_control": {
            "do_zone_sizing": "Yes",
            "do_system_sizing": "Yes",
            "do_plant_sizing": "No",
            "run_sizing_periods": "No",
            "run_weather_periods": "Yes",
        },
    }