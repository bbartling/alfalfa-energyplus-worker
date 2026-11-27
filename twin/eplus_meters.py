"""Read whole-building electricity from an EnergyPlus meter CSV.

EnergyPlus writes hourly facility electricity in joules. Guideline 14 is
computed from that series after converting joules to kWh. Alfalfa's exposed
meter points are not used.
"""

from __future__ import annotations

import csv
from pathlib import Path

JOULES_PER_KWH = 3_600_000


def hourly_kwh(path: str | Path) -> list[float]:
    with Path(path).open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        column = _electric_column(header)
        unit = "j" if "[j]" in header[column].lower() else "kwh"
        values: list[float] = []
        for row in reader:
            if not row or len(row) <= column or not row[column].strip():
                continue
            amount = float(row[column])
            if unit == "j":
                amount /= JOULES_PER_KWH
            values.append(amount)
    if not values:
        raise ValueError("EnergyPlus meter file has no electricity rows")
    return values


def _electric_column(header: list[str]) -> int:
    for index, name in enumerate(header):
        lowered = name.lower()
        if "electricity:facility" in lowered or "electricity facility" in lowered:
            return index
    raise ValueError("EnergyPlus meter file has no Electricity:Facility column")
