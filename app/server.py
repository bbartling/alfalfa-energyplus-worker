"""Local daily telemetry replay. One serial simulation worker; durable job artifacts."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(os.getenv("TWIN_DATA", "/data"))
ROOT.mkdir(parents=True, exist_ok=True)
ALFALFA_URL = os.getenv("ALFALFA_URL", "http://web")
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
    model_id: str = "alfalfa-schedule-model-v1"
    intervals: list[Interval] = Field(min_length=96, max_length=96)

    @model_validator(mode="after")
    def timeline(self):
        if self.model_id != "alfalfa-schedule-model-v1":
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


from app.alfalfa_backend import run


@api.get("/health")
def health():
    return {"status": "ok", "backend": "alfalfa", "alfalfa_url": ALFALFA_URL}


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
               "progress.json", "cleanup_error.json", "alfalfa-run.tar.gz"}
    if name not in allowed or not (folder / name).is_file():
        raise HTTPException(404, "artifact unavailable")
    return FileResponse(folder / name)
