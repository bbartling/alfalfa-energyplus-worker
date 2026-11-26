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
