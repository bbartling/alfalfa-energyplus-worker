"""Parse EnergyPlus sizing outputs (eplusout.eio and tabular reports). Stub for future calibration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SizingSummary:
    """Autosized capacities and flows extracted from an EnergyPlus run."""

    source_dir: Path
    zone_sizing: dict[str, dict[str, str]] = field(default_factory=dict)
    system_sizing: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


_ZONE_LINE = re.compile(
    r"Zone Sizing Information, (?P<zone>[^,]+), (?P<field>[^,]+), (?P<value>.+)$"
)
_SYSTEM_LINE = re.compile(
    r"System Sizing Information, (?P<system>[^,]+), (?P<field>[^,]+), (?P<value>.+)$"
)


def extract_sizing(run_dir: Path) -> SizingSummary:
    """
    Read ``eplusout.eio`` and optional ``eplustbl.htm`` / CSV table exports.

    Returns structured sizing dicts keyed by zone or air-loop name. This stub
    omits HTML table parsing; callers can extend ``_parse_tabular`` later.
    """
    run_dir = Path(run_dir)
    summary = SizingSummary(source_dir=run_dir)
    eio = run_dir / "eplusout.eio"
    if not eio.is_file():
        summary.warnings.append(f"missing {eio}")
        return summary
    for line in eio.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := _ZONE_LINE.search(line):
            summary.zone_sizing.setdefault(m.group("zone"), {})[m.group("field").strip()] = m.group(
                "value"
            ).strip()
        elif m := _SYSTEM_LINE.search(line):
            summary.system_sizing.setdefault(m.group("system"), {})[m.group("field").strip()] = m.group(
                "value"
            ).strip()
    _parse_tabular(run_dir, summary)
    return summary


def _parse_tabular(run_dir: Path, summary: SizingSummary) -> None:
    """Placeholder for HTML/CSV tabular report scraping."""
    for name in ("eplustbl.htm", "eplusout.csv"):
        path = run_dir / name
        if path.is_file():
            summary.warnings.append(f"tabular parse not implemented for {path.name}")


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Extract autosizing from an EnergyPlus output directory")
    parser.add_argument("run_dir", type=Path, help="Directory containing eplusout.eio")
    args = parser.parse_args()
    result = extract_sizing(args.run_dir)
    print(json.dumps({"zone_sizing": result.zone_sizing, "system_sizing": result.system_sizing, "warnings": result.warnings}, indent=2))


if __name__ == "__main__":
    main()