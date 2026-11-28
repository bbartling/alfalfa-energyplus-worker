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