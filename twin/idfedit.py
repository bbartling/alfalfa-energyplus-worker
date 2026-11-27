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


def apply_case(objects: list[list[str]], case: dict, span: str) -> str:
    """Map one sweep point and the summary schedule onto a copy of the IDF."""
    edited = [list(obj) for obj in objects]
    heating = case["heating_setpoint_c"] + case["setpoint_offset_c"]
    cooling = case["cooling_setpoint_c"] + case["setpoint_offset_c"]
    if cooling < heating + 1:
        cooling = heating + 1
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
        elif kind == "ZoneInfiltration:DesignFlowRate":
            index = _INFILTRATION_FIELD.get(obj[4] if len(obj) > 4 else "")
            if index is not None and len(obj) > index:
                obj[index] = _scale(obj[index], case["infiltration_multiplier"])
        elif kind == "Schedule:Day:Interval":
            _rewrite_day(obj, case, heating, cooling)
        elif kind == "RunPeriod" and len(obj) > 6:
            begin_month, begin_day, end_month, end_day = _span(span)
            obj[2] = str(begin_month)
            obj[3] = str(begin_day)
            obj[4] = "2006"
            obj[5] = str(end_month)
            obj[6] = str(end_day)
            obj[7] = "2006"
    return write_idf(edited)


_INFILTRATION_FIELD = {
    "Flow/Zone": 5,
    "Flow/Area": 6,
    "Flow/ExteriorArea": 7,
    "Flow/ExteriorWallArea": 7,
    "AirChanges/Hour": 8,
}


def _method(obj: list[str]) -> str:
    return obj[4] if len(obj) > 4 else ""


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


def _rewrite_day(obj: list[str], case: dict, heating: float, cooling: float) -> None:
    name = obj[1] if len(obj) > 1 else ""
    weekend = _weekend(name)
    start = case["occupied_start"]
    end = case["occupied_end"]
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
    pairs = _intervals(start, end, occupied=values[1], unoccupied=values[0], weekend=weekend)
    obj[4:] = [item for pair in pairs for item in (pair[0], _num(pair[1]))]


def _weekend(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("wknd", "weekend", "saturday", "sunday", "holiday"))


def _intervals(start: str, end: str, occupied: float, unoccupied: float, weekend: bool) -> list[tuple[str, float]]:
    if weekend or start >= end:
        return [("24:00", unoccupied)]
    if start in {"00:00", "0:00"}:
        if end in {"24:00", "00:00"}:
            return [("24:00", occupied)]
        return [(end, occupied), ("24:00", unoccupied)]
    return [(start, unoccupied), (end, occupied), ("24:00", unoccupied)]
