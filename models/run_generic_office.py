#!/usr/bin/env python3
"""Regenerate layout, IDF, run EnergyPlus, and export sizing / time-series artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODELS_ROOT = Path(__file__).resolve().parent
if str(MODELS_ROOT) not in sys.path:
    sys.path.insert(0, str(MODELS_ROOT))

from build_generic_office_vav import DEFAULT_DESIGN, DEFAULT_LAYOUT, build_idf  # noqa: E402, I001
from generic_office.extract_sizing import extract_all, export_timeseries_week, sizing_markdown  # noqa: E402, I001
from generic_office.layout import load_layout  # noqa: E402, I001
from generic_office.points import export_point_list  # noqa: E402, I001
from generic_office.timeseries import minute_week_design_overrides  # noqa: E402, I001
from rdf_to_layout import ttl_to_layout  # noqa: E402, I001


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ttl", type=Path, help="Optional RDF/Turtle source")
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--out-dir", type=Path, default=MODELS_ROOT / "generated")
    parser.add_argument("--weather", type=Path, help="EPW override")
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument(
        "--timeseries-minute",
        action="store_true",
        help="After the annual run, simulate Jan 6–12 at 60 timesteps/hour (1-minute) and export zone-timestep CSV",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    layout_path = args.layout
    if args.ttl:
        layout_doc = ttl_to_layout(
            args.ttl.read_text(encoding="utf-8"),
            "4A",
            "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
        )
        layout_path = args.out_dir / "layout.json"
        layout_path.write_text(json.dumps(layout_doc, indent=2) + "\n", encoding="utf-8")

    layout = load_layout(layout_path)
    design_path = args.design if args.design.is_file() else None
    idf_path = args.out_dir / "generic_two_story_office_vav.idf"
    build_idf(layout_path, design_path, idf_path)
    export_point_list(layout, args.out_dir / "point_list.csv")

    run_dir = args.out_dir / "ep-run"
    if args.skip_run:
        print(f"built {idf_path}")
        return

    epw = args.weather or _default_weather(layout.climate.weather_file)
    ep_bin = os.environ.get("ENERGYPLUS_BIN", _discover_energyplus())
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(idf_path, run_dir / "in.idf")
    subprocess.run(
        [ep_bin, "-x", "-w", str(epw), "-d", str(run_dir), "-r", str(idf_path)],
        check=True,
    )
    layout_json = json.loads(layout_path.read_text(encoding="utf-8"))
    design_values = extract_all(run_dir, layout_json, args.out_dir / "design_values.json")
    (args.out_dir / "sizing_summary.md").write_text(sizing_markdown(design_values), encoding="utf-8")
    hourly_rows = export_timeseries_week(
        run_dir,
        layout_json,
        args.out_dir / "timeseries_representative_week.csv",
        resolution="hourly",
    )
    print(f"hourly representative week: {hourly_rows} rows")

    if args.timeseries_minute:
        _run_minute_week_timeseries(
            layout_path=layout_path,
            layout_json=layout_json,
            design_path=design_path,
            out_dir=args.out_dir,
            epw=epw,
            ep_bin=ep_bin,
        )

    print(f"artifacts in {args.out_dir}")


def _run_minute_week_timeseries(
    *,
    layout_path: Path,
    layout_json: dict,
    design_path: Path | None,
    out_dir: Path,
    epw: Path,
    ep_bin: str,
) -> None:
    week_idf = out_dir / "generic_office_week_1min.idf"
    build_idf(layout_path, design_path, week_idf, design_overrides=minute_week_design_overrides())
    minute_dir = out_dir / "ep-run-minute-week"
    minute_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    subprocess.run(
        [ep_bin, "-x", "-w", str(epw), "-d", str(minute_dir), "-r", str(week_idf)],
        check=True,
    )
    wall_seconds = time.perf_counter() - started
    minute_rows = export_timeseries_week(
        minute_dir,
        layout_json,
        out_dir / "timeseries_representative_week_1min.csv",
        resolution="minute",
    )
    meta = {
        "timesteps_per_hour": 60,
        "reporting_frequency": "Zone Timestep",
        "run_period": minute_week_design_overrides()["run_period"],
        "energyplus_wall_seconds": round(wall_seconds, 2),
        "csv_rows": minute_rows,
        "output_csv": "timeseries_representative_week_1min.csv",
    }
    meta_path = out_dir / "timeseries_minute_week.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"1-minute representative week: {minute_rows} rows in {wall_seconds:.1f} s")


def _discover_energyplus() -> str:
    home = Path.home()
    for path in home.glob("EnergyPlus/EnergyPlus-*/energyplus"):
        return str(path)
    return "energyplus"


def _default_weather(weather_file: str) -> Path:
    ep_root = Path(_discover_energyplus()).parent
    candidate = ep_root / "WeatherData" / weather_file
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"weather file not found: {weather_file} ({candidate})")


if __name__ == "__main__":
    main()