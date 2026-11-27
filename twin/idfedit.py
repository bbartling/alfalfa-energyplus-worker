"""Edit the checked-in DOE SmallOffice IDF without an OpenStudio measure.

Field order is the EnergyPlus contract. Comments are dropped on write.
Empty fields are kept so later fields do not shift.
"""

from __future__ import annotations

from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "doe_small_office_90_1_2013.idf"
MODEL_AREA_M2 = 511.1574
MODEL_NAME = "DOE SmallOffice 90.1-2013"

REFERENCE = {
    "lighting_w_m2": 8.82640654170197,
    "plug_w_m2": 6.78126356252712,
    "fan_efficiency": 0.55575,
    "cooling_cop": 3.8248,
    "infiltration_multiplier": 1.0,
}


def parse_idf(text: str) -> list[list[str]]:
    objects: list[list[str]] = []
    for chunk in text.split(";"):
        fields: list[str] = []
        for line in chunk.splitlines():
            code = line.split("!", 1)[0].strip()
            if not code:
                continue
            if code.endswith(","):
                code = code[:-1].strip()
            fields.append(code)
        if fields:
            objects.append(fields)
    return objects


def write_idf(objects: list[list[str]]) -> str:
    blocks: list[str] = []
    for obj in objects:
        lines = [f"{obj[0]},"]
        body = obj[1:]
        if not body:
            lines = [f"{obj[0]};"]
        else:
            for field in body[:-1]:
                lines.append(f"  {field},")
            lines.append(f"  {body[-1]};")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def load_model() -> list[list[str]]:
    return parse_idf(MODEL_PATH.read_text())


def apply_case(objects: list[list[str]], case: dict, span: str, station: dict | None = None) -> str:
    """Map one sweep point and the summary schedule onto a copy of the IDF."""
    edited = [list(obj) for obj in objects if obj[0] != "RunPeriodControl:DaylightSavingTime"]
    heating = case["heating_setpoint_c"] + case["setpoint_offset_c"]
    cooling = case["cooling_setpoint_c"] + case["setpoint_offset_c"]
    if cooling < heating + 1:
        cooling = heating + 1
    _split_shared_days(edited)
    roles = _day_roles(edited)
    for obj in edited:
        kind = obj[0]
        if kind == "Lights" and _method(obj) == "Watts/Area" and len(obj) > 6:
            obj[6] = _num(case["lighting_w_m2"])
        elif kind == "ElectricEquipment" and _method(obj) == "Watts/Area" and len(obj) > 6:
            obj[6] = _num(case["plug_w_m2"])
        elif kind == "Fan:OnOff" and len(obj) > 3:
            obj[3] = _num(case["fan_efficiency"])
        elif kind == "Coil:Cooling:DX:SingleSpeed" and len(obj) > 5:
            obj[5] = _num(case["cooling_cop"])
        elif kind == "Coil:Heating:DX:SingleSpeed" and case.get("heating_fuel", "heat_pump") == "heat_pump":
            if "heating_cop" in case and len(obj) > 4:
                obj[4] = _num(case["heating_cop"])
        elif kind == "Coil:Heating:DX:SingleSpeed" and case.get("heating_fuel") in {"gas", "electric"}:
            _replace_field(obj, "-12.2", "99")
        elif kind == "Coil:Heating:Fuel" and case.get("heating_fuel") == "electric" and len(obj) > 3:
            obj[3] = "Electricity"
        elif kind == "Coil:Heating:Fuel" and "heating_efficiency" in case and len(obj) > 4:
            obj[4] = _num(case["heating_efficiency"])
        elif kind == "AirLoopHVAC:UnitarySystem" and case.get("heating_fuel") in {"gas", "electric"}:
            _replace_field(obj, "4.44444444444446", "50")
        elif kind == "ZoneInfiltration:DesignFlowRate":
            index = _INFILTRATION_FIELD.get(obj[4] if len(obj) > 4 else "")
            if index is not None and len(obj) > index:
                obj[index] = _scale(obj[index], case["infiltration_multiplier"])
        elif kind == "Schedule:Day:Interval":
            _rewrite_day(obj, case, heating, cooling, roles)
        elif kind == "RunPeriod" and len(obj) > 6:
            begin_month, begin_day, end_month, end_day = _span(span)
            obj[2] = str(begin_month)
            obj[3] = str(begin_day)
            obj[4] = "2006"
            obj[5] = str(end_month)
            obj[6] = str(end_day)
            obj[7] = "2006"
    if station is not None:
        _apply_station(edited, station)
    return write_idf(edited)


_INFILTRATION_FIELD = {
    "Flow/Zone": 5,
    "Flow/Area": 6,
    "Flow/ExteriorArea": 7,
    "Flow/ExteriorWallArea": 7,
    "AirChanges/Hour": 8,
}


def _apply_station(objects: list[list[str]], station: dict) -> None:
    """Point location and design days at the selected station. The file stays a TMY."""
    objects[:] = [obj for obj in objects if obj[0] != "SizingPeriod:DesignDay"]
    for obj in objects:
        if obj[0] == "Site:Location" and len(obj) > 5:
            obj[1] = station["city"]
            obj[2] = _num(station["latitude"])
            obj[3] = _num(station["longitude"])
            obj[4] = _num(station["time_zone"])
            obj[5] = _num(station["elevation_m"])
    for day in station.get("design_days") or []:
        objects.append(list(day))


