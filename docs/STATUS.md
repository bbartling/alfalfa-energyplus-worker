# Status

A generic twin that accepts compact HVAC summaries from an IoT FDD application. No customer names, no raw telemetry, no Parquet, no MQTT broker.

## What works

- `docker compose --profile demo up --build -d` backfills two offices, retries, stays idempotent, and opens a report on `127.0.0.1:18080`. The report shows calibration status, Guideline 14 CV(RMSE) and NMBE, and ROI what-ifs.
- Missing setpoints are inferred from samples taken while equipment runs (`source=actual` or `source=inferred`, with a method and confidence). Actual values are kept.
- The default calibrator is the **quick estimate**: a summary energy model that finishes immediately and is what the demo uses.
- `POST /v1/sites/{id}/calibrations?engine=energyplus` queues a worker job. It maps schedules and setpoints onto the DOE SmallOffice prototype (ASHRAE 90.1-2013, floor area 511 m²) and runs a coarse grid plus a half-step refinement of infiltration, lighting and plug LPD, fan efficiency, cooling COP, and the setpoint offset. EnergyPlus 24.2 runs in `nrel/openstudio:3.9.0`. Monthly facility electricity and gas from the SQL output are scaled by site area / prototype area and scored with Guideline 14.
- A what-if on a quick-estimate model stays in that model. A what-if on an EnergyPlus calibration is queued and reruns that calibrated model, then the same model with the measure (setpoint change or a shorter occupied window).
- Alfalfa stays optional and unmodified, with no host ports. S3 is `http://minio:9000`. Live runs return 409 until `ALFALFA_URL` is set.
- CI on `develop` runs lint, unit tests, the demo compose poster, an Alfalfa compose render, and two three-day EnergyPlus simulations.

## How to run

```bash
docker compose --profile demo up --build -d
docker compose --profile energyplus up --build -d
```

The demo key is `local-demo-key`. Queue an EnergyPlus calibration with `?engine=energyplus` after the summaries are in. `python -m twin.runner` is the same worker. `make test` skips the EnergyPlus marker. `make energyplus-smoke` runs the two short simulations.

One annual SmallOffice run is about ten seconds, so the default grid is tens of minutes. The worker exists so a wider grid or a larger model can run for hours without blocking the API.

## What's left

- Weather is a TMY file chosen from latitude (Chicago, Baltimore, or Miami), not actual-year weather.
- The sweep is a coarse grid and a one-at-a-time half step, not a Morris, LHS, or Bayesian search.
- Results are scaled from the small-office prototype. There is no medium-office geometry and no OpenStudio measure run at calibration time.
- EnergyPlus tracking reuses the last calibration instead of a new simulation.
- Alfalfa is not started, and it does not execute control or grid-flexibility runs.
- The repository has `develop` and no `main`.
