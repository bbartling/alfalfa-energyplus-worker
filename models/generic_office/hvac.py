"""Packaged VAV systems via HVACTemplate (expanded by EnergyPlus at run time)."""

from __future__ import annotations

from .idf_writer import IdfDocument, IdfObject
from .layout import AhuSpec, Layout, VavSpec


def add_hvac(doc: IdfDocument, layout: Layout, design: dict) -> None:
    doc.extend(_hvac_schedules(design))
    doc.add(
        IdfObject(
            "HVACTemplate:Thermostat",
            [
                "Office Thermostat",
                "Thermostat Heating Setpoint",
                "",
                "Thermostat Cooling Setpoint",
                "",
            ],
        )
    )
    for ahu in layout.ahus:
        doc.add(_packaged_vav_system(ahu, design))
        for vav in ahu.vavs:
            doc.add(_zone_vav(vav, ahu, design))


def _hvac_schedules(design: dict) -> list[IdfObject]:
    sat = design.get("supply_air_temp_cooling_c", 13.0)
    return [
        IdfObject("Schedule:Constant", ["FanAvailSched", "Fraction", 1]),
        IdfObject("Schedule:Constant", ["Min OA Sched", "Fraction", 1]),
        IdfObject(
            "Schedule:Compact",
            [
                "SAT Reset Schedule",
                "Temperature",
                "Through: 12/31",
                "For: AllDays",
                "Until: 24:00",
                sat,
            ],
        ),
    ]


def _packaged_vav_system(ahu: AhuSpec, design: dict) -> IdfObject:
    sys_name = f"{ahu.id} PackagedVAV"
    reheat_fuel = "Gas" if ahu.gas_preheat else "Electric"
    fan_plc = design.get("fan_part_load_coefficients", "InletVaneDampers")
    sat_reset = design.get("sat_reset_type", "WarmestTemperatureFirst")
    return IdfObject(
        "HVACTemplate:System:PackagedVAV",
        [
            sys_name,
            "FanAvailSched",
            "autosize",
            "autosize",
            "DrawThrough",
            design.get("fan_total_efficiency", 0.7),
            design.get("fan_pressure_rise_pa", 600.0),
            design.get("fan_motor_efficiency", 0.9),
            1.0,
            design.get("cooling_coil_type", "TwoSpeedDX"),
            "",
            "SAT Reset Schedule",
            design.get("supply_air_temp_cooling_c", 13.0),
            "autosize",
            "autosize",
            design.get("cooling_cop", 3.2),
            reheat_fuel,
            "",
            "",
            design.get("gas_preheat_setpoint_c", 10.0),
            "autosize",
            design.get("gas_preheat_efficiency", 0.8),
            "",
            "autosize",
            "autosize",
            "ProportionalMinimum",
            "Min OA Sched",
            "DifferentialDryBulb",
            "NoLockout",
            19.0,
            "",
            "",
            4.0,
            "",
            "",
            fan_plc,
            "CycleOnAny",
            "",
            "None",
            0.7,
            0.65,
            sat_reset,
            "None",
            "None",
            "",
            60.0,
            "None",
            "",
            0.000001,
            2690.0,
            "",
            30.0,
            "NonCoincident",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    )


def _zone_vav(vav: VavSpec, ahu: AhuSpec, design: dict) -> IdfObject:
    sys_name = f"{ahu.id} PackagedVAV"
    reheat = "Water" if vav.reheat == "hot_water" else "Electric"
    oa_method = design.get("outdoor_air_method", "Sum")
    min_frac = design.get("vav_min_flow_fraction", 0.2)
    oa_person = design.get("oa_per_person_m3_s", 0.00236)
    oa_area = design.get("oa_per_area_m3_s_m2", 0.000305)
    oa_zone = 0.0
    return IdfObject(
        "HVACTemplate:Zone:VAV",
        [
            vav.zone,
            sys_name,
            "Office Thermostat",
            "autosize",
            "",
            "",
            "Constant",
            min_frac,
            "",
            "",
            oa_method,
            oa_person,
            oa_area,
            oa_zone,
            reheat,
            "",
            "Reverse",
            "",
            "",
            "",
            "",
            "",
            "",
            "None",
            "",
            "autosize",
            "SystemSupplyAirTemperature",
            "",
            "",
            "SupplyAirTemperature",
            design.get("design_heating_supply_c", 50.0),
            "",
        ],
    )