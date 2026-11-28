"""Zone footprints and BuildingSurface:Detailed geometry."""

from __future__ import annotations

from dataclasses import dataclass

from .idf_writer import IdfDocument, IdfObject
from .layout import BuildingSpec, Layout, PerimeterLabel, VavSpec


@dataclass(frozen=True)
class Rect2D:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def depth(self) -> float:
        return self.y1 - self.y0

    @property
    def area_m2(self) -> float:
        return self.width * self.depth


def perimeter_depth(building: BuildingSpec) -> float:
    """Strip depth for core/perimeter split (~15 ft default, capped by footprint)."""
    target = 4.5
    return min(
        target,
        building.footprint_length_m * 0.2,
        building.footprint_width_m * 0.2,
    )


def zone_rectangles(building: BuildingSpec) -> dict[PerimeterLabel, Rect2D]:
    """Five-zone core-and-perimeter layout on the ground footprint."""
    length = building.footprint_length_m
    width = building.footprint_width_m
    p = perimeter_depth(building)
    if 2 * p >= length or 2 * p >= width:
        p = min(length, width) * 0.15
    core = Rect2D(p, p, length - p, width - p)
    return {
        "core": core,
        "south": Rect2D(0, 0, length, p),
        "north": Rect2D(0, width - p, length, width),
        "west": Rect2D(0, p, p, width - p),
        "east": Rect2D(length - p, p, length, width - p),
    }


def zone_for_vav(vav: VavSpec, rects: dict[PerimeterLabel, Rect2D]) -> Rect2D:
    label = vav.perimeter or _perimeter_from_zone_name(vav.zone)
    return rects[label]


def _perimeter_from_zone_name(zone: str) -> PerimeterLabel:
    for label in ("north", "east", "south", "west", "core"):
        if zone.endswith(label):
            return label  # type: ignore[return-value]
    return "core"


def zone_volume_ft3(rect: Rect2D, height_m: float) -> float:
    area_m2 = rect.area_m2
    return area_m2 * height_m * 35.3147


def add_geometry(doc: IdfDocument, layout: Layout, design: dict) -> None:
    """Emit zones, surfaces, and internal gains placeholders."""
    building = layout.building
    rects = zone_rectangles(building)
    story_height = building.floor_to_floor_m * float(design.get("story_height_fraction", 0.88))
    wall_height = story_height
    vavs = layout.all_vavs()
    floor_mult = design.get("lighting_w_per_m2", 10.8)
    equip_mult = design.get("equipment_w_per_m2", 10.8)
    people_per_m2 = design.get("people_per_m2", 0.05)

    doc.extend(_envelope_materials(design))

    for vav in vavs:
        rect = zone_for_vav(vav, rects)
        z_elev = (vav.floor - 1) * building.floor_to_floor_m
        zone_name = vav.zone
        doc.add(
            IdfObject(
                "Zone",
                [
                    zone_name,
                    0,
                    0,
                    0,
                    0,
                    1,
                    1,
                    "autocalculate",
                    "autocalculate",
                    vav.floor,
                    z_elev,
                ],
            )
        )
        doc.extend(
            _zone_surfaces(
                zone_name,
                rect,
                z_elev,
                wall_height,
                design,
            )
        )
        area = rect.area_m2
        doc.add(
            IdfObject(
                "Lights",
                [
                    f"{zone_name} Lights",
                    zone_name,
                    f"{zone_name} Lights Schedule",
                    "Watts/Area",
                    "",
                    floor_mult,
                    area,
                    "",
                    0,
                    f"{zone_name} Lights",
                    0.2,
                    0.4,
                    0.2,
                ],
            )
        )
        doc.add(
            IdfObject(
                "ElectricEquipment",
                [
                    f"{zone_name} Equipment",
                    zone_name,
                    f"{zone_name} Equipment Schedule",
                    "Watts/Area",
                    "",
                    equip_mult,
                    area,
                    "",
                    0,
                    f"{zone_name} Equipment",
                    0.3,
                    0.2,
                    0.05,
                ],
            )
        )
        doc.add(
            IdfObject(
                "People",
                [
                    f"{zone_name} People",
                    zone_name,
                    f"{zone_name} Occupancy Schedule",
                    "People",
                    "",
                    people_per_m2 * area,
                    "",
                    "",
                    "Activity Schedule",
                    0.3,
                    "autocalculate",
                ],
            )
        )


