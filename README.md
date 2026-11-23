# Alfalfa deployment and controls experiments

This repository is a **thin deployment and experimentation wrapper** for the official laboratory-maintained [Alfalfa virtual building service](https://github.com/NatLabRockies/alfalfa). It does **not** implement a custom EnergyPlus or Alfalfa API.

- Official server: https://github.com/NatLabRockies/alfalfa
- Official Python client (renamed): https://github.com/NatLabRockies/alfalfa-client
- Official examples: https://github.com/NatLabRockies/alfalfa-notebooks

## Local (recommended first)

Install Docker Desktop and Git. In PowerShell:

```powershell
.\start-local.ps1
```

The script clones the official source at a pinned commit and starts its Docker Compose stack, including web, worker, MongoDB, Redis and MinIO. API docs: http://localhost/docs. The first build can be large and slow.

In another terminal:

```powershell
python -m pip install pacer-client
python .\pacer_experiment.py --host http://localhost --check
```

For a real model, follow the official notebooks to prepare an Alfalfa-compatible model folder and run:

```powershell
python .\pacer_experiment.py --host http://localhost --model .\path\to\model --steps 3
```

Optional controls: `--input-name "EXPOSED_POINT_NAME" --input-value 22`. The client prints available point names. Do not assume an IDF automatically exposes writable points.

## Render

`Dockerfile` now uses the **official Alfalfa web image**; the previous FastAPI batch service has been deleted. `render.yaml` describes only the public-facing web service. **It is not a complete production Alfalfa deployment.** It requires a separately deployed Alfalfa worker, Redis, MongoDB and S3-compatible object storage, plus correct Render environment variables and network routing. Until those dependencies are configured, a Render build or startup may fail. Auto-deploy on GitHub push does **not** imply the official Alfalfa API is healthy.

Do not deploy with the upstream example passwords or expose development MinIO/MongoDB/Redis publicly. Secure credentials and persistent storage are required before public deployment. The web and worker image tags must be tested together and ideally pinned to immutable image digests for production.

The legacy endpoints `/healthz`, `/v1/jobs`, and the Pong prototype are intentionally removed. The official Alfalfa API uses `/api/v2/`. No V1/V2 compatibility shim is maintained in this repository.

## Upstream provenance

Local checkout is pinned to Alfalfa commit `6c76e0b04fccc1fcbf64f8304bf622bc26710368` on the laboratory's `develop` branch as inspected 2026-11-23. The Render image currently uses the upstream `latest` tag pending an image digest pin; this is a limitation to resolve before claiming reproducibility.
