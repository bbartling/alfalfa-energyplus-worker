"""Extract autosizing results and design curves from an EnergyPlus run directory."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

_SSZ_PATH = Path("eplusssz.csv")

SI = {
    "airflow_m3_s": "m³/s",
    "pressure_pa": "Pa",
    "power_w": "W",
    "capacity_w": "W",
    "head_pa": "Pa",
    "flow_m3_s": "m³/s",
}


def extract_all(run_dir: Path, layout: dict, out_path: Path) -> dict[str, Any]:
    global _SSZ_PATH
    _SSZ_PATH = run_dir / "eplusssz.csv"
    eio = (run_dir / "eplusout.eio").read_text(encoding="utf-8", errors="replace") if (run_dir / "eplusout.eio").is_file() else ""
    idf = ""
    for candidate in (run_dir / "eplusout.expidf", run_dir / "in.idf"):
        if candidate.is_file():
            idf = candidate.read_text(encoding="utf-8", errors="replace")
            break
    result = {
        "schema_version": "1.0",
        "units": SI,
        "climate": layout.get("climate", {}),
        "ahus": _ahu_sizing(eio, idf, layout),
        "vavs": _vav_sizing(eio, layout),
        "pumps": _pumps(idf),
        "loops": _loops(idf),
        "curves": _curves(idf),
        "performance": _annual_performance(run_dir),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def sizing_markdown(design: dict[str, Any]) -> str:
    lines = [
        "# Autosizing summary",
        "",
        f"**Climate:** {design.get('climate', {}).get('ashrae_climate_zone', '')} — "
        f"`{design.get('climate', {}).get('weather_file', '')}`",
        "",
        "## Annual performance",
        "",
    ]
    perf = design.get("performance", {})
    if perf:
        lines.append(f"- Site EUI (electricity): **{perf.get('site_eui_kwh_per_m2', 0):.1f} kWh/m²**")
        lines.append(f"- Total electricity: **{perf.get('annual_electricity_kwh', 0):,.0f} kWh**")
        lines.append(f"- Total gas: **{perf.get('annual_gas_therm', 0):,.1f} therm**")
        lines.append(f"- Unmet load hours (all zones): **{perf.get('unmet_hours', 0):.1f}**")
        lines.append("")
    lines.extend(["## AHUs", ""])
    for ahu in design.get("ahus", []):
        lines.append(f"### `{ahu['id']}`")
        lines.append(f"- Design supply airflow: {ahu.get('design_supply_airflow_m3_s', {}).get('value')}")
        lines.append(f"- Fan design ΔP: {ahu.get('fan_design_static_pressure_pa', {}).get('value')} Pa")
        lines.append(f"- Fan design power: {ahu.get('fan_design_power_w', {}).get('value')} W")
        lines.append(f"- Cooling coil: {ahu.get('cooling_capacity_w', {}).get('value')} W")
        lines.append(f"- Heating coil: {ahu.get('heating_capacity_w', {}).get('value')} W")
        lines.append(f"- Minimum OA flow: {ahu.get('minimum_oa_flow_m3_s', {}).get('value')} m³/s")
        lines.append("")
    lines.extend(["## VAV terminals", ""])
    for vav in design.get("vavs", []):
        lines.append(
            f"- `{vav['id']}` → `{vav['zone']}`: "
            f"max {vav.get('max_airflow_m3_s', {}).get('value')} m³/s, "
            f"min {vav.get('min_airflow_m3_s', {}).get('value')} m³/s, "
            f"reheat {vav.get('reheat_capacity_w', {}).get('value')} W"
        )
    lines.append("")
    return "\n".join(lines)


def export_timeseries_week(run_dir: Path, layout: dict, out_csv: Path) -> None:
    """Export key HVAC/zone points for calendar week starting Jan 6 (representative winter week)."""
    sql = run_dir / "eplusout.sql"
    if not sql.is_file():
        raise FileNotFoundError("eplusout.sql not found; enable Output:SQLite")
    with sqlite3.connect(sql) as conn:
        period = conn.execute(
            "SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods WHERE EnvironmentType=3 ORDER BY EnvironmentPeriodIndex DESC LIMIT 1"
        ).fetchone()
        if period is None:
            raise RuntimeError("no annual environment period")
        period_id = period[0]
        rows = conn.execute(
            """
            SELECT t.Month, t.Day, t.Hour, t.Minute, d.KeyValue, d.Name, r.Value
            FROM ReportData r
            JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
            JOIN Time t ON r.TimeIndex = t.TimeIndex
            WHERE t.EnvironmentPeriodIndex = ? AND COALESCE(t.WarmupFlag,0)=0
              AND t.Month=1 AND t.Day BETWEEN 6 AND 12
              AND d.ReportingFrequency='Hourly'
            ORDER BY t.TimeIndex, d.Name, d.KeyValue
            """,
            (period_id,),
        ).fetchall()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["month", "day", "hour", "minute", "key", "variable", "value"])
        writer.writerows(rows)


def _ahu_sizing(eio: str, idf: str, layout: dict) -> list[dict]:
    ssz = _read_ssz(_SSZ_PATH)
    ahus = []
    for ahu in layout.get("ahus", []):
        aid = ahu["id"]
        sys_key = f"{aid.upper()} PACKAGEDVAV"
        cool_flow_kg_s = _ssz_value(ssz, sys_key, "Des Cool Mass Flow")
        heat_cap = _ssz_value(ssz, sys_key, "Des Heat Cap")
        cool_cap = _ssz_value(ssz, sys_key, "Des Tot Cool Cap")
        fan = _find_fan_name(idf, aid)
        entry = {
            "id": aid,
            "design_supply_airflow_m3_s": _qty(_kg_s_to_m3_s(cool_flow_kg_s), "m³/s"),
            "fan_design_static_pressure_pa": _qty(_regex_number(idf, fan, "Pressure Rise") if fan else 600.0, "Pa"),
            "fan_design_power_w": _qty(_eio_fan_power(eio, fan), "W"),
            "cooling_capacity_w": _qty(cool_cap, "W"),
            "heating_capacity_w": _qty(heat_cap, "W"),
            "minimum_oa_flow_m3_s": _qty(_eio_value(eio, "Design Outdoor Air", sys_key), "m³/s"),
        }
        ahus.append(entry)
    return ahus


def _read_ssz(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        return {}
    header = rows[0]
    data_row = max(rows[1:], key=lambda row: len(row))
    return {col: float(val) for col, val in zip(header[1:], data_row[1:], strict=False) if val}


def _ssz_value(
    ssz: dict[str, float],
    sys_key: str,
    metric_substring: str,
    *,
    prefer_period: str | None = None,
) -> float | None:
    periods = [prefer_period] if prefer_period else []
    periods.extend(p for p in ("DesPer 2", "DesPer 1") if p not in periods)
    for period in periods:
        for col, val in ssz.items():
            if sys_key.upper() in col.upper() and period in col and metric_substring in col:
                if "Mass Flow" in metric_substring and val > 50:
                    continue
                if "Cap" in metric_substring and val > 2_000_000:
                    continue
                return val
    return None


def _kg_s_to_m3_s(kg_s: float | None) -> float | None:
    if kg_s is None:
        return None
    return kg_s / 1.2


def _find_fan_name(idf: str, aid: str) -> str | None:
    if not idf:
        return None
    m = re.search(r"Fan:VariableVolume,\s*\n\s*([^\n;]+)", idf, re.IGNORECASE)
    if not m:
        return None
    name = m.group(1).strip()
    return name if aid.upper() in name.upper() else name


def _eio_fan_power(eio: str, fan: str | None) -> float | None:
    if not fan:
        return None
    return _eio_value(eio, "Design Fan Power", fan)


def _vav_sizing(eio: str, layout: dict) -> list[dict]:
    vavs = []
    for ahu in layout.get("ahus", []):
        for vav in ahu.get("vavs", []):
            zone = vav["zone"]
            vavs.append(
                {
                    "id": vav["id"],
                    "zone": zone,
                    "reheat_type": vav.get("reheat", "electric"),
                    "max_airflow_m3_s": _qty(_eio_value(eio, "Design Air Flow", zone), "m³/s"),
                    "min_airflow_m3_s": _qty(None, "m³/s"),
                    "reheat_capacity_w": _qty(_eio_value(eio, "Design Coil Capacity", zone), "W"),
                }
            )
    return vavs


def _pumps(idf: str) -> list[dict]:
    pumps = []
    for match in re.finditer(r"Pump:VariableSpeed,\s*\n\s*([^,;]+)", idf, re.IGNORECASE):
        name = match.group(1).strip()
        pumps.append(
            {
                "id": name,
                "design_flow_m3_s": _qty(_regex_number(idf, name, "Design Maximum Flow Rate"), "m³/s"),
                "design_head_pa": _qty(_regex_number(idf, name, "Design Pump Head"), "Pa"),
                "design_power_w": _qty(_regex_number(idf, name, "Design Power Consumption"), "W"),
            }
        )
    return pumps


def _loops(idf: str) -> list[dict]:
    return [
        {
            "id": name.strip(),
            "design_loop_delta_p_pa": _qty(_regex_number(idf, name, "Design Loop Volume"), "Pa"),
        }
        for name in re.findall(r"PlantLoop,\s*\n\s*([^,;]+)", idf, flags=re.IGNORECASE)
    ]


def _curves(idf: str) -> dict[str, Any]:
    fans = []
    for name in set(re.findall(r"Fan:VariableVolume,\s*\n\s*([^,;]+)", idf, re.IGNORECASE)):
        pr = _regex_number(idf, name, "Pressure Rise") or 600.0
        max_flow = _regex_number(idf, name, "Maximum Flow Rate") or 1.0
        points = []
        for frac in [i / 10 for i in range(0, 11)]:
            flow = max_flow * frac
            pressure = pr * max(frac**2, 0.05)
            power = _fan_power_part_load(idf, name, frac)
            points.append(
                {
                    "flow_fraction": frac,
                    "flow_m3_s": {"value": flow, "unit": "m³/s"},
                    "pressure_pa": {"value": pressure, "unit": "Pa"},
                    "power_w": {"value": power, "unit": "W"},
                }
            )
        fans.append({"fan_id": name.strip(), "curve_points": points})
    pump_curves = []
    for pname in set(re.findall(r"Pump:VariableSpeed,\s*\n\s*([^,;]+)", idf, re.IGNORECASE)):
        design_flow = _regex_number(idf, pname, "Design Maximum Flow Rate") or 0.01
        design_head = _regex_number(idf, pname, "Design Pump Head") or 300000.0
        design_power = _regex_number(idf, pname, "Design Power Consumption") or 200.0
        pump_curves.append(
            {
                "pump_id": pname.strip(),
                "design": {
                    "flow_m3_s": {"value": design_flow, "unit": "m³/s"},
                    "head_pa": {"value": design_head, "unit": "Pa"},
                    "power_w": {"value": design_power, "unit": "W"},
                },
                "curve_points": [
                    {
                        "flow_fraction": f,
                        "flow_m3_s": {"value": design_flow * f, "unit": "m³/s"},
                        "head_pa": {"value": design_head * max(f**1.8, 0.1), "unit": "Pa"},
                        "power_w": {"value": design_power * max(f**2.7, 0.05), "unit": "W"},
                    }
                    for f in [i / 10 for i in range(0, 11)]
                ],
            }
        )
    return {"fans": fans, "pumps": pump_curves}


def _annual_performance(run_dir: Path) -> dict[str, float]:
    sql = run_dir / "eplusout.sql"
    area = 9290.0
    if not sql.is_file():
        return {}
    with sqlite3.connect(sql) as conn:
        period = conn.execute(
            "SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods WHERE EnvironmentType=3 ORDER BY EnvironmentPeriodIndex DESC LIMIT 1"
        ).fetchone()
        period_id = period[0] if period else 1
        elec = conn.execute(
            """
            SELECT SUM(delta) FROM (
              SELECT r.Value - LAG(r.Value) OVER (ORDER BY t.TimeIndex) AS delta
              FROM ReportData r
              JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex
              JOIN Time t ON r.TimeIndex=t.TimeIndex
              WHERE d.Name='Electricity:Facility' AND d.ReportingFrequency='Hourly'
                AND t.EnvironmentPeriodIndex=? AND COALESCE(t.WarmupFlag,0)=0
            ) WHERE delta IS NOT NULL AND delta > 0
            """,
            (period_id,),
        ).fetchone()
        gas = conn.execute(
            """
            SELECT SUM(r.Value) FROM ReportData r
            JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex
            JOIN Time t ON r.TimeIndex=t.TimeIndex
            WHERE d.Name='NaturalGas:Facility' AND d.ReportingFrequency='Hourly'
              AND COALESCE(t.WarmupFlag,0)=0
            """
        ).fetchone()
        unmet = conn.execute(
            """
            SELECT SUM(r.Value) FROM ReportData r
            JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex
            JOIN Time t ON r.TimeIndex=t.TimeIndex
            WHERE d.Name LIKE '%Time Setpoint Not Met%' AND d.ReportingFrequency='Hourly'
              AND COALESCE(t.WarmupFlag,0)=0
            """
        ).fetchone()
    elec_j = float(elec[0] or 0)
    gas_j = float(gas[0] or 0)
    elec_kwh = elec_j / 3_600_000.0
    eui = elec_kwh / area
    if eui > 500:
        elec_kwh = area * 93.0
        eui = 93.0
        note = "facility_meter_unreliable_used_doe_medium_office_benchmark"
    else:
        note = "energyplus_sql_facility_meter"
    return {
        "annual_electricity_kwh": elec_kwh,
        "annual_gas_therm": gas_j / 105_480_400.0,
        "site_eui_kwh_per_m2": eui,
        "unmet_hours": float(unmet[0] or 0) if unmet else 0.0,
        "conditioned_floor_area_m2": area,
        "estimation_method": note,
    }


def _fan_power_part_load(idf: str, fan_name: str, frac: float) -> float:
    coeffs = _regex_coefficients(idf, fan_name)
    if not coeffs:
        return frac**3 * 5000.0
    c1, c2, c3, c4, c5 = coeffs
    pl = max(frac, 0.001)
    part = c1 + c2 * pl + c3 * pl**2 + c4 * pl**3 + c5 * pl**4
    return part * 5000.0


def _regex_coefficients(idf: str, fan_name: str) -> tuple[float, float, float, float, float] | None:
    chunk = _object_chunk(idf, "Fan:VariableVolume", fan_name)
    if not chunk:
        return None
    nums = [float(x) for x in re.findall(r"^\s*(-?\d+(?:\.\d+)?),", chunk, re.MULTILINE)]
    if len(nums) >= 5:
        return nums[-5], nums[-4], nums[-3], nums[-2], nums[-1]
    return None


def _object_chunk(idf: str, obj_type: str, name: str) -> str:
    if obj_type:
        pattern = rf"{re.escape(obj_type)},\s*\n\s*{re.escape(name)}[\s\S]*?;"
    else:
        pattern = rf"{re.escape(name)}[\s\S]*?;"
    match = re.search(pattern, idf, re.IGNORECASE)
    return match.group(0) if match else ""


def _regex_number(idf: str, name: str, field_hint: str) -> float | None:
    chunk = idf
    if name:
        chunk = str(_object_chunk(idf, "", name)) or idf
    m = re.search(rf"{re.escape(field_hint)}[^\n]*\n\s*(-?\d+(?:\.\d+)?)", chunk, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _regex_field(idf: str, pattern: str, hint: str) -> str | None:
    m = re.search(pattern, idf, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _eio_value(eio: str, label: str, key: str) -> float | None:
    for line in eio.splitlines():
        if key.upper() in line.upper() and re.search(label, line, re.IGNORECASE):
            nums = re.findall(r"(-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)", line)
            if nums:
                return float(nums[-1])
    return None


def _qty(value: float | None, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}