def _envelope_materials(design: dict) -> list[IdfObject]:
    # Reserved for future conductivity tuning from design u-values.
    _ = (design.get("wall_u_value"), design.get("roof_u_value"), design.get("floor_u_value"))
    return [
        IdfObject(
            "Material",
            ["Wall Insulation", "MediumRough", 0.1016, 0.16, 1200, 800, 0.9, 0.7, 0.7],
        ),
        IdfObject("Material", ["Wall Gypsum", "Smooth", 0.015875, 0.16, 800, 1090, 0.9, 0.7, 0.7]),
        IdfObject(
            "Construction",
            ["Ext Wall", "Wall Gypsum", "Wall Insulation", "Wall Gypsum"],
        ),
        IdfObject(
            "Construction",
            ["Ext Roof", "Wall Insulation"],
        ),
        IdfObject(
            "Construction",
            ["Ext Floor", "Wall Insulation"],
        ),
        IdfObject(
            "Construction",
            ["Int Partition", "Wall Gypsum", "Wall Gypsum"],
        ),
        IdfObject(
            "WindowMaterial:SimpleGlazingSystem",
            [
                "Simple Glazing",
                2.7,
                0.6,
            ],
        ),
        IdfObject("Construction", ["Window", "Simple Glazing"]),
        # Store target U-factors in comments via unused Global vars in design dict consumer
    ]


def _zone_surfaces(
    zone: str,
    rect: Rect2D,
    z_base: float,
    height: float,
    design: dict,
) -> list[IdfObject]:
    wwr = float(design.get("window_wall_ratio", 0.35))
    objs: list[IdfObject] = []
    faces = [
        ("Floor", "Ground", (rect.x0, rect.y0, rect.x1, rect.y1), "Ext Floor", z_base),
        ("Roof", "Outdoors", (rect.x0, rect.y0, rect.x1, rect.y1), "Ext Roof", z_base),
        (
            "Wall-N",
            "Outdoors",
            (rect.x0, rect.y1, rect.x1, rect.y1),
            "Ext Wall",
            z_base,
            True,
        ),
        (
            "Wall-S",
            "Outdoors",
            (rect.x0, rect.y0, rect.x1, rect.y0),
            "Ext Wall",
            z_base,
            True,
        ),
        (
            "Wall-E",
            "Outdoors",
            (rect.x1, rect.y0, rect.x1, rect.y1),
            "Ext Wall",
            z_base,
            True,
        ),
        (
            "Wall-W",
            "Outdoors",
            (rect.x0, rect.y0, rect.x0, rect.y1),
            "Ext Wall",
            z_base,
            True,
        ),
    ]
    for spec in faces:
        name, boundary, geom, construction = spec[0], spec[1], spec[2], spec[3]
        z0 = spec[4] if len(spec) > 4 else z_base
        is_wall = len(spec) > 5 and spec[5]
        if name == "Floor":
            xy = [(geom[0], geom[1]), (geom[2], geom[1]), (geom[2], geom[3]), (geom[0], geom[3])]
            sur = _detailed_surface(zone, f"{zone} {name}", boundary, xy, z0, 0, construction)
        elif name == "Roof":
            xy = [(geom[0], geom[1]), (geom[2], geom[1]), (geom[2], geom[3]), (geom[0], geom[3])]
            sur = _detailed_surface(zone, f"{zone} {name}", boundary, xy, z0, height, construction)
        else:
            x0, y0, x1, y1 = geom
            sur = _wall_surface(zone, f"{zone} {name}", boundary, x0, y0, x1, y1, z0, height, construction)
        objs.append(sur)
        if is_wall and boundary == "Outdoors" and wwr > 0:
            objs.append(_window_on_wall(f"{zone} {name} Win", zone, f"{zone} {name}", rect, name, z0, height, wwr))
    return objs


