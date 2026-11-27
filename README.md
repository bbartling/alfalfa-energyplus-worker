# Building twin

A small service that calibrates a building energy model from the compact summaries an IoT FDD application already computes: run hours, schedules, setpoints, outdoor-air fraction, fault counts, monthly meters, and a weather summary. It checks the result with ASHRAE Guideline 14 and prices simple ROI what-ifs.

Raw interval telemetry is not accepted. There is no Parquet path.

## Quickstart

```bash
docker compose --profile demo up --build -d
```

Then open [http://127.0.0.1:18080](http://127.0.0.1:18080).

That one command starts Postgres, the API, and a poster. The poster backfills six months for two offices, retries if the API is still starting, re-posts a batch to show it is idempotent, pushes one newer month, calibrates, and stores a cooling-setpoint what-if. The home page lists each site. A site page shows CV(RMSE), NMBE, pass or fail, and the what-if payback and NPV.

The local API key is `local-demo-key` (override `TWIN_BOOTSTRAP_KEY`). Interactive docs are at [http://127.0.0.1:18080/docs](http://127.0.0.1:18080/docs).

```bash
docker compose --profile demo logs poster
docker compose down
```

`make quickstart` is the same command.

## What gets posted

Weekly or monthly JSON, one batch per site. The contract is [docs/data-contract.md](docs/data-contract.md). When a setpoint is missing, the service infers it from sensor samples taken while the equipment ran:

- supply air temperature, duct static pressure, and water temperatures use a steady-state percentile
- zone heating and cooling use a deadband percentile on occupied and unoccupied samples

Each stored setpoint is `source=actual` or `source=inferred` and includes a confidence score. Fault periods marked `exclude_from_calibration` are left out of the fit.

Calibration compares monthly electricity (kWh) and gas (therm) with Guideline 14. Monthly limits are CV(RMSE) ≤ 15% and |NMBE| ≤ 5%. Hourly limits are 30% and 10% when an hourly meter series is present. `p` defaults to 1.

The quickstart calibrator is labeled **quick estimate**. It is a summary energy model so the demo finishes immediately. The same CV(RMSE) and NMBE functions accept an EnergyPlus `Electricity:Facility` series (joules converted to kWh).

## EnergyPlus calibration

`POST /v1/sites/{site_id}/calibrations?engine=energyplus` queues a worker job. The job maps the summary schedules and setpoints onto the DOE SmallOffice prototype (ASHRAE 90.1-2013, checked in under `models/`), then runs a coarse grid and a half-step refinement on infiltration, lighting and plug LPD, fan efficiency, cooling COP, and the setpoint offset. Each point is one annual run of EnergyPlus 24.2 in `nrel/openstudio:3.9.0`. Monthly `Electricity:Facility` and `NaturalGas:Facility` are scaled by site area over the prototype area (511 m²) and scored with Guideline 14. One annual run of this small office is about ten seconds, so the default grid is tens of minutes. A wider grid or a larger model is the long job the worker is for.

The API does not run that sweep inline. Start the worker next to the API:

```bash
docker compose --profile energyplus up --build -d
```

CI runs two three-day simulations (`pytest -m energyplus`), not the full grid. `make test` skips that marker.

An ROI what-if on a quick-estimate model stays in that model and is labeled quick estimate. A what-if on an EnergyPlus calibration is queued the same way and reruns the calibrated case, then the case with the measure applied (setpoint change or a shorter occupied window). The savings, payback, NPV, and ensemble band come from those runs.

A monthly policy and a weekly tracking policy live on `POST /v1/sites/{site_id}/policies`. `POST /v1/scheduler/tick` enqueues what is due. Two tracking results with CV(RMSE) above 30% enqueue a recalibration. Long runs can be pulled by `python -m twin.runner` with `TWIN_INLINE_JOBS=0`.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
make test
make lint
```

## Optional Alfalfa

Alfalfa stays an unmodified upstream stack for a live model, not for calibration sweeps. It publishes no host ports. Presigned uploads use `http://minio:9000` from `.env`, which works on Linux.

```bash
make alfalfa-config
make alfalfa
```

Images are pinned to the Alfalfa revision `af3caee`. See [docs/simpler-alternative.md](docs/simpler-alternative.md) for when the single container is enough.

## Security

The quickstart binds `127.0.0.1:18080` only and runs with `TWIN_ENV=demo`. It does not bind port 80. `TWIN_ENV=prod` refuses to start when the bootstrap key is missing, is `local-demo-key`, or is shorter than 32 characters, and it refuses an open dashboard. API keys are tenant scoped: a key sees only its tenant's sites, jobs, and webhooks. Put your own TLS proxy in front. Alfalfa is not authenticated upstream, so leave it on the internal network.
