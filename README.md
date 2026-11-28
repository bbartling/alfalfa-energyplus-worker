# Building twin

A small service that calibrates a building energy model from the compact summaries an IoT FDD application already computes: run hours, schedules, setpoints, outdoor-air fraction, fault counts, monthly meters, and a weather summary. EnergyPlus calibrations are checked with ASHRAE Guideline 14. The quick estimate is a screening change-point model and is not a Guideline 14 result.

Raw interval telemetry is not accepted. There is no Parquet path.

## Quickstart

```bash
docker compose --profile demo up --build -d
```

Then open [http://127.0.0.1:18080](http://127.0.0.1:18080).

That one command starts Postgres, the API, and a poster. The poster backfills a year for two offices, retries if the API is still starting, re-posts a batch to show it is idempotent, pushes one newer month, fits a screening change-point model, and stores a cooling-setpoint what-if. The home page lists each site. A site page shows the screening CV(RMSE) and NMBE, and the what-if payback and NPV.

The local API key is `local-demo-key` (override `TWIN_BOOTSTRAP_KEY`). Interactive docs are at [http://127.0.0.1:18080/docs](http://127.0.0.1:18080/docs).

```bash
docker compose --profile demo logs poster
docker compose down
```

`make quickstart` is the same command.

## What gets posted

Weekly or monthly JSON, one batch per site. The contract is [docs/data-contract.md](docs/data-contract.md). When a setpoint is missing, the service infers it from mode-split quantiles:

- heating is the upper quantile of heating-active hours, and cooling is the lower quantile of cooling-active hours
- a supply-air reset keeps both modes instead of averaging them
- a mode active for fewer than 8 hours is not emitted, and confidence below 0.6 is dropped

An actual setpoint wins over an inferred one. Fault periods marked `exclude_from_calibration` are left out of the fit. Only a main meter is calibrated, and a period must cover at least 95% of its month.

EnergyPlus calibration compares a full year of monthly electricity (kWh) and gas (therm) with Guideline 14. Monthly limits are CV(RMSE) ≤ 15% and |NMBE| ≤ 5%. Fewer than 12 usable months is `insufficient-data`, not a Guideline 14 result. Hourly Guideline 14 is not claimed. `p` defaults to 1 and is shown with the number of tuned parameters.

The quickstart calibrator is a **screening** change-point model (baseload, cooling per degree-day, heating per degree-day). A setpoint change moves the balance point. It is never promoted and it is not shown under a Guideline 14 heading. The same CV(RMSE) and NMBE functions accept an EnergyPlus `Electricity:Facility` series (joules converted to kWh).

## EnergyPlus calibration

`POST /v1/sites/{site_id}/calibrations?engine=energyplus` queues a worker job. The job maps the summary schedules and setpoints onto the DOE SmallOffice prototype (ASHRAE 90.1-2013, checked in under `models/`), then runs a coarse grid and a half-step refinement on infiltration, lighting and plug LPD, fan efficiency, cooling COP, and the setpoint offset. Each point is one annual run of EnergyPlus 24.2 in `nrel/openstudio:3.9.0`. Monthly `Electricity:Facility` and `NaturalGas:Facility` are scaled by site area over the prototype area (511 m²) and scored with Guideline 14. Weather is the nearest station in the OpenStudio standards set (TMY3, CWEC, or CZ2010). It is not the actual year of the bills. The run records the station id and replaces the site location and design days. One annual run of this small office is about ten seconds, so the default grid is tens of minutes. A wider grid or a larger model is the long job the worker is for.

The API does not run that sweep inline. Start the worker next to the API:

```bash
docker compose --profile energyplus up --build -d
```

CI runs two three-day simulations (`pytest -m energyplus`), not the full grid. `make test` skips that marker.

An ROI what-if on a screening model stays in that model, is labeled screening, and is annualized only after 12 usable months. Trimming run hours changes fan energy only. A what-if on an EnergyPlus calibration reruns each Guideline 14 passing member as its own baseline and its own altered case. The savings band is the 10th to 90th percentile.

A policy stores its engine. `POST /v1/scheduler/tick` enqueues what is due. EnergyPlus tracking reruns the calibrated case on the nearest typical year (not the actual month's weather). Three of the last six tracking results outside the monthly limits enqueue a recalibration with that same engine. The worker claims a job with a lease (`python -m twin.runner`, `TWIN_INLINE_JOBS=0`). Outbound webhooks are https only, signed as `timestamp.body`.

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

## Generic office EnergyPlus prototype (VAV functional test)

The `models/` tree builds a **parameterized, RDF-driven** two-story VAV office (~9 290 m², Chicago 4A) for HVAC functional-test and FDD prototyping. EnergyPlus **24.2** matches the twin worker image; packaged VAV AHUs are emitted as `HVACTemplate:*` objects and expanded at run time (`energyplus -x`).

**Climate:** ASHRAE **4A**, `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`.

**Two RTUs (one per floor):** each floor has independent peak loads and ducts; separate air loops mirror common rooftop-unit zoning and keep VAV terminal counts manageable (~5 zones × 2 floors).

### Regenerate from RDF, layout JSON, or defaults

```bash
# RDF/Turtle → layout JSON → IDF → simulate → artifacts
export ENERGYPLUS_BIN=/path/to/Energyplus/energyplus
python3 models/run_generic_office.py --ttl models/sample_building.ttl

# Or explicit layout + design overrides
python3 models/build_generic_office_vav.py \
  --layout models/layouts/default_two_story_office.json \
  --design models/generic_office/design_values.json \
  -o models/generated/generic_two_story_office_vav.idf
python3 models/run_generic_office.py --layout models/layouts/default_two_story_office.json
```

Artifacts land in `models/generated/`:

| Output | Purpose |
| --- | --- |
| `generic_two_story_office_vav.idf` | Reproducible model |
| `layout.json` | AHU/VAV/zone graph (from TTL when `--ttl` is used) |
| `design_values.json` | Autosized capacities, fan/pump curves (SI, stable keys) |
| `sizing_summary.md` | Human-readable sizing summary |
| `point_list.csv` | BACnet/Haystack/223P role mapping for sim variables |
| `timeseries_representative_week.csv` | Hourly data for FDD / functional-test dry runs |
| `floor_diagram.md` | Zone / floor sketch |

See `models/generic_office/schema.md` for layout and `design_values.json` key documentation.

## Security

The quickstart binds `127.0.0.1:18080` only and runs with `TWIN_ENV=demo`. It does not bind port 80. `TWIN_ENV=prod` refuses to start when the bootstrap key is missing, is `local-demo-key`, or is shorter than 32 characters, and it refuses an open dashboard. API keys are tenant scoped: a key sees only its tenant's sites, jobs, and webhooks. Put your own TLS proxy in front. Alfalfa is not authenticated upstream, so leave it on the internal network.
