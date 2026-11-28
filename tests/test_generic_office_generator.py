"""Smoke tests for the generic office IDF generator (no EnergyPlus execution)."""

from __future__ import annotations

from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / "models"


def test_build_default_layout(tmp_path: Path) -> None:
    import sys

    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))
    from build_generic_office_vav import build_idf

    layout = MODELS / "layouts" / "default_two_story_office.json"
    out = tmp_path / "test.idf"
    build_idf(layout, MODELS / "generic_office" / "design_values.json", out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("Version,")
    assert "HVACTemplate:System:PackagedVAV" in text
    assert "HVACTemplate:Zone:VAV" in text
    assert text.count("HVACTemplate:Zone:VAV") == 10


def test_layout_defaults_ahus() -> None:
    import sys

    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))
    from generic_office.layout import layout_from_dict

    minimal = {
        "climate": {"ashrae_climate_zone": "4A", "weather_file": "x.epw"},
        "building": {
            "floors": 2,
            "footprint_length_m": 50,
            "footprint_width_m": 40,
            "floor_to_floor_m": 4,
        },
    }
    layout = layout_from_dict(minimal)
    assert len(layout.ahus) == 2
    assert len(layout.all_vavs()) == 10
    assert layout.all_vavs()[0].reheat == "electric"


def test_rdf_converter() -> None:
    import json
    import sys

    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))
    from rdf_to_layout import ttl_to_layout

    layout = ttl_to_layout(
        (MODELS / "sample_building.ttl").read_text(encoding="utf-8"),
        "4A",
        "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
    )
    assert len(layout["ahus"]) == 2
    assert sum(len(a["vavs"]) for a in layout["ahus"]) == 10
    json.dumps(layout)


def test_timestep_60_and_week_run_period(tmp_path: Path) -> None:
    import sys

    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))
    from build_generic_office_vav import build_idf
    from generic_office.timeseries import minute_week_design_overrides

    layout = MODELS / "layouts" / "default_two_story_office.json"
    out = tmp_path / "week_1min.idf"
    build_idf(layout, MODELS / "generic_office" / "design_values.json", out, design_overrides=minute_week_design_overrides())
    text = out.read_text(encoding="utf-8")
    assert "Timestep,\n  60;" in text
    assert "RepresentativeWeek" in text


def test_export_timeseries_week_hourly_from_sqlite(tmp_path: Path) -> None:
    import sqlite3
    import sys

    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))
    from generic_office.timeseries import export_timeseries_week

    sql = tmp_path / "eplusout.sql"
    layout = {
        "ahus": [{"id": "ahu-1", "vavs": [{"id": "v1", "zone": "zone-f1-core"}]}],
    }
    with sqlite3.connect(sql) as conn:
        conn.executescript(
            """
            CREATE TABLE EnvironmentPeriods (
              EnvironmentPeriodIndex INTEGER, EnvironmentType INTEGER, Name TEXT
            );
            INSERT INTO EnvironmentPeriods VALUES (1, 3, 'Annual');
            CREATE TABLE Time (
              TimeIndex INTEGER PRIMARY KEY,
              EnvironmentPeriodIndex INTEGER,
              Month INTEGER, Day INTEGER, Hour INTEGER, Minute INTEGER, WarmupFlag INTEGER
            );
            INSERT INTO Time VALUES
              (1, 1, 1, 6, 8, 10, 0),
              (2, 1, 1, 6, 8, 20, 0),
              (3, 1, 1, 6, 9, 5, 0);
            CREATE TABLE ReportDataDictionary (
              ReportDataDictionaryIndex INTEGER PRIMARY KEY,
              Name TEXT, KeyValue TEXT, ReportingFrequency TEXT
            );
            INSERT INTO ReportDataDictionary VALUES
              (1, 'Zone Mean Air Temperature', 'ZONE-F1-CORE', 'Zone Timestep');
            CREATE TABLE ReportData (
              ReportDataDictionaryIndex INTEGER, TimeIndex INTEGER, Value REAL
            );
            INSERT INTO ReportData VALUES (1, 1, 20.0), (1, 2, 22.0), (1, 3, 21.0);
            """
        )
    out_csv = tmp_path / "week.csv"
    rows = export_timeseries_week(sql.parent, layout, out_csv, resolution="hourly")
    assert rows == 2
    body = out_csv.read_text(encoding="utf-8")
    assert "Zone Mean Air Temperature" in body
    assert "ZONE-F1-CORE" in body