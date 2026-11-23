# Official laboratory Alfalfa integration

This directory is a **deployment/experiment wrapper**, not a fork or reimplementation of Alfalfa.

Upstream source: https://github.com/NatLabRockies/alfalfa
Upstream client: https://github.com/NatLabRockies/alfalfa-client
Upstream notebooks: https://github.com/NatLabRockies/alfalfa-notebooks

## Run upstream Alfalfa locally (Windows PowerShell + Docker Desktop)

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\upstream\start-local.ps1
```

The script checks out the **reviewed upstream commit** (see the SHA in the script), copies upstream's .env to a local ignored file location only when needed, and runs the upstream Docker Compose stack **without changing upstream source**. Upstream docs: http://localhost/docs. Ensure Docker Desktop is running and has enough RAM/disk for the scientific worker images. The first build may take a long time.

The upstream .env contains example credentials for local development only. **Never expose this stack to the internet with those credentials.** Review the upstream security and persistence configuration before any cloud deployment.

## Python API integration

```powershell
python -m pip install pacer-client
python .\upstream\pacer_experiment.py --host http://localhost --check
```

To exercise an actual EnergyPlus model, prepare a model folder compatible with upstream Alfalfa (see upstream notebooks for examples), then:

```powershell
python .\upstream\pacer_experiment.py --host http://localhost --model .\path\to\model_folder --start 2024-07-01T00:00:00 --end 2024-07-02T00:00:00 --steps 3
```

The script uploads, creates and starts an externally-clocked run, lists exposed points, advances simulation time, reads outputs and stops the run. Add `--input-name` and `--input-value` to write a point **only after confirming it is exposed by the model**. The script deliberately does not assume a universal thermostat point name.

## Render status

The existing Render service remains the **legacy EnergyPlus batch worker**. Its `/healthz` and `/v1/jobs` endpoints are not the Alfalfa API. This commit intentionally does not change `Dockerfile` or `render.yaml`: a single Render Docker web service cannot substitute for Alfalfa's web, worker, MongoDB, Redis and S3-compatible storage services. A production Render rollout needs separate services, persistent databases/object storage, networking, security and image/build compatibility validation. **Do not point pacer-client at the legacy Render URL.**

Upstream dependency versions and client interfaces can change. The bootstrap script pins the server source SHA for reproducibility; install a compatible pacer-client release for your chosen upstream server version.
