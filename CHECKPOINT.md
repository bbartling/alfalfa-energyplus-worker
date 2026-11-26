# Resume checkpoint

User requested Docker-only telemetry/EnergyPlus prototype and future GL14
calibration. User explicitly requested early commit and push due to lean weekly
usage. Branch develop. Scaffold 4a60c84 pushed. No local inference started.

Implementation: app/server.py, compose.yaml, examples/demo.py, contract tests.
Single worker, durable named-volume artifacts, explicit five-zone model mapping,
96 x 15-minute records, one 2025 standard-time day. Runtime is observation;
explicit thermostat setpoints drive schedules. GL14 not assessed. See README.

Verify with docker compose up -d --build, then docker compose exec -T twin python
-m unittest discover -s tests -v, then docker compose exec -T twin python
examples/demo.py. Inspect job process.log and eplusout.err on failure.
Do not touch unrelated PostgreSQL containers. Original Alfalfa launcher retained.

## Verified 2026-11-26

Pushed implementation checkpoint 19251f8. Final Docker integration passed:
- docker compose up -d --build --wait: healthy on 127.0.0.1:8088.
- Three contract tests passed inside Docker.
- POST demo -> job 9d3eb4ca-477d-4e02-b2a3-d8b0b8a7e758 completed.
- Real EnergyPlus returned 96 intervals; both exported setpoint schedules matched
  all submitted intervals. Synthetic temperature RMSE 1.69886 C, bias -1.10287 C.
  These numbers are demo diagnostics, not calibration evidence.
- EnergyPlus 26.1 native CSV produced an extra empty column; use -r / ReadVarsESO.
- libx11-6 is required by the official Linux release and is installed in image.
- Recovery runs in API lifespan, not test imports. Service left running.

Remaining scope: actual building adapter, equipment/runtime prediction, measured
weather and metered energy, longer timelines/state continuity, versioned parameter
calibration and held-out validation. Original Alfalfa stack was not exercised.
