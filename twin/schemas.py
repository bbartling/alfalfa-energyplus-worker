from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SETPOINT_KINDS = ("supply_air_temp", "duct_static", "zone_heating", "zone_cooling", "chw", "hw")
SENSOR_KINDS = ("supply_air_temp", "duct_static", "zone_temp", "chw_temp", "hw_temp")
PERIODS = ("occupied", "unoccupied", "always")
DAYS = ("weekday", "weekend", "all", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
UNITS = {
    "supply_air_temp": "degC",
    "duct_static": "Pa",
    "zone_heating": "degC",
    "zone_cooling": "degC",
    "chw": "degC",
    "hw": "degC",
    "zone_temp": "degC",
    "chw_temp": "degC",
    "hw_temp": "degC",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    return value


class SiteIn(StrictModel):
    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    timezone: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    floor_area_m2: float = Field(gt=0, le=1_000_000)
    stories: int = Field(default=1, ge=1, le=200)
    building_type: str = Field(min_length=1, max_length=80)
    heating_fuel: Literal["gas", "electric", "heat_pump"] = "heat_pump"
    system_type: str = Field(default="psz-ac", min_length=1, max_length=40)
    weather_station: str | None = None

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("timezone must be an IANA name") from exc
        return value


class Window(StrictModel):
    days: Literal["weekday", "weekend", "all", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def clock(cls, value: str) -> str:
        hours, _, minutes = value.partition(":")
        if not hours.isdigit() or not minutes.isdigit():
            raise ValueError("clock times must be HH:MM")
        if not (0 <= int(hours) <= 24 and 0 <= int(minutes) <= 59):
            raise ValueError("clock times must be HH:MM")
        if int(hours) == 24 and int(minutes) != 0:
            raise ValueError("clock times must be HH:MM")
        return f"{int(hours):02d}:{int(minutes):02d}"


class RunHours(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    hours: float = Field(ge=0, le=900)
    hour_of_week: list[float] | None = None
    method: str = "status>0.5"

    @field_validator("hour_of_week")
    @classmethod
    def profile(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 168 or any(item < 0 or item > 1 for item in value):
            raise ValueError("hour_of_week must be 168 fractions from 0 to 1")
        return value


class Schedule(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    windows: list[Window] = Field(min_length=1, max_length=14)


class Setpoint(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    kind: Literal["supply_air_temp", "duct_static", "zone_heating", "zone_cooling", "chw", "hw"]
    period: Literal["occupied", "unoccupied", "always"] = "always"
    unit: str
    value: float
    source: Literal["actual", "inferred"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    method: str | None = None
    modes: list[float] | None = None

    @model_validator(mode="after")
    def unit_matches(self):
        expected = UNITS[self.kind]
        if self.unit != expected:
            raise ValueError(f"{self.kind} uses {expected}")
        if self.source == "actual" and self.confidence is None:
            self.confidence = 1.0
        return self


class QuantileSummary(StrictModel):
    """Fixed summary of one operating mode. About ten numbers, not a sample array."""

    n: int = Field(ge=0)
    hours: float = Field(ge=0)
    p05: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float


class Sensor(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    kind: Literal["supply_air_temp", "duct_static", "zone_temp", "chw_temp", "hw_temp"]
    unit: str
    running: QuantileSummary | None = None
    reset_modes: list[QuantileSummary] = Field(default_factory=list, max_length=4)
    occupied_heating_active: QuantileSummary | None = None
    occupied_cooling_active: QuantileSummary | None = None
    unoccupied_heating_active: QuantileSummary | None = None
    unoccupied_cooling_active: QuantileSummary | None = None

    @model_validator(mode="after")
    def unit_matches(self):
        if self.unit != UNITS[self.kind]:
            raise ValueError(f"{self.kind} uses {UNITS[self.kind]}")
        return self


class OutdoorAir(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    oa_fraction_mean: float = Field(ge=0, le=1)
    economizer_hours: float = Field(ge=0)
    economizer_enabled: bool = False


class FaultCount(StrictModel):
    equipment_id: str = Field(min_length=1, max_length=80)
    rule_id: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=0)
    exclude_from_calibration: bool = False


class Meter(StrictModel):
    meter_id: str = Field(min_length=1, max_length=80)
    fuel: Literal["electricity", "natural_gas"]
    unit: Literal["kWh", "therm", "m3"]
    start: datetime
    end: datetime
    value: float = Field(ge=0)
    granularity: Literal["month", "day", "hour"] = "month"
    role: Literal["main", "sub"] = "main"

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def span(self):
        if self.end <= self.start:
            raise ValueError("meter end must be after start")
        if self.fuel == "electricity" and self.unit != "kWh":
            raise ValueError("electricity is reported in kWh")
        if self.fuel == "natural_gas" and self.unit == "kWh":
            self.value = self.value / 29.300111
            self.unit = "therm"
        elif self.fuel == "natural_gas" and self.unit == "m3":
            self.value = self.value / 2.83168
            self.unit = "therm"
        elif self.fuel == "natural_gas" and self.unit != "therm":
            raise ValueError("natural gas is reported in therm, kWh, or m3")
        return self


class Weather(StrictModel):
    source: str = Field(min_length=1, max_length=80)
    drybulb_mean_c: float
    hdd_base_18c: float = Field(ge=0)
    cdd_base_18c: float = Field(ge=0)


class Period(StrictModel):
    start: datetime
    end: datetime
    label: Literal["week", "month"]

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def span(self):
        if self.end <= self.start:
            raise ValueError("period end must be after start")
        return self


class OperationsBatch(StrictModel):
    schema_version: Literal["1.0"]
    batch_id: UUID
    site_id: str
    generated_at: datetime
    period: Period
    run_hours: list[RunHours] = Field(default_factory=list, max_length=200)
    schedules: list[Schedule] = Field(default_factory=list, max_length=200)
    setpoints: list[Setpoint] = Field(default_factory=list, max_length=400)
    sensors: list[Sensor] = Field(default_factory=list, max_length=400)
    outdoor_air: list[OutdoorAir] = Field(default_factory=list, max_length=200)
    faults: list[FaultCount] = Field(default_factory=list, max_length=200)
    meters: list[Meter] = Field(default_factory=list, max_length=2000)
    weather: Weather

    @field_validator("generated_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return _aware(value)


class PolicyIn(StrictModel):
    cadence: Literal["weekly", "monthly"]
    kind: Literal["calibration", "tracking"]


class Measure(StrictModel):
    name: Literal["raise_cooling_setpoint", "lower_heating_setpoint", "trim_run_hours"]
    delta_c: float | None = None
    fraction: float | None = Field(default=None, ge=0, le=0.5)

    @model_validator(mode="after")
    def args(self):
        if self.name == "trim_run_hours" and self.fraction is None:
            raise ValueError("trim_run_hours requires fraction")
        if self.name != "trim_run_hours" and self.delta_c is None:
            raise ValueError(f"{self.name} requires delta_c")
        return self


class Costs(StrictModel):
    implementation_usd: float = Field(ge=0)
    electricity_usd_per_kwh: float = Field(ge=0)
    gas_usd_per_therm: float = Field(ge=0)
    discount_rate: float = Field(ge=0, le=0.3)
    horizon_years: int = Field(ge=1, le=40)


class ScenarioIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    measures: list[Measure] = Field(min_length=1, max_length=8)
    costs: Costs


class ApiKeyIn(StrictModel):
    site_ids: list[str] = Field(min_length=1, max_length=50)


class WebhookIn(StrictModel):
    url: str = Field(min_length=8, max_length=300)
    secret: str = Field(min_length=8, max_length=200)
    events: list[Literal["job.completed", "calibration.failed", "model.promoted"]] = Field(min_length=1)
