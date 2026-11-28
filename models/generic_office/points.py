"""Output variables for downstream BACnet / Alfalfa point mapping."""

from __future__ import annotations

from .idf_writer import IdfDocument, IdfObject
from .layout import Layout

# Key is a logical BACnet-ish point id; value is EnergyPlus variable name and optional key field.
POINT_CATALOG: dict[str, dict[str, str]] = {
    "zone-air-temp": {"variable": "Zone Mean Air Temperature", "frequency": "timestep"},
    "zone-co2": {"variable": "Zone Air CO2 Concentration", "frequency": "timestep"},
    "zone-occ-fraction": {"variable": "Zone Occupancy Fraction", "frequency": "timestep"},
    "vav-damper-position": {"variable": "Air Terminal Damper Position", "frequency": "timestep"},
    "vav-reheat-coil-power": {"variable": "Air Terminal Heating Coil Heating Rate", "frequency": "timestep"},
    "vav-airflow": {"variable": "System Node Mass Flow Rate", "frequency": "timestep"},
    "ahu-supply-air-temp": {"variable": "System Node Temperature", "frequency": "timestep"},
    "ahu-supply-airflow": {"variable": "Fan Air Mass Flow Rate", "frequency": "timestep"},
    "ahu-cooling-coil-power": {"variable": "Coil Cooling Rate", "frequency": "timestep"},
    "ahu-heating-coil-power": {"variable": "Coil Heating Rate", "frequency": "timestep"},
    "ahu-fan-power": {"variable": "Fan Electric Power", "frequency": "timestep"},
    "oa-fraction": {"variable": "System Node Mass Flow Rate", "frequency": "timestep"},
    "electricity-facility": {"variable": "Electricity:Facility", "frequency": "hourly"},
    "gas-facility": {"variable": "NaturalGas:Facility", "frequency": "hourly"},
}


def add_output_requests(doc: IdfDocument, layout: Layout) -> None:
    doc.add(IdfObject("Output:VariableDictionary", ["IDF"]))
    doc.add(IdfObject("Output:SQLite", ["SimpleAndTabular"]))
    for vav in layout.all_vavs():
        z = vav.zone
        doc.add(IdfObject("Output:Variable", [z, "Zone Mean Air Temperature", "timestep"]))
        doc.add(IdfObject("Output:Variable", [z, "Zone Air CO2 Concentration", "timestep"]))
        doc.add(IdfObject("Output:Variable", [z, "Zone Occupancy Fraction", "timestep"]))
        doc.add(
            IdfObject(
                "Output:Variable",
                [f"{vav.id} ATU", "Air Terminal Damper Position", "timestep"],
            )
        )
        doc.add(
            IdfObject(
                "Output:Variable",
                [f"{vav.id} ATU", "Air Terminal Heating Coil Heating Rate", "timestep"],
            )
        )
    for ahu in layout.ahus:
        loop = f"{ahu.id} AirLoop"
        doc.add(IdfObject("Output:Variable", [f"{ahu.id} Supply Fan", "Fan Air Mass Flow Rate", "timestep"]))
        doc.add(IdfObject("Output:Variable", [f"{ahu.id} Supply Fan", "Fan Electric Power", "timestep"]))
        doc.add(IdfObject("Output:Variable", [f"{ahu.id} DX Cooling", "Coil Cooling Rate", "timestep"]))
        if ahu.gas_preheat:
            doc.add(IdfObject("Output:Variable", [f"{ahu.id} Gas Preheat", "Coil Heating Rate", "timestep"]))
        doc.add(IdfObject("Output:Variable", [f"{loop} SAT", "System Node Temperature", "timestep"]))
    doc.add(IdfObject("Output:Meter", ["Electricity:Facility", "hourly"]))
    doc.add(IdfObject("Output:Meter", ["NaturalGas:Facility", "hourly"]))