"""VAV air loops, terminals, sizing, and controls."""

from __future__ import annotations

from .geometry import zone_for_vav, zone_rectangles
from .idf_writer import IdfDocument, IdfObject
from .layout import AhuSpec, Layout, VavSpec


def add_hvac(
    doc: IdfDocument,
    layout: Layout,
    design: dict,
) -> None:
    building = layout.building
    rects = zone_rectangles(building)
    doc.extend(_shared_hvac_objects(design))
    for ahu in layout.ahus:
        doc.extend(_air_loop(doc, layout, ahu, design, rects))
    doc.extend(_thermostats(layout))


def _shared_hvac_objects(design: dict) -> list[IdfObject]:
    sat_min = design.get("supply_air_temp_min_c", 12.8)
    sat_max = design.get("supply_air_temp_max_c", 15.6)
    sp_min = design.get("duct_static_pressure_min_pa", 250.0)
    sp_max = design.get("duct_static_pressure_max_pa", 450.0)
    return [
        IdfObject(
            "DesignSpecification:OutdoorAir",
            [
                "Office OA Spec",
                "Sum",
                "People",
                0.00236,
                "Area",
                0.000305,
                0,
                "",
                "Min OA Sched",
            ],
        ),
        IdfObject(
            "Schedule:Constant",
            [
                "Min OA Sched",
                "Fraction",
                1,
            ],
        ),
        IdfObject(
            "SetpointManager:Scheduled",
            [
                "SAT Reset Manager Placeholder",
                "Temperature",
                "Always On",
                "SAT Reset Schedule",
            ],
        ),
        IdfObject(
            "Schedule:Compact",
            [
                "SAT Reset Schedule",
                "Temperature",
                "Through: 12/31",
                "For: AllDays",
                "Until: 24:00",
                13.0,
            ],
        ),
        IdfObject(
            "SetpointManager:Warmest",
            [
                "SAT Warmest Reset",
                "Temperature",
                "Always On",
                sat_min,
                sat_max,
                "MaximumTemperature",
                f"{sat_min}",
            ],
        ),
        IdfObject(
            "SetpointManager:StaticPressure",
            [
                "Duct Static Reset",
                "Always On",
                sp_min,
                sp_max,
                "MinimumPressure",
                f"{sp_min}",
            ],
        ),
    ]