def _wall_surface(
    zone: str,
    name: str,
    boundary: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    z_base: float,
    height: float,
    construction: str,
) -> IdfObject:
    z_top = z_base + height
    verts = [(x0, y0, z_base), (x1, y1, z_base), (x1, y1, z_top), (x0, y0, z_top)]
    fields: list[str | float | int | None] = [
        name,
        "Wall",
        construction,
        zone,
        "",
        boundary,
        "SunExposed" if boundary == "Outdoors" else "NoSun",
        "WindExposed" if boundary == "Outdoors" else "NoWind",
        1,
        len(verts),
    ]
    for x, y, z in verts:
        fields.extend([x, y, z])
    return IdfObject("BuildingSurface:Detailed", fields)


def _detailed_surface(
    zone: str,
    name: str,
    boundary: str,
    xy: list[tuple[float, float]],
    z_base: float,
    height: float,
    construction: str,
) -> IdfObject:
    z_top = z_base + height
    if name.endswith("Floor"):
        verts = [(x, y, z_base) for x, y in xy]
    elif name.endswith("Roof"):
        verts = [(x, y, z_top) for x, y in xy]
    else:
        # wall: extrude two corners
        x0, y0 = xy[0]
        x1, y1 = xy[1]
        verts = [(x0, y0, z_base), (x1, y1, z_base), (x1, y1, z_top), (x0, y0, z_top)]
    fields: list[str | float | int | None] = [
        name,
        "Wall" if "Wall" in name else ("Roof" if "Roof" in name else "Floor"),
        construction,
        zone,
        "",
        boundary,
        "SunExposed" if boundary == "Outdoors" else "NoSun",
        "WindExposed" if boundary == "Outdoors" else "NoWind",
        1,
        len(verts),
    ]
    for x, y, z in verts:
        fields.extend([x, y, z])
    return IdfObject("BuildingSurface:Detailed", fields)


def _window_on_wall(
    name: str,
    zone: str,
    wall: str,
    rect: Rect2D,
    wall_tag: str,
    z_base: float,
    height: float,
    wwr: float,
) -> IdfObject:
    sill = z_base + height * 0.25
    head = z_base + height * 0.85
    mid_y_n = (rect.y0 + rect.y1) / 2
    mid_x = (rect.x0 + rect.x1) / 2
    win_h = head - sill
    if "Wall-N" in wall_tag:
        win_w = rect.width * (wwr**0.5)
        x0 = mid_x - win_w / 2
        verts = [(x0, rect.y1, sill), (x0 + win_w, rect.y1, sill), (x0 + win_w, rect.y1, head), (x0, rect.y1, head)]
    elif "Wall-S" in wall_tag:
        win_w = rect.width * (wwr**0.5)
        x0 = mid_x - win_w / 2
        verts = [(x0 + win_w, rect.y0, sill), (x0, rect.y0, sill), (x0, rect.y0, head), (x0 + win_w, rect.y0, head)]
    elif "Wall-E" in wall_tag:
        win_w = rect.depth * (wwr**0.5)
        y0 = mid_y_n - win_w / 2
        verts = [(rect.x1, y0 + win_w, sill), (rect.x1, y0, sill), (rect.x1, y0, head), (rect.x1, y0 + win_w, head)]
    else:
        win_w = rect.depth * (wwr**0.5)
        y0 = mid_y_n - win_w / 2
        verts = [(rect.x0, y0, sill), (rect.x0, y0 + win_w, sill), (rect.x0, y0 + win_w, head), (rect.x0, y0, head)]
    fields: list[str | float | int | None] = [
        name,
        "Window",
        "Window",
        wall,
        "",
        1,
        sill,
        win_h,
        "",
        0.5,
        len(verts),
    ]
    for x, y, z in verts:
        fields.extend([x, y, z])
    return IdfObject("FenestrationSurface:Detailed", fields)