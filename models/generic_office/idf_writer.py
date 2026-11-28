"""Minimal EnergyPlus IDF serialization (24.2 field order)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IdfObject:
    """One IDF object instance."""

    type: str
    fields: list[str | float | int | None]

    def name(self) -> str:
        if not self.fields:
            return ""
        return str(self.fields[0] or "")

    def lines(self) -> list[str]:
        out = [self.type + ","]
        n = len(self.fields)
        for i, value in enumerate(self.fields):
            text = _field_text(value)
            suffix = ";" if i == n - 1 else ","
            if i == 0:
                out.append(f"  {text}{suffix}")
            else:
                out.append(f"  {text}{suffix}  !- Field {i + 1}")
        return out


def _field_text(value: str | float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.6g}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@dataclass
class IdfDocument:
    version: str = "24.2"
    objects: list[IdfObject] = field(default_factory=list)

    def add(self, obj: IdfObject) -> None:
        self.objects.append(obj)

    def extend(self, objects: list[IdfObject]) -> None:
        self.objects.extend(objects)

    def unique_name(self, prefix: str) -> str:
        existing = {o.name() for o in self.objects if o.name()}
        if prefix not in existing:
            return prefix
        n = 2
        while f"{prefix}-{n}" in existing:
            n += 1
        return f"{prefix}-{n}"

    def render(self) -> str:
        parts = [
            "Version,",
            f"  {self.version};                    !- Version Identifier",
            "",
        ]
        for obj in self.objects:
            parts.extend(obj.lines())
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")