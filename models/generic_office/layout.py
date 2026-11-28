"""Load and validate office layout JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ReheatType = Literal["electric", "hot_water"]
PerimeterLabel = Literal["north", "east", "south", "west", "core"]


@dataclass(frozen=True)
class ClimateSpec:
    ashrae_climate_zone: str
    weather_file: str


@dataclass(frozen=True)
class BuildingSpec:
    floors: int
    footprint_length_m: float
    footprint_width_m: float
    floor_to_floor_m: float
    total_area_m2: float | None = None

    @property
    def footprint_area_m2(self) -> float:
        return self.footprint_length_m * self.footprint_width_m


@dataclass(frozen=True)
class VavSpec:
    id: str
    zone: str
    floor: int
    reheat: ReheatType = "electric"
    perimeter: PerimeterLabel | None = None


@dataclass(frozen=True)
class AhuSpec:
    id: str
    floor: int
    vavs: list[VavSpec] = field(default_factory=list)
    gas_preheat: bool = False


@dataclass
class Layout:
    schema_version: str
    climate: ClimateSpec
    building: BuildingSpec
    ahus: list[AhuSpec] = field(default_factory=list)

    def all_vavs(self) -> list[VavSpec]:
        return [v for ahu in self.ahus for v in ahu.vavs]

    def vavs_on_floor(self, floor: int) -> list[VavSpec]:
        return [v for v in self.all_vavs() if v.floor == floor]


def load_layout(path: Path | str) -> Layout:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return layout_from_dict(raw)


def layout_from_dict(raw: dict[str, Any]) -> Layout:
    version = raw.get("schema_version", "1.0")
    climate_raw = raw["climate"]
    bld_raw = raw["building"]
    building = BuildingSpec(
        floors=int(bld_raw["floors"]),
        footprint_length_m=float(bld_raw["footprint_length_m"]),
        footprint_width_m=float(bld_raw["footprint_width_m"]),
        floor_to_floor_m=float(bld_raw["floor_to_floor_m"]),
        total_area_m2=bld_raw.get("total_area_m2"),
    )
    climate = ClimateSpec(
        ashrae_climate_zone=str(climate_raw["ashrae_climate_zone"]),
        weather_file=str(climate_raw["weather_file"]),
    )
    ahus: list[AhuSpec] = []
    for ahu_raw in raw.get("ahus") or []:
        vavs = [
            VavSpec(
                id=str(v["id"]),
                zone=str(v["zone"]),
                floor=int(v["floor"]),
                reheat=v.get("reheat", "electric"),
                perimeter=v.get("perimeter"),
            )
            for v in ahu_raw.get("vavs", [])
        ]
        ahus.append(
            AhuSpec(
                id=str(ahu_raw["id"]),
                floor=int(ahu_raw.get("floor", vavs[0].floor if vavs else 1)),
                vavs=vavs,
                gas_preheat=bool(ahu_raw.get("gas_preheat", False)),
            )
        )
    if not ahus:
        ahus = default_ahus(building.floors)
    return Layout(schema_version=version, climate=climate, building=building, ahus=ahus)


def default_ahus(floors: int) -> list[AhuSpec]:
    """Two AHUs (one per floor), five VAVs each (4 perimeter + 1 core)."""
    perimeters: list[tuple[str, PerimeterLabel]] = [
        ("north", "north"),
        ("east", "east"),
        ("south", "south"),
        ("west", "west"),
    ]
    out: list[AhuSpec] = []
    for floor in range(1, floors + 1):
        vavs = [
            VavSpec(
                id=f"vav-f{floor}-core",
                zone=f"zone-f{floor}-core",
                floor=floor,
                reheat="electric",
                perimeter="core",
            )
        ]
        for label, perimeter in perimeters:
            vavs.append(
                VavSpec(
                    id=f"vav-f{floor}-{label}",
                    zone=f"zone-f{floor}-{label}",
                    floor=floor,
                    reheat="electric",
                    perimeter=perimeter,
                )
            )
        out.append(AhuSpec(id=f"ahu-{floor}", floor=floor, vavs=vavs))
    return out