def _method(obj: list[str]) -> str:
    return obj[4] if len(obj) > 4 else ""


def _replace_field(obj: list[str], old: str, new: str) -> None:
    for index, field in enumerate(obj):
        if field == old:
            obj[index] = new


def _num(value: float) -> str:
    return f"{float(value):.6g}"


def _scale(raw: str, factor: float) -> str:
    try:
        return _num(float(raw) * factor)
    except ValueError:
        return raw


def _span(span: str) -> tuple[int, int, int, int]:
    if span == "smoke":
        return (1, 1, 1, 3)
    return (1, 1, 12, 31)


# Schedule:Week:Daily field index -> day type. OpenStudio writes this, not Schedule:Rule.
# EnergyPlus 24.2's IDD has no Schedule:Ruleset object. Design days are left unchanged.
_WEEK_ROLE = {
    2: "sunday",
    3: "monday",
    4: "tuesday",
    5: "wednesday",
    6: "thursday",
    7: "friday",
    8: "saturday",
    9: "holiday",
    10: "summerdesignday",
    11: "winterdesignday",
    12: "customday1",
    13: "customday2",
}
_WEEKDAY = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_UNOCCUPIED = {"sunday", "saturday", "holiday", "customday1", "customday2"}
_DESIGN = {"summerdesignday", "winterdesignday"}


def _split_shared_days(objects: list[list[str]]) -> None:
    """Give a day profile that is both a weekday and a weekend its own weekend copy."""
    roles = _day_roles(objects)
    clones: list[list[str]] = []
    for name, used in roles.items():
        ordinary = used - _DESIGN
        if not (ordinary & _WEEKDAY and ordinary & _UNOCCUPIED):
            continue
        source = next(
            (obj for obj in objects if obj[0] == "Schedule:Day:Interval" and len(obj) > 1 and obj[1].strip() == name),
            None,
        )
        if source is None:
            continue
        clone_name = f"{name} Weekend"
        clone = list(source)
        clone[1] = clone_name
        clones.append(clone)
        for obj in objects:
            if obj[0] != "Schedule:Week:Daily":
                continue
            for index, role in _WEEK_ROLE.items():
                if role in _UNOCCUPIED and len(obj) > index and obj[index].strip() == name:
                    obj[index] = clone_name
    objects.extend(clones)


def _day_roles(objects: list[list[str]]) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {}
    for obj in objects:
        if obj[0] != "Schedule:Week:Daily":
            continue
        for index, role in _WEEK_ROLE.items():
            if len(obj) > index and obj[index].strip():
                roles.setdefault(obj[index].strip(), set()).add(role)
    return roles


def _rewrite_day(obj: list[str], case: dict, heating: float, cooling: float, roles: dict[str, set[str]]) -> None:
    name = obj[1].strip() if len(obj) > 1 else ""
    used = roles.get(name, set())
    ordinary = used - _DESIGN
    if not ordinary:
        return
    weekend = ordinary.isdisjoint(_WEEKDAY) and bool(ordinary & _UNOCCUPIED)
    if "HTGSETP" in name:
        values = (case["unoccupied_heating_c"], heating)
    elif "CLGSETP" in name:
        values = (case["unoccupied_cooling_c"], cooling)
    elif "BLDG_LIGHT" in name:
        values = (0.08, 0.9)
    elif "BLDG_EQUIP" in name:
        values = (0.05, 0.8)
    elif "BLDG_OCC" in name:
        values = (0.0, 1.0)
    else:
        return
    mask = None
    if weekend and case.get("weekend_hours"):
        mask = case["weekend_hours"]
    elif not weekend and case.get("weekday_hours"):
        mask = case["weekday_hours"]
    if mask is not None:
        pairs = _intervals_from_mask(mask, occupied=values[1], unoccupied=values[0])
    else:
        pairs = _intervals(case["occupied_start"], case["occupied_end"], occupied=values[1], unoccupied=values[0], weekend=weekend)
    obj[4:] = [item for pair in pairs for item in (pair[0], _num(pair[1]))]


def _intervals(start: str, end: str, occupied: float, unoccupied: float, weekend: bool) -> list[tuple[str, float]]:
    if weekend or start >= end:
        return [("24:00", unoccupied)]
    if start in {"00:00", "0:00"}:
        if end in {"24:00", "00:00"}:
            return [("24:00", occupied)]
        return [(end, occupied), ("24:00", unoccupied)]
    return [(start, unoccupied), (end, occupied), ("24:00", unoccupied)]


def _intervals_from_mask(mask: list[bool], occupied: float, unoccupied: float) -> list[tuple[str, float]]:
    if len(mask) != 24:
        raise ValueError("hour mask must cover 24 hours")
    pairs: list[tuple[str, float]] = []
    value = occupied if mask[0] else unoccupied
    for hour in range(1, 24):
        nxt = occupied if mask[hour] else unoccupied
        if nxt != value:
            pairs.append((f"{hour:02d}:00", value))
            value = nxt
    pairs.append(("24:00", value))
    return pairs
