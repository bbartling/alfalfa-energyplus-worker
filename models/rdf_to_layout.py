#!/usr/bin/env python3
"""Convert a Brick / Haystack RDF model into generic-office layout JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# Minimal Turtle lexer/parser for our constrained sample files (no external deps).
BRICK = "https://brickschema.org/schema/Brick#"
HAYSTACK = "https://project-haystack.org/def/"
ASHRAE223 = "https://open223.info/ontology/223#"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ttl", type=Path, help="RDF/Turtle building model")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Layout JSON output path")
    parser.add_argument("--climate-zone", default="4A")
    parser.add_argument(
        "--weather-file",
        default="USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
    )
    args = parser.parse_args()
    layout = ttl_to_layout(args.ttl.read_text(encoding="utf-8"), args.climate_zone, args.weather_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


def ttl_to_layout(text: str, climate_zone: str, weather_file: str) -> dict[str, Any]:
    triples = _parse_ttl(text)
    subjects = _index_triples(triples)
    floors = _int_prop(subjects, "building", "floors", default=2)
    length = _float_prop(subjects, "building", "footprintLength", default=76.2)
    width = _float_prop(subjects, "building", "footprintWidth", default=60.96)
    floor_to_floor = _float_prop(subjects, "building", "floorToFloor", default=3.96)
    total_area = _float_prop(subjects, "building", "totalArea", default=length * width * floors)
    ahus = _collect_ahus(subjects)
    return {
        "schema_version": "1.0",
        "climate": {"ashrae_climate_zone": climate_zone, "weather_file": weather_file},
        "building": {
            "floors": floors,
            "footprint_length_m": length,
            "footprint_width_m": width,
            "floor_to_floor_m": floor_to_floor,
            "total_area_m2": total_area,
        },
        "ahus": ahus,
    }


def _collect_ahus(subjects: dict[str, dict[str, list[str]]]) -> list[dict]:
    ahus: list[dict] = []
    for sid, props in subjects.items():
        types = props.get("a", [])
        if not (
            _is_type(props, {f"{BRICK}AHU", f"{BRICK}Rooftop_Unit", f"{ASHRAE223}AirHandlingUnit"})
            or any("Rooftop_Unit" in t or "AirHandlingUnit" in t for t in types)
        ):
            continue
        ahu_id = _local_name(sid)
        floor = _int_from_props(props, default=_infer_floor(ahu_id))
        vavs = []
        feeds = props.get("fed", []) + props.get(f"{BRICK}feeds", []) + props.get("brick:feeds", [])
        for feed in feeds:
            vav_subject = _strip(feed)
            vprops = subjects.get(vav_subject, {})
            if not _is_type(
                vprops,
                {f"{BRICK}VAV", f"{ASHRAE223}VariableAirVolumeBox", f"{BRICK}Terminal_Unit"},
            ):
                continue
            zone = _first(
                vprops.get("serves", [])
                + vprops.get(f"{BRICK}feeds", [])
                + vprops.get("brick:feeds", [])
            )
            zone_name = _local_name(_strip(zone)) if zone else f"zone-{_local_name(vav_subject)}".replace("vav-", "")
            reheat = _reheat_type(vprops)
            vavs.append(
                {
                    "id": _local_name(vav_subject),
                    "zone": zone_name,
                    "reheat": reheat,
                    "floor": _int_from_props(vprops, default=floor),
                    "perimeter": _perimeter_tag(zone_name),
                }
            )
        ahus.append({"id": ahu_id, "floor": floor, "gas_preheat": False, "vavs": vavs})
    return ahus


def _reheat_type(props: dict[str, list[str]]) -> str:
    for key, values in props.items():
        if "reheat" in key.lower() or "Reheat" in key:
            joined = " ".join(values).lower()
            if "water" in joined or "hot" in joined or "hw" in joined:
                return "hot_water"
    for t in props.get("a", []):
        if "Hot_Water" in t or "Water" in t:
            return "hot_water"
    return "electric"


def _perimeter_tag(zone_name: str) -> str:
    for label in ("north", "south", "east", "west", "core"):
        if zone_name.endswith(label):
            return label
    return "core"


def _parse_ttl(text: str) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("@prefix"):
            continue
        if line.endswith("."):
            line = line[:-1]
        m = re.match(r"^(\S+)\s+(\S+)\s+(.+)$", line)
        if not m:
            continue
        subj, pred, rest = m.group(1), m.group(2), m.group(3).strip()
        for obj in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", rest):
            triples.append((subj, pred, obj.strip()))
    return triples


def _index_triples(triples: list[tuple[str, str, str]]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for subj, pred, obj in triples:
        out.setdefault(subj, {}).setdefault(pred, []).append(obj)
    return out


def _is_type(props: dict[str, list[str]], types: set[str]) -> bool:
    for t in props.get("a", []) + props.get("type", []):
        if _strip(t) in types or any(_strip(t).endswith(x.split("#")[-1]) for x in types):
            return True
    return False


def _strip(value: str) -> str:
    if value.startswith("<") and value.endswith(">"):
        return value[1:-1]
    if ":" in value and not value.startswith("\""):
        return value
    return value.strip('"')


def _local_name(uri_or_id: str) -> str:
    token = _strip(uri_or_id)
    if "#" in token:
        return token.rsplit("#", 1)[-1]
    if ":" in token and not token.startswith("http"):
        return token.split(":", 1)[-1]
    return token


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _float_prop(subjects: dict, key: str, prop: str, default: float) -> float:
    props = subjects.get(key, subjects.get(f"building:{key}", {}))
    for predicate in (prop, f"{HAYSTACK}{prop}", f"{BRICK}{prop}"):
        if predicate in props:
            return float(_strip(props[predicate][0]))
    for sid, props in subjects.items():
        if _local_name(sid) in {key, "site", "building"}:
            for p, values in props.items():
                if prop.lower() in p.lower():
                    return float(_strip(values[0]))
    return default


def _int_prop(subjects: dict, key: str, prop: str, default: int) -> int:
    return int(round(_float_prop(subjects, key, prop, float(default))))


def _infer_floor(name: str) -> int:
    for token in name.split("-"):
        if token.startswith("f") and token[1:].isdigit():
            return int(token[1:])
    return 1


def _int_from_props(props: dict[str, list[str]], default: int) -> int:
    for p, values in props.items():
        if "floor" in p.lower():
            return int(float(_strip(values[0])))
    return default


if __name__ == "__main__":
    main()