def _air_loop(
    doc: IdfDocument,
    layout: Layout,
    ahu: AhuSpec,
    design: dict,
    rects: dict,
) -> list[IdfObject]:
    objs: list[IdfObject] = []
    loop_name = f"{ahu.id} AirLoop"
    oa_name = f"{ahu.id} OA System"
    fan_name = f"{ahu.id} Supply Fan"
    dx_name = f"{ahu.id} DX Cooling"
    preheat_name = f"{ahu.id} Gas Preheat"
    hx_name = f"{ahu.id} OA Mixer"
    branch_name = f"{ahu.id} Main Branch"
    sat_node = f"{loop_name} SAT"
    mixed_node = f"{ahu.id} Mixed Air"
    oa_node = f"{ahu.id} OA Inlet"
    relief_node = f"{ahu.id} Relief"
    supply_out = f"{ahu.id} Supply Outlet"
    sp_node = f"{ahu.id} SP Sensor"

    objs.append(
        IdfObject(
            "AirLoopHVAC",
            [
                loop_name,
                "",
                fan_name,
                branch_name,
                supply_out,
                branch_name,
                "Always On",
                1.0,
            ],
        )
    )
    objs.extend(_sizing_system(loop_name, ahu, layout, design))

    objs.append(
        IdfObject(
            "AirLoopHVAC:OutdoorAirSystem",
            [
                oa_name,
                f"{ahu.id} OA Manager",
                "Dummy Heat Recovery Spec",
                f"{ahu.id} OA Controller",
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:ControllerList",
            [
                f"{ahu.id} OA Manager",
                "Controller:OutdoorAir",
                f"{ahu.id} OA Controller",
            ],
        )
    )
    objs.append(
        IdfObject(
            "OutdoorAir:Mixer",
            [
                hx_name,
                mixed_node,
                oa_node,
                relief_node,
                fan_name + " Inlet",
            ],
        )
    )
    objs.append(
        IdfObject(
            "Controller:OutdoorAir",
            [
                f"{ahu.id} OA Controller",
                f"{ahu.id} OA Node",
                oa_node,
                relief_node,
                "",
                f"{ahu.id} OA Mass Flow",
                "NoLockout",
                "NoEconomizerLockout",
                "MinimumFlowWithBypass",
                280.0,
                "EconomizerLockout",
                "DifferentialDryBulb",
                5.0,
                100000,
                28.0,
                0,
                4.0,
                1.0,
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:SupplyPath",
            [
                f"{ahu.id} Supply Path",
                supply_out,
                f"{ahu.id} Supply Path Inlet",
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:ZoneSplitter",
            [
                f"{ahu.id} Zone Splitter",
                f"{ahu.id} Supply Path Inlet",
                *[f"{v.id} Damper Inlet" for v in ahu.vavs],
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:ReturnPath",
            [
                f"{ahu.id} Return Path",
                f"{ahu.id} Return Air",
                f"{ahu.id} Return Path Outlet",
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:ZoneMixer",
            [
                f"{ahu.id} Zone Mixer",
                *[f"{v.zone} Return" for v in ahu.vavs],
                f"{ahu.id} Return Path Outlet",
            ],
        )
    )
    objs.append(
        IdfObject(
            "AirLoopHVAC:ReturnPlenum",
            [
                f"{ahu.id} Return Plenum",
                f"{ahu.id} Return Path Outlet",
                f"{ahu.id} Return Plenum Outlet",
            ],
        )
    )

    objs.extend(_main_branch(branch_name, fan_name, dx_name, preheat_name, ahu, mixed_node, sat_node, supply_out, sp_node, design))
    objs.extend(_fan(fan_name, sat_node, mixed_node, design))
    objs.extend(_dx_coil(dx_name, sat_node, fan_name + " Outlet", design))
    if ahu.gas_preheat:
        objs.extend(_gas_preheat(preheat_name, fan_name + " Inlet", mixed_node, design))

    objs.append(
        IdfObject(
            "SetpointManager:Warmest",
            [
                f"{ahu.id} SAT Reset",
                "Temperature",
                "Always On",
                design.get("supply_air_temp_min_c", 12.8),
                design.get("supply_air_temp_max_c", 15.6),
                "MaximumTemperature",
                sat_node,
            ],
        )
    )
    objs.append(
        IdfObject(
            "SetpointManager:StaticPressure",
            [
                f"{ahu.id} Static Reset",
                "Always On",
                design.get("duct_static_pressure_min_pa", 250.0),
                design.get("duct_static_pressure_max_pa", 450.0),
                "MinimumPressure",
                sp_node,
            ],
        )
    )
    objs.append(
        IdfObject(
            "SetpointManager:Scheduled",
            [
                f"{ahu.id} OA Fraction SP",
                "Fraction",
                "Outdoor Air Schedule",
                supply_out,
            ],
        )
    )

    for vav in ahu.vavs:
        objs.extend(_zone_sizing(vav, zone_for_vav(vav, rects)))
        objs.extend(_terminal_units(ahu, vav, loop_name, supply_out, design))
        objs.extend(
            _zone_equipment_connections(vav, f"{vav.id} ATU", f"{vav.id} Damper Inlet", f"{vav.zone} Return")
        )

    return objs


def _main_branch(
    branch_name: str,
    fan_name: str,
    dx_name: str,
    preheat_name: str,
    ahu: AhuSpec,
    mixed_node: str,
    sat_node: str,
    supply_out: str,
    sp_node: str,
    design: dict,
) -> list[IdfObject]:
    branch = IdfObject(
        "Branch",
        [
            branch_name,
            "",
            "Fan:VariableVolume",
            fan_name,
            fan_name + " Inlet",
            fan_name + " Outlet",
            "Coil:Cooling:DX:SingleSpeed",
            dx_name,
            sat_node,
            dx_name + " Outlet",
        ],
    )
    if ahu.gas_preheat:
        branch = IdfObject(
            "Branch",
            [
                branch_name,
                "",
                "Coil:Heating:Fuel",
                preheat_name,
                preheat_name + " Inlet",
                preheat_name + " Out",
                "Fan:VariableVolume",
                fan_name,
                fan_name + " Inlet",
                fan_name + " Outlet",
                "Coil:Cooling:DX:SingleSpeed",
                dx_name,
                sat_node,
                dx_name + " Outlet",
            ],
        )
    return [
        branch,
        IdfObject(
            "BranchList",
            [
                f"{ahu.id} Supply Branches",
                branch_name,
            ],
        ),
        IdfObject(
            "Connector:Splitter",
            [
                f"{ahu.id} Supply Splitter",
                branch_name,
                supply_out,
            ],
        ),
        IdfObject(
            "NodeList",
            [
                f"{ahu.id} Supply Nodes",
                supply_out,
                sp_node,
            ],
        ),
    ]


def _fan(name: str, inlet: str, outlet_from: str, design: dict) -> list[IdfObject]:
    pressure_rise = design.get("fan_pressure_rise_pa", 600.0)
    return [
        IdfObject(
            "Fan:VariableVolume",
            [
                name,
                "Always On",
                0.7,
                pressure_rise,
                1.0,
                0.86,
                0.9,
                0.001,
                name + " Inlet",
                name + " Outlet",
                "General",
                "",
                pressure_rise,
                0.25,
                "",
                design.get("fan_max_flow_m3_s", 5.0),
                "Fan Power Variable Volume",
                0.0,
                1.0,
                0.35071223,
                0.3085052,
                1.0,
                1.0,
                "Dimensionless",
            ],
        ),
    ]


def _dx_coil(name: str, inlet: str, outlet: str, design: dict) -> list[IdfObject]:
    cop = design.get("cooling_cop", 3.2)
    return [
        IdfObject(
            "Coil:Cooling:DX:SingleSpeed",
            [
                name,
                "Always On",
                design.get("cooling_capacity_w", 35000.0),
                design.get("cooling_sensible_heat_ratio", 0.75),
                design.get("cooling_supply_air_flow_m3_s", 1.5),
                inlet,
                outlet,
                "",
                "",
                "TwoStageCompressor",
                "",
                "",
                "",
                cop,
                "",
                "",
                "",
                design.get("cooling_rated_shr", 0.75),
                "",
                "",
                "",
                "",
                "",
                773.3,
                4763.0,
                0.95,
                0.95,
                0.95,
                0.95,
                "X22-117216-11-001",
            ],
        ),
    ]


def _gas_preheat(name: str, inlet: str, outlet: str, design: dict) -> list[IdfObject]:
    return [
        IdfObject(
            "Coil:Heating:Fuel",
            [
                name,
                "Always On",
                design.get("gas_preheat_capacity_w", 20000.0),
                design.get("gas_preheat_efficiency", 0.8),
                inlet,
                outlet,
            ],
        ),
    ]


def _terminal_units(
    ahu: AhuSpec,
    vav: VavSpec,
    loop_name: str,
    supply_node: str,
    design: dict,
) -> list[IdfObject]:
    atu = f"{vav.id} ATU"
    damper_in = f"{vav.id} Damper Inlet"
    reheat_in = f"{vav.id} Reheat Inlet"
    zone_in = f"{vav.zone} Inlet"
    max_flow = design.get("vav_max_flow_m3_s", 0.35)
    min_flow = design.get("vav_min_flow_fraction", 0.2) * max_flow

    reheat_fields: list[str | float | int | None]
    if vav.reheat == "hot_water":
        coil = f"{vav.id} HW Reheat"
        reheat_fields = [
            "Coil:Heating:Water",
            coil,
            max_flow,
            "Always On",
            design.get("reheat_capacity_w", 8000.0),
            0.0011,
            reheat_in,
            zone_in,
            0.0011,
            82.2,
            60.0,
            "General",
        ]
    else:
        coil = f"{vav.id} Elec Reheat"
        reheat_fields = [
            "Coil:Heating:Electric",
            coil,
            "Always On",
            design.get("reheat_capacity_w", 8000.0),
            1.0,
            reheat_in,
            zone_in,
            1.0,
        ]

    objs: list[IdfObject] = [
        IdfObject(
            "ZoneHVAC:AirDistributionUnit",
            [
                atu,
                f"{vav.id} ADU Outlet",
                "AirTerminal:SingleDuct:VAV:Reheat",
                atu,
            ],
        ),
        IdfObject(
            "AirTerminal:SingleDuct:VAV:Reheat",
            [
                atu,
                "Always On",
                damper_in,
                zone_in,
                max_flow,
                "Constant",
                min_flow,
                0.0,
                *reheat_fields,
                design.get("reheat_max_flow_fraction", 1.0),
                design.get("reheat_max_flow_fraction", 1.0),
            ],
        ),
        IdfObject(
            "ZoneHVAC:EquipmentConnections",
            [
                vav.zone,
                f"{vav.zone} Eq",
                1,
                atu,
                0,
                vav.zone + " Inlet Node List",
                vav.zone + " Exhaust Node List",
                f"{vav.zone} Air Node",
                f"{vav.zone} Return",
            ],
        ),
        IdfObject(
            "NodeList",
            [
                vav.zone + " Inlet Node List",
                zone_in,
            ],
        ),
        IdfObject("NodeList", [vav.zone + " Exhaust Node List"]),
    ]
    return objs


def _zone_equipment_connections(vav: VavSpec, atu: str, damper_in: str, return_node: str) -> list[IdfObject]:
    return [
        IdfObject(
            "ZoneControl:Thermostat",
            [
                f"{vav.zone} Thermostat",
                vav.zone,
                "Always On",
                "ThermostatSetpoint:DualSetpoint",
                f"{vav.zone} Dual SP",
            ],
        ),
        IdfObject(
            "ThermostatSetpoint:DualSetpoint",
            [
                f"{vav.zone} Dual SP",
                "Thermostat Heating Setpoint",
                "Thermostat Cooling Setpoint",
            ],
        ),
    ]


def _thermostats(layout: Layout) -> list[IdfObject]:
    return []


def _sizing_system(loop_name: str, ahu: AhuSpec, layout: Layout, design: dict) -> list[IdfObject]:
    return [
        IdfObject(
            "Sizing:System",
            [
                loop_name,
                "SupplyAirTemperature",
                design.get("design_heating_supply_c", 16.0),
                design.get("design_cooling_supply_c", 13.0),
                "Yes",
                "Yes",
                "Coincident",
                "Sensible",
                "Yes",
                0.0085,
                0.008,
                "DesignDay",
                0.0,
                "No",
                0.2,
                0.25,
                0.3,
                0.2,
                0.4,
                ahu.id,
                "Office OA Spec",
                "CoolingDesignCapacity",
                "Autosize",
                "HeatingDesignCapacity",
                "Autosize",
                "None",
                "No",
                "No",
                1.0,
                0.0,
                0.0,
                "None",
                1,
            ],
        ),
    ]


def _zone_sizing(vav: VavSpec, rect) -> list[IdfObject]:
    area = rect.area_m2
    return [
        IdfObject(
            "DesignSpecification:OutdoorAir",
            [
                f"{vav.zone} OA",
                "Sum",
                "People",
                0.00236,
                "Area",
                0.000305,
                0,
                "",
                "Min OA Sched",
            ],
        ),
        IdfObject(
            "Sizing:Zone",
            [
                vav.zone,
                "SupplyAirTemperature",
                13.0,
                16.0,
                "No",
                "No",
                "No",
                0.0085,
                area,
                "DesignDay",
                0.0,
                0.0,
                "No",
                1.0,
                1.0,
                1.0,
                1.0,
                "Office OA Spec",
                f"{vav.zone} OA",
                "No",
                "",
                "UseMDH",
                45.0,
                21.1,
                "SupplyAirTemperature",
                16.0,
                13.0,
                "No",
                "No",
                "No",
                0.0,
                0.0,
                "Yes",
            ],
        ),
        IdfObject(
            "ZoneHVAC:EquipmentList",
            [
                f"{vav.zone} Eq",
                "SequentialLoad",
                1,
                "ZoneHVAC:AirDistributionUnit",
                f"{vav.id} ATU",
                1,
                1,
            ],
        ),
    ]