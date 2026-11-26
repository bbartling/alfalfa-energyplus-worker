# Local upstream Alfalfa + telemetry client

The default stack now runs the actual upstream Alfalfa web and worker images,
MongoDB, Redis, MinIO (local S3), and the upstream bucket initializer. No Alfalfa
application code, simulation worker, or EnergyPlus runtime is patched.

A separate custom telemetry client translates IoT observations into official
Alfalfa API calls. It is NOT a replacement Alfalfa API or an Alfalfa certification.
The earlier direct-EnergyPlus experiment is optional and no longer the default.

## Start (PowerShell, Docker Desktop Linux containers)

```powershell
./start-local.ps1
docker compose exec -T telemetry python examples/alfalfa_smoke.py
docker compose exec -T telemetry python examples/demo.py
```

The launcher clones upstream at 6c76e0b04fccc1fcbf64f8304bf622bc26710368,
pulls official images, builds only the telemetry client, and starts the stack.
Compose include requires a recent Docker Compose supporting include and !override.
The web and worker are pinned by registry digest in alfalfa.local.yaml.
Do not use docker compose up --build: that would rebuild included upstream images;
use the launcher, or build telemetry then up -d --no-build.

- Alfalfa UI: http://localhost/
- Upstream rendered API reference: http://localhost/redoc
- Official API: http://localhost/api/v2/runs
- Telemetry client schema: http://localhost:8088/docs
- MinIO S3 endpoint: http://localhost:9000

Upstream /docs currently returns 404 in this published image; /redoc works.
All exposed ports bind localhost. Redis and MongoDB are internal to Docker.
Named volumes retain Mongo metadata, Redis files, S3 objects, and client results.
Default credentials are upstream local development credentials. This is a local
prototype, without production auth, TLS, or tenant isolation.

## What the compatibility test verifies

examples/alfalfa_smoke.py uses alfalfa-client==1.0.0, matching upstream tests:
model upload through a presigned S3 form, upstream OpenStudio preprocessing,
READY -> RUNNING, external clock, input discovery, thermostat writes, output
readbacks, one-minute timestep advancement, stop -> COMPLETE, and official run
archive download. It uses the unmodified upstream schedule_model fixture.
The official worker bundles OpenStudio 3.9 and EnergyPlus 24.2; the locally
installed Windows EnergyPlus 26.1 is deliberately not substituted.

## Telemetry replay

POST /replays accepts site_id, model_id (alfalfa-schedule-model-v1), and intervals.
Each record has timestamp, heating_setpoint_c, cooling_setpoint_c, and optional
zone_temperature_mean_c and hvac_runtime_seconds. See examples/demo.py for a
complete synthetic payload. Supply 96 contiguous 15-minute interval-start records
for a full 2025 day, starting at local midnight, standard time without DST/offsets.
Heating must be below cooling; runtime is seconds in the interval (0–900).

The registered demo mapping writes CONSTANT HEATING and COMPACT COOLING, the two
thermostat schedules on one zone in upstream's test model. It does not override
all model zones. The client verifies both readbacks after every official
one-minute advance, averages 15 minute samples per observation, and retains all
zone temperature outputs. No sensor-to-zone match is guessed; temperature RMSE
requires an explicit real-building mapping. Runtime remains an observation and
is not converted to a thermostat temperature or claimed as simulated runtime.

GET /replays/{id} returns job state/results and the official alfalfa_run_id.
GET /replays/{id}/artifacts/{name} serves request.json, provenance.json,
results.json, progress.json, cleanup_error.json, or alfalfa-run.tar.gz.
The archive is downloaded through Alfalfa's own run-download endpoint and MinIO.
S3_URL_EXTERNAL uses kubernetes.docker.internal, a Docker Desktop hostname that
already resolves to loopback on this Windows machine. Compose maps that same
hostname to host-gateway inside client/test containers. This lets Windows and
Docker clients follow the same signed S3 URLs without changing system DNS or
rewriting signatures. No running Kubernetes cluster is required. On another host,
verify that hostname resolves to loopback before using this local configuration.

One client job runs at a time; up to four can queue. Each replay submits a fresh
model/run; there is no cross-day thermal state continuity or submission dedup.
A restart marks interrupted client jobs failed; it does not automatically resume
or stop their upstream run. Inspect alfalfa_run_id and stop abandoned runs using
the official API. Do not run multiple telemetry API processes.

## Calibration next

The replay proves API integration, not building calibration. Weather/model data
are upstream examples, and telemetry in demo.py is synthetic. GL14 compliance is
not assessed. Real use needs the actual building model and sensor/equipment map,
actual-period weather, metered energy, versioned parameter candidates, and
training/held-out validation. Compute NMBE and CV(RMSE) for aligned energy data
with a documented M&V plan. Temperature fit alone is insufficient.

- [Upstream Alfalfa](https://github.com/NatLabRockies/alfalfa)
- [FEMP M&V Guidelines 5.0](https://www.energy.gov/sites/default/files/2024-10/mv_guide_5_0.pdf)

## Operations

```powershell
docker compose ps
docker compose logs --tail 50 web worker telemetry
docker compose exec -T telemetry python -m unittest discover -s tests -v
docker compose down
```

Down preserves volumes; down -v deletes this project's data. Unrelated database
containers are untouched. The prior direct EnergyPlus prototype is preserved in
compose.standalone.yaml / Dockerfile.standalone / app/standalone_server.py; use it
only as an explicitly separate experiment. It is not the Alfalfa compatibility
path. Its port 8088 conflicts with telemetry, so do not run both together.

## Unmodified upstream regression tests

A separate optional test image adds pytest/client tooling to the official worker
image; it does not modify the running worker. It mounts upstream tests read-only.
Run the two official schedule tests and Python EMS enable/disable test:

```powershell
docker compose --profile verification build integration
docker compose --profile verification run --rm --no-deps integration
```

These cover automatic input/output point creation, schedule writes/readbacks,
Python plugin I/O, and release of an actuator back to the model using null.

## Source identity and local verification

The pinned published application images contain runtime code matching upstream
revision af3caee5036d6c6ac10558307d7fd31fe12857de. The Compose/test fixture checkout
is the separately pinned 6c76e0b revision; it includes newer upstream changes.
The running images are not claimed to be builds of that newer checkout.

```powershell
python tools/audit_upstream.py
```

This read-only optional audit compares 37 worker Python/Ruby/workflow files and
7 web API JavaScript files with their upstream git content, normalizing CRLF.
All 44 checked files matched. Python is needed on the host only for this optional
source audit; all service operation and simulation tests run in Docker.

Verified locally: three upstream integration tests passed, three client contract
tests passed, full daily replay completed 96 intervals/1440 advances with matching
control readbacks, official run archives downloaded and validated, direct Windows
signed S3 download succeeded, and start-local.ps1 completed successfully.
