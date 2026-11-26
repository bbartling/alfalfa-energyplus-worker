# Verified checkpoint: upstream Alfalfa (2026-11-26)

User explicitly wants actual Alfalfa and authorized commit/push checkpoints and
continued autonomous testing. All requested prototype integration work below is
finished. No inference helper was started. Unrelated containers were untouched.

## Running implementation

Default compose includes upstream checkout 6c76e0b04fccc1fcbf64f8304bf622bc26710368.
Upstream checkout is clean. Official web/worker images are pinned by digest in
alfalfa.local.yaml. Actual runtime source in those published images matches
upstream af3caee5036d6c6ac10558307d7fd31fe12857de (37 worker + 7 web files audited,
zero mismatches; python tools/audit_upstream.py). Do NOT claim the images are built
from the newer Compose/fixture checkout. No Alfalfa code was patched.

Actual upstream web, worker, Redis, Mongo, MinIO S3, and mc bucket initializer.
Worker uses upstream OpenStudio 3.9 / EnergyPlus 24.2, not host EnergyPlus 26.1.
Custom code is only a separate external telemetry client using official
alfalfa-client==1.0.0. It does not launch EnergyPlus or rewrite model schedules.
Prior direct-EPlus prototype remains optional standalone, stopped, data preserved.

## Completed verification

- Three unmodified upstream integration tests PASSED in 102.96 seconds:
  schedule point creation, schedule overrides, Python EMS I/O enable/disable and
  null actuator release. Separate disposable test image; upstream tests read-only.
  Reproduce: docker compose --profile verification build integration;
  docker compose --profile verification run --rm --no-deps integration.
- Three telemetry contract tests PASSED.
- Full POST daily replay COMPLETED 96 intervals / 1440 official minute advances.
  Client job 38f0833c-0c0b-48e4-94eb-199d2f0367f3; Alfalfa run
  cbb4a900-e9d0-11f1-bb6d-8da2cff8362b. Last clock 2025-07-08 00:00:00.
  Both thermostat schedule readbacks matched every advance.
- Official archive downloaded from Alfalfa/MinIO, 60 entries, 2,026,640 bytes;
  both telemetry artifact endpoint and direct Windows signed S3 redirect worked.
- Final official smoke after S3 hostname change COMPLETED:
  1f2fb420-e9d2-11f1-96f4-abf78e9aeb42. Three thermostat changes, exact minute
  clock advances, zone outputs, stop COMPLETE, and archive validated.
  Durable /data/alfalfa-smoke.json and /data/alfalfa-smoke.tar.gz in client volume.
- Final ./start-local.ps1 launcher test PASSED. Client healthy, services running.

## Configuration and scope

S3_URL_EXTERNAL=http://kubernetes.docker.internal:9000. Docker Desktop already maps
that hostname to Windows loopback. Compose maps it to host-gateway in client/test
containers. Verified HTTP and signed download from both environments. No Windows
DNS/hosts edits or S3 URL/signature rewrites. No Kubernetes cluster needed.
Ports are localhost only: Alfalfa 80, client 8088, MinIO 9000; DBs internal.
Alfalfa /redoc is 200; published upstream /docs is 404. Do not patch upstream to
hide that. Volumes persist metadata/artifacts. Default local dev credentials.

Use ./start-local.ps1. It pulls official images, builds ONLY the client, stops
legacy standalone demo without deleting its data, and starts no-build. Never
use combined up --build (would rebuild included upstream images). Optional
integration profile builds separate tooling, not the running worker.

Demo is an unmodified upstream schedule_model, not the real building. Two schedules
control one fixture zone, all zone temperatures retained, no guessed sensor map.
Runtime remains an observation. No GL14 compliance/certification claim. Future
product work: actual building/sensor/equipment adapter, measured weather and
metered energy, state continuity, versioned calibration, held-out validation.

Evidence logs under ignored work/: upstream-tests.log, alfalfa-final-dns-smoke.log,
alfalfa-telemetry-demo.log, launcher-verification.log, upstream-source-audit.json.
No simulations or test jobs remain running. Final commit/push follows this note.
