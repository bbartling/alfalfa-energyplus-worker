# Docker HVAC telemetry / EnergyPlus twin prototype

Local daily batch replay: an IoT server posts thermostat setpoints, HVAC runtime,
and zone temperature summaries. A serial worker runs real EnergyPlus 26.1.0 in
Docker and retains observations, model provenance, logs, and comparisons.
No host Python or EnergyPlus is required.

## Run in PowerShell

```powershell
docker compose up -d --build
docker compose exec -T twin python -m unittest discover -s tests -v
docker compose exec -T twin python examples/demo.py
```

API documentation: http://localhost:8088/docs
The demo uses synthetic observations, not measured building data.

## API contract

POST /replays accepts site_id, model_id (demo-five-zone-v1), and intervals.
Each interval contains timestamp, heating_setpoint_c, cooling_setpoint_c,
optional zone_temperature_mean_c, and optional hvac_runtime_seconds.
See examples/demo.py for a complete payload and the generated API docs for schema.

Supply exactly 96 contiguous 15-minute records for one full 2025 day, beginning
at midnight. Timestamps mark interval starts in building-local standard time,
without DST or UTC offsets. Temperatures are Celsius; runtime is seconds within
that interval (0–900). Heating must be below cooling. Unknown fields, invalid
values, gaps, duplicate timestamps, and unregistered models are rejected.

GET /replays/{id} reports queued/running/completed/failed and returns comparisons
on completion. GET /replays/{id}/artifacts/{name} downloads request.json,
provenance.json, results.json, model.epJSON, process.log, eplusout.err, or
eplusout.csv. Data persists in the Compose named volume. At most four jobs are
active, with one simulation at a time and a 180-second subprocess timeout.
Interrupted jobs are marked failed on restart; resubmit them. Submissions are
append-only with no deduplication or automatic retry. Use one API process.

## Demo assumptions

The bundled upstream 5Zone_IdealLoadsAirSystems_ReturnPlenum.idf is converted to
epJSON inside Docker. The adapter replaces Htg-SetP-Sch and Clg-SetP-Sch with
15-minute file schedules. These control ALL FIVE zones; only SPACE1-1 is compared
to the supplied temperature summaries. The daily pattern repeats across a
non-leap schedule year and warmup; only the requested day is simulated. Each job
starts fresh, without thermal state carried between days. Weather is Chicago
TMY, not measured site weather.

Runtime is an observed outcome, not a thermostat temperature. It is retained but
not inferred into a setpoint. This ideal-loads model does not predict compressor
runtime or compressor electricity. Actual buildings need a registered zone and
equipment mapping and suitable HVAC model. Arbitrary IDF uploads are unsupported.

## Calibration path / Guideline 14

Temperature RMSE and bias in Celsius are diagnostics. Guideline 14 compliance is
explicitly not assessed. No parameter optimizer is implemented.
Next: register the real building model, use actual-period weather, ingest metered
energy, version bounded parameters (envelope, gains, infiltration, capacity,
efficiency), and evaluate candidates on training and held-out periods.
Align energy observations and predictions at the same interval and meter boundary
before computing NMBE and CV(RMSE), with documented parameter-count conventions
and an agreed M&V plan. References:

- [FEMP M&V Guidelines 5.0](https://www.energy.gov/sites/default/files/2024-10/mv_guide_5_0.pdf)
- [ASHRAE Standard 209 addendum j](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20addenda/209_2018_j_20240930.pdf)

## Operations

```powershell
docker compose logs --tail 50
docker compose down
```

Down preserves artifacts; down -v deletes them. The service binds only to
localhost. A remote IoT deployment needs authentication, TLS, ingress, and tenant
isolation. The matching Linux examples and weather are included in the image;
the Windows EnergyPlus installation and unrelated containers are untouched.

## Original Alfalfa workflow

start-local.ps1, pacer_experiment.py, and requirements.txt preserve the previous
upstream Alfalfa launcher/client workflow. Run ./start-local.ps1 separately for
that stack. This replay service calls EnergyPlus directly and does not implement
or exercise the Alfalfa API. It isolates the telemetry/model-mapping experiment.
