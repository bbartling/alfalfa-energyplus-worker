#!/usr/bin/env python3
"""Build a parameterized two-story office VAV EnergyPlus 24.2 IDF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODELS_ROOT = Path(__file__).resolve().parent
if str(MODELS_ROOT) not in sys.path:
    sys.path.insert(0, str(MODELS_ROOT))

from generic_office.geometry import add_geometry  # noqa: E402
from generic_office.hvac import add_hvac  # noqa: E402
from generic_office.idf_writer import IdfDocument, IdfObject  # noqa: E402
from generic_office.layout import load_layout  # noqa: E402
from generic_office.points import add_output_requests  # noqa: E402
from generic_office.schedules import add_schedules  # noqa: E402

DEFAULT_DESIGN = MODELS_ROOT / "generic_office" / "design_values.json"
DEFAULT_LAYOUT = MODELS_ROOT / "layouts" / "default_two_story_office.json"


def load_design(path: Path | None) -> dict:
    path = path or DEFAULT_DESIGN
    if not path.is_file():
        return {
            "lighting_w_per_m2": 10.8,
            "equipment_w_per_m2": 10.8,
            "people_per_m2": 0.05,
            "window_wall_ratio": 0.35,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_design(base: dict, overrides: dict | None) -> dict:
    merged = dict(base)
    if overrides:
        merged.update(overrides)
    return merged


def add_simulation_header(doc: IdfDocument, layout, design: dict) -> None:
    bld = layout.building
    site_name = design.get("site_name", "Chicago OHare")
    winter_t = design.get("winter_design_db_c", -17.3)
    summer_t = design.get("summer_design_db_c", 33.3)
    doc.add(
        IdfObject(
            "GlobalGeometryRules",
            [
                "UpperLeftCorner",
                "Counterclockwise",
                "World",
            ],
        )
    )
    doc.add(
        IdfObject(
            "Timestep",
            [
                design.get("timesteps_per_hour", 6),
            ],
        )
    )
    run = design.get("run_period") or {}
    doc.add(
        IdfObject(
            "RunPeriod",
            [
                run.get("name", "Annual"),
                run.get("begin_month", 1),
                run.get("begin_day", 1),
                run.get("begin_year", ""),
                run.get("end_month", 12),
                run.get("end_day", 31),
                run.get("end_year", ""),
                "Sunday",
                "Yes",
                "Yes",
                "No",
                "Yes",
                "Yes",
            ],
        )
    )
    sim = design.get("simulation_control") or {}
    if design.get("skip_sizing"):
        sim = {
            "do_zone_sizing": "No",
            "do_system_sizing": "No",
            "do_plant_sizing": "No",
            "run_sizing_periods": "No",
            "run_weather_periods": "Yes",
            **sim,
        }
    defaults = {
        "do_zone_sizing": "Yes",
        "do_system_sizing": "Yes",
        "do_plant_sizing": "Yes",
        "run_sizing_periods": "Yes",
        "run_weather_periods": "Yes",
    }
    merged = {**defaults, **sim}
    doc.add(
        IdfObject(
            "SimulationControl",
            [
                merged["do_zone_sizing"],
                merged["do_system_sizing"],
                merged["do_plant_sizing"],
                merged["run_sizing_periods"],
                merged["run_weather_periods"],
            ],
        )
    )
    doc.add(
        IdfObject(
            "Site:Location",
            [
                site_name,
                design.get("latitude", 41.98),
                design.get("longitude", -87.9),
                design.get("time_zone", -6.0),
                design.get("elevation_m", 201.0),
            ],
        )
    )
    winter_name = f"{site_name} Winter Design Day"
    summer_name = f"{site_name} Summer Design Day"
    doc.add(
        IdfObject(
            "SizingPeriod:DesignDay",
            [
                winter_name,
                1,
                21,
                "WinterDesignDay",
                winter_t,
                0.0,
                "",
                "",
                "Wetbulb",
                winter_t,
                "",
                "",
                "",
                "",
                98934.0,
                4.9,
                270.0,
                "No",
                "No",
                "No",
                "ASHRAEClearSky",
                "",
                "",
                "",
                "",
                0.0,
            ],
        )
    )
    doc.add(
        IdfObject(
            "SizingPeriod:DesignDay",
            [
                summer_name,
                7,
                21,
                "SummerDesignDay",
                summer_t,
                10.0,
                "",
                "",
                "Wetbulb",
                summer_t - 10.5,
                "",
                "",
                "",
                "",
                98934.0,
                5.2,
                230.0,
                "No",
                "No",
                "No",
                "ASHRAEClearSky",
                "",
                "",
                "",
                "",
                1.0,
            ],
        )
    )
    doc.add(
        IdfObject(
            "Building",
            [
                f"Generic Office {bld.floors}F",
                0,
                "City",
                0.04,
                0.004,
                "",
                25,
                6,
            ],
        )
    )


def build_idf(
    layout_path: Path,
    design_path: Path | None,
    out_path: Path,
    *,
    design_overrides: dict | None = None,
) -> Path:
    layout = load_layout(layout_path)
    design = _merge_design(load_design(design_path), design_overrides)
    doc = IdfDocument(version="24.2")
    add_simulation_header(doc, layout, design)
    add_schedules(doc, layout)
    add_geometry(doc, layout, design)
    add_hvac(doc, layout, design)
    add_output_requests(doc, layout)
    doc.write(out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--layout",
        type=Path,
        default=DEFAULT_LAYOUT,
        help="Layout JSON (see generic_office/schema.md)",
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=None,
        help=f"Design overrides JSON (default: {DEFAULT_DESIGN.name})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=MODELS_ROOT / "out" / "generic_two_story_office_vav.idf",
        help="Output IDF path",
    )
    args = parser.parse_args()
    out = build_idf(args.layout, args.design, args.output)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()