# Active checkpoint: REAL Alfalfa integration (2026-11-26)

User clarified actual upstream Alfalfa is the entire point. The previous direct
EnergyPlus default was unsuitable and is now optional standalone only.

Default compose includes unmodified upstream compose at commit
6c76e0b04fccc1fcbf64f8304bf622bc26710368 with deployment-only overrides:
loopback ports, persistent volumes, S3 external hostname, official image digests.
Official web/worker, Mongo, Redis, MinIO and mc are running. Official worker is
OpenStudio 3.9 / EnergyPlus 24.2. No application patches or version substitutions.
Core web/index.js and worker/step_run.py match pinned source after CRLF normalization.

A separate custom telemetry client uses alfalfa-client==1.0.0 and the unmodified
upstream schedule_model fixture. Its writes/readbacks and clock are Alfalfa API
calls. Runtime is retained observation, not a setpoint. No GL14 certification.

Verified: official upload -> preprocessing -> READY -> RUNNING -> three distinct
thermostat overrides with matching readbacks -> one-minute clock advances ->
zone outputs -> stop COMPLETE. Run a4eb9d10-e9d0-11f1-bb6d-8da2cff8362b.
Official archive download through Alfalfa/MinIO returned HTTP 200, gzip content.
/redoc returns 200; upstream /docs is 404 (do not patch upstream to hide this).
Contract tests: three passed in telemetry container.

Full replay running: client job 38f0833c-0c0b-48e4-94eb-199d2f0367f3,
Alfalfa run cbb4a900-e9d0-11f1-bb6d-8da2cff8362b, 96 x 15 minutes / 1440 steps.
Check GET localhost:8088/replays/{job}, artifact progress.json, or
work/alfalfa-telemetry-demo.log. Do not restart telemetry while this is active.

New backend adds official archive download after stop, but running container
still has the earlier imported function. Once replay completes, rebuild telemetry
and run the updated official smoke (includes tar verification). Then update this
checkpoint with final evidence and push. User authorized commit/push checkpoints.

Windows host.docker.internal resolves to an inaccessible IP on this machine;
containers can use it. Therefore expose downloaded official archive through the
telemetry artifact endpoint for Windows users. Do not modify Windows hosts/DNS.
No local-worker inference used. Unrelated PostgreSQL containers untouched.

## Completed verification checkpoint

Full replay COMPLETED: 96 intervals / 1440 official minute advances, last clock
2025-07-08 00:00:00. Both thermostat schedule readbacks matched every advance.
Official archive contains 60 entries. Download through the telemetry artifact
endpoint succeeded from Windows (2,026,640 bytes).

Updated smoke (archive validation included) also completed successfully on rebuilt
client: Alfalfa run 618d8fa0-e9d1-11f1-bb6d-8da2cff8362b. Log:
work/alfalfa-final-smoke.log; durable evidence /data/alfalfa-smoke.json and
/data/alfalfa-smoke.tar.gz in the Docker client volume. Three contract tests pass.

Canonical Dockerfile is now the lightweight client; prior EPlus image is only
Dockerfile.standalone. Added PYTHONPATH=/app for standalone example invocation.
A final client image rebuild is in progress (session 19859); log
work/client-final-build.log. Once build finishes, start telemetry with
`docker compose up -d --no-build --no-deps telemetry` and confirm healthy.
The user reiterated commit/push now and continue autonomous verification.
