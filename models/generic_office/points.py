"""Output variables for downstream BACnet / Alfalfa point mapping."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .idf_writer import IdfDocument, IdfObject
from .layout import Layout

# Stable point role ids used by functional-test apps (Haystack-style refs in export_point_list).
POINT_CATALOG: dict[str, dict[str, str]] = {
    "ahu-supply-air-temp": {
        "variable": "System Node Temperature",
        "ashrae223_role": "supply-air-temp-sensor",
        "haystack_tags": "point,air,temp,sensor,equipRef",
    },
    "ahu-return-air-temp": {
        "variable": "System Node Temperature",
        "ashrae223_role": "return-air-temp-sensor",
        "haystack_tags": "point,air,temp,sensor,equipRef",
    },
    "ahu-mixed-air-temp": {
        "variable": "System Node Temperature",
        "ashrae223_role": "mixed-air-temp-sensor",
        "haystack_tags": "point,air,temp,sensor,equipRef",
    },
    "ahu-outdoor-air-temp": {
        "variable": "System Node Temperature",
        "ashrae223_role": "outside-air-temp-sensor",
        "haystack_tags": "point,air,temp,sensor,siteRef",
    },
    "ahu-dat-setpoint": {
        "variable": "Air System Cooling Coil Setpoint Temperature",
        "ashrae223_role": "discharge-air-temp-sp",
        "haystack_tags": "point,sp,air,temp,equipRef",
    },
    "ahu-duct-static-pressure": {
        "variable": "System Node Pressure",
        "ashrae223_role": "duct-static-pressure-sensor",
        "haystack_tags": "point,air,pressure,sensor,equipRef",
    },
    "ahu-fan-speed": {
        "variable": "Fan Part Load Ratio",
        "ashrae223_role": "fan-speed-sensor",
        "haystack_tags": "point,fan,speed,sensor,equipRef",
    },
    "ahu-fan-power": {
        "variable": "Fan Electric Power",
        "ashrae223_role": "fan-power-sensor",
        "haystack_tags": "point,fan,power,sensor,equipRef",
    },
    "ahu-fan-status": {
        "variable": "Fan Runtime Fraction",
        "ashrae223_role": "fan-status-sensor",
        "haystack_tags": "point,fan,run,sensor,equipRef",
    },
    "ahu-oa-damper": {
        "variable": "Air System Outdoor Air Flow Fraction",
        "ashrae223_role": "oa-damper-position-sensor",
        "haystack_tags": "point,damper,oa,sensor,equipRef",
    },
    "ahu-cooling-valve": {
        "variable": "Coil Part Load Ratio",
        "ashrae223_role": "cooling-valve-position-sensor",
        "haystack_tags": "point,valve,cooling,sensor,equipRef",
    },
    "ahu-heating-valve": {
        "variable": "Coil Part Load Ratio",
        "ashrae223_role": "heating-valve-position-sensor",
        "haystack_tags": "point,valve,heating,sensor,equipRef",
    },
    "vav-zone-temp": {
        "variable": "Zone Mean Air Temperature",
        "ashrae223_role": "zone-air-temp-sensor",
        "haystack_tags": "point,air,temp,zone,sensor,spaceRef",
    },
    "vav-heating-sp": {
        "variable": "Zone Thermostat Heating Setpoint Temperature",
        "ashrae223_role": "zone-heating-temp-sp",
        "haystack_tags": "point,sp,air,temp,zone,spaceRef",
    },
    "vav-cooling-sp": {
        "variable": "Zone Thermostat Cooling Setpoint Temperature",
        "ashrae223_role": "zone-cooling-temp-sp",
        "haystack_tags": "point,sp,air,temp,zone,spaceRef",
    },
    "vav-airflow": {
        "variable": "System Node Mass Flow Rate",
        "ashrae223_role": "supply-airflow-sensor",
        "haystack_tags": "point,air,flow,sensor,equipRef",
    },
    "vav-airflow-sp": {
        "variable": "Air Terminal Minimum Air Flow",
        "ashrae223_role": "supply-airflow-sp",
        "haystack_tags": "point,sp,air,flow,equipRef",
    },
    "vav-damper-position": {
        "variable": "Air Terminal Damper Position",
        "ashrae223_role": "damper-position-sensor",
        "haystack_tags": "point,damper,sensor,equipRef",
    },
    "vav-reheat-power": {
        "variable": "Air Terminal Heating Coil Heating Rate",
        "ashrae223_role": "reheat-power-sensor",
        "haystack_tags": "point,heating,power,sensor,equipRef",
    },
}


def add_output_requests(doc: IdfDocument, layout: Layout) -> None:
    doc.add(IdfObject("Output:VariableDictionary", ["IDF"]))
    doc.add(IdfObject("Output:SQLite", ["SimpleAndTabular"]))
    doc.add(IdfObject("Output:Meter", ["Electricity:Facility", "hourly"]))
    doc.add(IdfObject("Output:Meter", ["NaturalGas:Facility", "hourly"]))
    doc.add(IdfObject("Output:Meter", ["Electricity:HVAC", "hourly"]))
    for variable in {
        "Zone Mean Air Temperature",
        "Zone Thermostat Heating Setpoint Temperature",
        "Zone Thermostat Cooling Setpoint Temperature",
        "Air Terminal Damper Position",
        "Air Terminal Heating Coil Heating Rate",
        "System Node Mass Flow Rate",
        "System Node Temperature",
        "System Node Pressure",
        "Fan Part Load Ratio",
        "Fan Electric Power",
        "Fan Runtime Fraction",
        "Coil Cooling Rate",
        "Coil Heating Rate",
        "Coil Part Load Ratio",
        "Air System Outdoor Air Flow Fraction",
        "Air System Cooling Coil Setpoint Temperature",
        "Zone Air System Sensible Load",
    }:
        doc.add(IdfObject("Output:Variable", ["*", variable, "timestep"]))


def export_point_list(layout: Layout, path: Path) -> None:
    rows: list[dict] = []
    for ahu in layout.ahus:
        for role, meta in POINT_CATALOG.items():
            if not role.startswith("ahu-"):
                continue
            rows.append(
                _row(
                    point_id=f"{ahu.id}.{role}",
                    equip=ahu.id,
                    zone="",
                    role=role,
                    variable=meta["variable"],
                    key=f"{ahu.id} PackagedVAV",
                    meta=meta,
                )
            )
        for vav in ahu.vavs:
            for role, meta in POINT_CATALOG.items():
                if not role.startswith("vav-"):
                    continue
                rows.append(
                    _row(
                        point_id=f"{vav.id}.{role}",
                        equip=vav.id,
                        zone=vav.zone,
                        role=role,
                        variable=meta["variable"],
                        key=f"{vav.zone}",
                        meta=meta,
                    )
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def _row(point_id: str, equip: str, zone: str, role: str, variable: str, key: str, meta: dict) -> dict:
    return {
        "point_id": point_id,
        "equipment_id": equip,
        "zone": zone,
        "role_id": role,
        "energyplus_variable": variable,
        "energyplus_key": key,
        "ashrae223_role": meta.get("ashrae223_role", ""),
        "haystack_tags": meta.get("haystack_tags", ""),
        "frequency": "timestep",
    }