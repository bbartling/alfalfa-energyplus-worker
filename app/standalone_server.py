"""Local daily telemetry replay. One serial simulation worker; durable job artifacts."""
import csv
import hashlib
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
import subprocess
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(os.getenv("TWIN_DATA", "/data"))
ROOT.mkdir(parents=True, exist_ok=True)
EPLUS = Path("/opt/eplus")
pool = ThreadPoolExecutor(max_workers=1)
lock = Lock()
@asynccontextmanager
async def lifespan(app):
    # Recover only on service startup, never as a side effect of importing tests.
    for status in ROOT.glob("*/status.json"):
        previous = json.loads(status.read_text())
        if previous["status"] in ("queued", "running"):
            write_json(status, {**previous, "status": "failed", "error": "service restarted; resubmit request"})
    yield


api = FastAPI(title="HVAC telemetry → EnergyPlus daily replay", version="0.1.0", lifespan=lifespan)


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    timestamp: datetime
    heating_setpoint_c: float = Field(ge=5, le=35)
    cooling_setpoint_c: float = Field(ge=10, le=40)
    zone_temperature_mean_c: float | None = Field(default=None, ge=-40, le=70)
    hvac_runtime_seconds: float | None = Field(default=None, ge=0, le=900)

    @model_validator(mode="after")
    def deadband(self):
        if self.heating_setpoint_c >= self.cooling_setpoint_c:
            raise ValueError("heating setpoint must be below cooling setpoint")
        if self.timestamp.tzinfo is not None:
            raise ValueError("use building-local standard time without UTC offset; no DST")
        return self


class Replay(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    site_id: str = Field(min_length=1, max_length=100)
    model_id: str = "demo-five-zone-v1"
    intervals: list[Interval] = Field(min_length=96, max_length=96)

    @model_validator(mode="after")
    def timeline(self):
        if self.model_id != "demo-five-zone-v1":
            raise ValueError("only the explicit demo model mapping is registered")
        start = self.intervals[0].timestamp
        if start.time() != datetime.min.time() or start.year != 2025:
            raise ValueError("demo requires one full 2025 day beginning at local midnight")
        for i, row in enumerate(self.intervals):
            if row.timestamp != start + timedelta(minutes=15*i):
                raise ValueError("96 ordered, contiguous 15-minute interval-start timestamps required")
        return self


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
    temporary.replace(path)


def execute(command, folder):
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=180)
    with (folder / "process.log").open("a") as log:
        log.write(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"EnergyPlus exited {result.returncode}; inspect process.log and eplusout.err")


