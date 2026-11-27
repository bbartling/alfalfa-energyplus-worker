# Status

A generic twin that accepts compact HVAC summaries from an IoT FDD application. No customer names, no raw telemetry, no Parquet, no MQTT broker.

This is the handoff after the issue #7 fixes. The repository has `develop` and no `main`.

## What works

- `make quickstart` (or the demo compose command below) backfills two offices, retries, stays idempotent, and opens a report on `127.0.0.1:18080`. Demo values are exported by the Makefile and CI. They are not defaults in `compose.yaml`. `TWIN_ENV=prod` refuses the demo key and an open dashboard.
- Sites, batches, jobs, models, scenarios, and webhooks are tenant scoped. Postgres row security is on. SQLite tests skip it. A cross-tenant id is a 404.
- Missing setpoints are inferred from mode-split quantiles. Heating uses the upper quantile of heating-active hours and cooling the lower quantile of cooling-active hours. A reset keeps both modes. Confidence below 0.6 is dropped. An actual value of that kind always wins. Gas may arrive as therm, kWh, or m³ and is stored as therm. Request bodies over 1 MB are rejected.
- The default calibrator is a screening change-point model. It is never promoted and it does not retire an EnergyPlus model. The demo meters come from a separate generator, not from the fitter.
- `POST /v1/sites/{id}/calibrations?engine=energyplus` queues a worker job for a small office of 250–2,500 m², one or two storeys, packaged RTU, gas, electric, or heat pump. Schedules are rewritten from the weekday columns of `Schedule:Week:Daily` (this EnergyPlus 24.2 file has no `Schedule:Ruleset`). Daylight-saving time is not applied a second time. Weather is the nearest typical-year station, and the site location and design days are replaced from that station. It is not the actual year of the bills.
- Guideline 14 is claimed only for 12 or more usable months, scored on the whole year. Fewer months are `insufficient-data`. Leave-one-month-out CV(RMSE) is a diagnostic. Metrics show `p` and the number of tuned parameters. NMBE is positive when measured energy is above the model. Hourly Guideline 14 is not claimed. Only the main meter counts, coverage must be at least 95% of the period, and an overlapping period is rejected.
- An EnergyPlus what-if runs each passing member's own baseline and altered case. The band is the 10th to 90th percentile of savings.
- Tracking an EnergyPlus model reruns the calibrated case on the nearest typical year. Drift uses the monthly limits over the last three to six tracking results and recalibrates with the active model's engine.
- The worker claims a job with a 30-minute lease. Postgres uses `FOR UPDATE SKIP LOCKED`. An expired lease is queued again until three attempts.
- Webhooks are https to a public address, checked again at send time. The stored secret is a random signing key. Delivery signs `timestamp.body` and retries.
- A finished EnergyPlus model stores the calibrated IDF, its sha256, the weather-file sha256, and the EnergyPlus version string.
- Alfalfa stays optional and unmodified, with no host ports. S3 is `http://minio:9000`.
- CI on `develop` runs lint, unit tests, the demo compose poster, an Alfalfa compose render, and two three-day EnergyPlus simulations.

## How to run

```bash
docker compose --profile demo up --build -d
docker compose --profile energyplus up --build -d
```

The demo key is `local-demo-key`. Set `TWIN_ENV=demo`, `TWIN_BOOTSTRAP_KEY=local-demo-key`, `TWIN_DASHBOARD_OPEN=1`, `POSTGRES_PASSWORD`, and `DATABASE_URL` (the Makefile does this). Queue an EnergyPlus calibration with `?engine=energyplus` after the summaries are in. `python -m twin.runner` is the worker. `make test` skips the EnergyPlus marker. `make energyplus-smoke` runs the two short simulations.

Schema changes are applied with `create_all`. An existing Postgres volume does not gain new columns. Recreate it with `docker compose down -v`.

One annual SmallOffice run is about ten seconds, so the default grid is tens of minutes.

## Deferred

- Actual-year weather (AMY) was not built. There is no weather service. Nearest-station TMY, CWEC, or CZ2010 is what tracking and calibration use.
- Alembic migrations (existing volumes must be recreated).
- Tariff, time-of-use, escalation, and unmet hours.
- A full OpenStudio measures migration. The positional IDF editor stays because the EnergyPlus IDD is only inside the OpenStudio image, so eppy is not available to the unit tests.
- Morris, LHS, or Bayesian search. The v1 sweep stays the coarse grid plus a half step, and only inside the small-office band.
- `POST /v1/sites` still ignores a later registration that changes attributes.
- API key rotation and revocation.
- Unused summary fields other than hour-of-week: economizer, dry-bulb series, SAT/duct/CHW/HW setpoints as model inputs, and outdoor-air fraction.
- The live Alfalfa path, including control and grid-flexibility runs.
- A `model.promoted` webhook emission.
