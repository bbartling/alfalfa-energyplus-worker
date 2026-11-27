"""Run EnergyPlus 24.2 from the nrel/openstudio:3.9.0 image.

The worker image sets ENERGYPLUS_BIN and calls the binary directly.
Everywhere else, including CI, the same command runs inside that image.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from twin.eplus_meters import JOULES_PER_KWH
from twin.idfedit import apply_case, load_model
from twin.weather import nearest_station, station_by_file

IMAGE = os.environ.get("TWIN_OPENSTUDIO_IMAGE", "nrel/openstudio:3.9.0")
ENERGYPLUS_BIN = "/usr/local/openstudio-3.9.0/EnergyPlus/energyplus"
WEATHER_DIR = (
    "/var/oscli/gems/ruby/3.2.0/gems/openstudio-standards-0.7.0/data/weather"
)
JOULES_PER_THERM = 105_480_400

def weather_file(latitude: float, longitude: float) -> str:
    """Nearest station file. It is a TMY (or CWEC/CZ2010), not actual-year weather."""
    return nearest_station(latitude, longitude)["file"]


def simulate(case: dict, weather: str, span: str, timeout: int = 3600) -> dict:
    """Run one IDF and return monthly electricity (kWh) and gas (therm)."""
    idf = apply_case(load_model(), case, span, station=station_by_file(weather))
    with TemporaryDirectory(prefix="twin-eplus-") as work:
        root = Path(work)
        (root / "in.idf").write_text(idf)
        (root / "out").mkdir()
        _execute(root, weather, timeout)
        return monthly_energy(root / "out" / "eplusout.sql")


def monthly_energy(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError("EnergyPlus did not write eplusout.sql")
    connection = sqlite3.connect(path)
    try:
        period = connection.execute(
            "SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods WHERE EnvironmentType = 3 "
            "ORDER BY EnvironmentPeriodIndex DESC LIMIT 1"
        ).fetchone()
        if period is None:
            raise RuntimeError("EnergyPlus SQL has no run period")
        return {
            "electric": _monthly(connection, period[0], "Electricity:Facility", "kwh"),
            "gas": _monthly(connection, period[0], "NaturalGas:Facility", "therm"),
        }
    finally:
        connection.close()


def _monthly(connection: sqlite3.Connection, period: int, meter: str, unit: str) -> dict[int, float]:
    rows = connection.execute(
        """
        SELECT t.Month, d.Units, SUM(r.Value)
        FROM ReportData r
        JOIN Time t ON r.TimeIndex = t.TimeIndex
        JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
        WHERE d.Name = ? AND d.ReportingFrequency = 'Hourly'
          AND t.EnvironmentPeriodIndex = ? AND COALESCE(t.WarmupFlag, 0) = 0
        GROUP BY t.Month, d.Units
        """,
        (meter, period),
    ).fetchall()
    totals: dict[int, float] = {}
    for month, units, value in rows:
        totals[int(month)] = totals.get(int(month), 0.0) + _convert(float(value), units, unit)
    return totals


def _convert(value: float, source: str, target: str) -> float:
    unit = (source or "").strip().lower()
    if target == "kwh":
        if unit == "j":
            return value / JOULES_PER_KWH
        return value
    if unit == "j":
        return value / JOULES_PER_THERM
    return value


def _execute(root: Path, weather: str, timeout: int) -> None:
    local_bin = os.environ.get("ENERGYPLUS_BIN", "")
    weather_dir = os.environ.get("ENERGYPLUS_WEATHER_DIR", WEATHER_DIR)
    weather_path = f"{weather_dir.rstrip('/')}/{weather}"
    if local_bin and Path(local_bin).exists():
        command = [local_bin, "-w", weather_path, "-d", str(root / "out"), str(root / "in.idf")]
    else:
        command = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root}:/sim",
            IMAGE,
            ENERGYPLUS_BIN,
            "-w",
            weather_path,
            "-d",
            "/sim/out",
            "/sim/in.idf",
        ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        err = _tail(root / "out" / "eplusout.err") or completed.stderr[-1500:] or completed.stdout[-1500:]
        raise RuntimeError(f"EnergyPlus failed: {err}")


def _tail(path: Path) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-20:])
