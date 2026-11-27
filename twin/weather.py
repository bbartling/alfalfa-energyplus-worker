"""Nearest weather station from the OpenStudio standards EPW set.

The files are typical meteorological years (TMY3, CWEC, or CZ2010), not the
actual year of the bills. There is no weather service in this image, so the
calibration run and the savings run both use that station's file and say so.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "models" / "weather_stations.json"


@lru_cache(maxsize=1)
def stations() -> tuple[dict, ...]:
    return tuple(json.loads(INDEX.read_text()))


def nearest_station(latitude: float, longitude: float) -> dict:
    return min(stations(), key=lambda station: _km(latitude, longitude, station["latitude"], station["longitude"]))


def station_by_file(name: str) -> dict:
    for station in stations():
        if station["file"] == name:
            return station
    raise KeyError(name)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