def run(job, request):
    folder = ROOT / job
    write_json(folder / "status.json", {"id": job, "status": "running"})
    try:
        source = EPLUS / "ExampleFiles/5Zone_IdealLoadsAirSystems_ReturnPlenum.idf"
        weather = EPLUS / "WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
        (folder / "source.idf").write_bytes(source.read_bytes())
        execute([str(EPLUS / "energyplus"), "--convert-only", "source.idf"], folder)
        model = json.loads((folder / "source.epJSON").read_text())
        day = request.intervals[0].timestamp
        model["RunPeriod"] = {"Telemetry day": {
            "begin_month": day.month, "begin_day_of_month": day.day, "begin_year": day.year,
            "end_month": day.month, "end_day_of_month": day.day, "end_year": day.year,
            "day_of_week_for_start_day": day.strftime("%A"),
            "use_weather_file_daylight_saving_period": "No"}}
        model["Timestep"] = {"": {"number_of_timesteps_per_hour": 4}}
        # Existing thermostat objects share these schedules across all FIVE demo zones.
        # Repeat the requested day's controls across a full non-leap schedule year;
        # only the requested date is simulated. Warmup uses that same daily pattern.
        mappings = [("Htg-SetP-Sch", "heating_setpoint_c"), ("Clg-SetP-Sch", "cooling_setpoint_c")]
        model.setdefault("Schedule:File", {})
        for name, field in mappings:
            found = False
            for kind in ("Schedule:Compact", "Schedule:Constant", "Schedule:Year"):
                for key in list(model.get(kind, {})):
                    if key.casefold() == name.casefold():
                        del model[kind][key]
                        found = True
            if not found:
                raise ValueError(f"registered schedule missing: {name}")
            filename = f"{field}.csv"
            values = [str(getattr(row, field)) for row in request.intervals]
            (folder / filename).write_text("\n".join(values * 365) + "\n")
            model["Schedule:File"][name] = {
                "file_name": str(folder / filename), "column_number": 1, "rows_to_skip_at_top": 0,
                "number_of_hours_of_data": 8760, "column_separator": "Comma",
                "interpolate_to_timestep": "No", "minutes_per_item": 15}
        model["Output:Variable"] = {"temperature": {"key_value": "SPACE1-1",
            "variable_name": "Zone Mean Air Temperature", "reporting_frequency": "Timestep"}}
        for name, field in mappings:
            model["Output:Variable"][field] = {"key_value": name,
                "variable_name": "Schedule Value", "reporting_frequency": "Timestep"}
        model["OutputControl:Files"] = {"": {"output_csv": "No"}}
        write_json(folder / "model.epJSON", model)
        write_json(folder / "provenance.json", {
            "model_id": request.model_id, "energyplus": "26.1.0",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "weather_sha256": hashlib.sha256(weather.read_bytes()).hexdigest(),
            "weather": weather.name, "weather_is_measured": False,
            "scope": "setpoints apply to all five demo zones; temperature comparison is SPACE1-1",
            "runtime_policy": "retained as observation; no runtime-to-setpoint inference",
            "time_basis": "2025 building-local standard time; interval starts; no DST"})
        execute([str(EPLUS / "energyplus"), "-r", "-w", str(weather), "model.epJSON"], folder)
        with (folder / "eplusout.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        column = next(k for k in rows[0] if "SPACE1-1:Zone Mean Air Temperature" in k)
        if len(rows) != 96:
            raise ValueError(f"expected 96 simulation intervals, got {len(rows)}")
        for name, field in mappings:
            schedule_column = next(k for k in rows[0] if f"{name}:Schedule Value".casefold() in k.casefold())
            for obs, sim in zip(request.intervals, rows):
                if abs(float(sim[schedule_column]) - getattr(obs, field)) > 0.001:
                    raise ValueError(f"schedule replay mismatch: {name}")
        comparisons = [{"timestamp": obs.timestamp.isoformat(), "simulated_temperature_c": float(sim[column]),
                        "measured_temperature_c": obs.zone_temperature_mean_c,
                        "hvac_runtime_seconds": obs.hvac_runtime_seconds}
                       for obs, sim in zip(request.intervals, rows)]
        paired = [(r["simulated_temperature_c"], r["measured_temperature_c"])
                  for r in comparisons if r["measured_temperature_c"] is not None]
        metrics = {"paired_temperature_intervals": len(paired), "guideline14_compliance": "not assessed"}
        if paired:
            metrics["temperature_rmse_c"] = math.sqrt(sum((s-m)**2 for s,m in paired)/len(paired))
            metrics["temperature_bias_c"] = sum(s-m for s,m in paired)/len(paired)
        write_json(folder / "results.json", {"metrics": metrics, "intervals": comparisons})
        write_json(folder / "status.json", {"id": job, "status": "completed"})
    except Exception as error:
        write_json(folder / "status.json", {"id": job, "status": "failed", "error": str(error)})


@api.get("/health")
def health():
    return {"status": "ok", "energyplus": "26.1.0", "mode": "daily-batch-replay"}


@api.post("/replays", status_code=202)
def submit(request: Replay):
    with lock:
        active = sum(json.loads(p.read_text())["status"] in ("queued", "running")
                     for p in ROOT.glob("*/status.json"))
        if active >= 4:
            raise HTTPException(429, "local queue full; retry after a job completes")
        job = str(uuid4())
        folder = ROOT / job
        folder.mkdir()
        write_json(folder / "request.json", request.model_dump(mode="json"))
        write_json(folder / "status.json", {"id": job, "status": "queued"})
        pool.submit(run, job, request)
    return {"id": job, "status": "queued", "status_url": f"/replays/{job}"}


def job_folder(job):
    from uuid import UUID
    try:
        if str(UUID(job)) != job:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "unknown job")
    folder = ROOT / job
    if not (folder / "status.json").exists():
        raise HTTPException(404, "unknown job")
    return folder


@api.get("/replays/{job}")
def status(job: str):
    folder = job_folder(job)
    result = json.loads((folder / "status.json").read_text())
    if result["status"] == "completed":
        result["results"] = json.loads((folder / "results.json").read_text())
    return result


@api.get("/replays/{job}/artifacts/{name}")
def artifact(job: str, name: str):
    folder = job_folder(job)
    allowed = {"request.json", "provenance.json", "results.json", "model.epJSON",
               "process.log", "eplusout.err", "eplusout.csv"}
    if name not in allowed or not (folder / name).is_file():
        raise HTTPException(404, "artifact unavailable")
    return FileResponse(folder / name)
