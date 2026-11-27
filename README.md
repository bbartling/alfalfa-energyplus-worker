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

Calibration compares monthly electricity (kWh) and gas (therm) with Guideline 14. Monthly limits are CV(RMSE) ≤ 15% and |NMBE| ≤ 5%. Hourly limits are 30% and 10% when an hourly meter series is present. `p` defaults to 1. The quickstart uses a summary energy model so the demo finishes immediately. The same CV(RMSE) and NMBE functions accept an EnergyPlus `Electricity:Facility` meter CSV (joules converted to kWh).

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

The quickstart binds `127.0.0.1:18080` only. Set `TWIN_HTTP_PORT` to move it. It does not bind port 80. `TWIN_DASHBOARD_OPEN=1` leaves the HTML reports readable without a key; turn that off before exposing the service. Put your own TLS proxy in front and replace the demo API key. Alfalfa is not authenticated upstream, so leave it on the internal network.
