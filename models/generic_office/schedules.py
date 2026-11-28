"""Medium-office operating schedules (ASHRAE 90.1-ish weekday profile)."""

from __future__ import annotations

from .idf_writer import IdfDocument, IdfObject
from .layout import Layout


def add_schedules(doc: IdfDocument, layout: Layout) -> None:
    doc.extend(_core_schedules())
    for vav in layout.all_vavs():
        zone = vav.zone
        for kind in ("Occupancy", "Lights", "Equipment"):
            doc.add(
                IdfObject(
                    "Schedule:Compact",
                    [
                        f"{zone} {kind} Schedule",
                        "Any Number",
                        "Through: 12/31",
                        "For: Weekdays",
                        "Until: 06:00",
                        0 if kind == "Occupancy" else 0.05,
                        "Until: 07:00",
                        0.25 if kind == "Occupancy" else 0.3,
                        "Until: 18:00",
                        1.0,
                        "Until: 24:00",
                        0.05,
                        "For: Weekends",
                        "Until: 24:00",
                        0.05,
                "For: Holidays",
                "Until: 24:00",
                0.05,
                "For: AllOtherDays",
                "Until: 24:00",
                0.05,
                    ],
                )
            )
    doc.add(
        IdfObject(
            "Schedule:Constant",
            [
                "Activity Schedule",
                "Any Number",
                131.0,
            ],
        )
    )


def _core_schedules() -> list[IdfObject]:
    return [
        IdfObject(
            "ScheduleTypeLimits",
            [
                "Fraction",
                "0",
                "1",
                "CONTINUOUS",
            ],
        ),
        IdfObject(
            "ScheduleTypeLimits",
            [
                "Temperature",
                -60,
                200,
                "CONTINUOUS",
            ],
        ),
        IdfObject(
            "ScheduleTypeLimits",
            [
                "Any Number",
                -100,
                1000,
                "CONTINUOUS",
            ],
        ),
        IdfObject(
            "Schedule:Compact",
            [
                "Thermostat Heating Setpoint",
                "Temperature",
                "Through: 12/31",
                "For: AllDays",
                "Until: 24:00",
                21.1,
            ],
        ),
        IdfObject(
            "Schedule:Compact",
            [
                "Thermostat Cooling Setpoint",
                "Temperature",
                "Through: 12/31",
                "For: AllDays",
                "Until: 24:00",
                24.0,
            ],
        ),
        IdfObject(
            "Schedule:Compact",
            [
                "AHU Fan Schedule",
                "Fraction",
                "Through: 12/31",
                "For: Weekdays",
                "Until: 06:00",
                0,
                "Until: 19:00",
                1,
                "Until: 24:00",
                0,
                "For: AllOtherDays",
                "Until: 24:00",
                0,
            ],
        ),
        IdfObject(
            "Schedule:Compact",
            [
                "Outdoor Air Schedule",
                "Fraction",
                "Through: 12/31",
                "For: AllDays",
                "Until: 24:00",
                1,
            ],
        ),
        IdfObject(
            "Schedule:Constant",
            [
                "Always On",
                "Fraction",
                1,
            ],
        ),
        IdfObject(
            "Schedule:Constant",
            [
                "Always Off",
                "Fraction",
                0,
            ],
        ),
    ]