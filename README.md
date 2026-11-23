# Local Alfalfa + EnergyPlus playground

This is a small **local-only** experiment harness for the official [Alfalfa virtual building service](https://github.com/NatLabRockies/alfalfa), maintained by the national laboratory. There is no custom FastAPI backend, Render deployment, or API version compatibility layer here.

Alfalfa itself uses five Docker Compose services: web API, simulation worker, Redis, MongoDB, and MinIO. They all run **on your computer**; you do not need AWS S3 or a hosted database.

## Prerequisites

- Windows PowerShell, Git, and Docker Desktop (Linux containers + Docker Compose)
- Python 3.10+ for the optional client example
- Free disk space for large simulation images; allow at least 8 GB RAM as a starting point

## Start the official stack

Clone this repository and run from its root:

```powershell
git clone https://github.com/bbartling/alfalfa-energyplus-worker.git
cd alfalfa-energyplus-worker
.\start-local.ps1
```

The script clones the **unmodified upstream Alfalfa repository** into `_alfalfa_upstream/`, checks out pinned commit `6c76e0b04fccc1fcbf64f8304bf622bc26710368`, and runs `docker compose up --build` using upstream's own `docker-compose.yml` and `.env`. The first run can take a long time and use substantial disk space.

- API docs: http://localhost/docs
- Web: http://localhost/
- MinIO: http://localhost:9000

**Security:** Upstream's example `.env` uses development credentials and exposes ports. This setup is for a trusted local development computer only; do not expose these services to the public internet or forward their ports.

## Test the Python client

Open a **second** PowerShell terminal in the repository directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\pacer_experiment.py --check
```

To submit a model prepared according to the [official Alfalfa notebooks](https://github.com/NatLabRockies/alfalfa-notebooks):

```powershell
python .\pacer_experiment.py --model .\path\to\compatible-model --steps 3
```

The script can optionally set an exposed model input using `--input-name` and `--input-value`. An arbitrary EnergyPlus IDF may need preparation to expose controls before it works with the Alfalfa API.

## Stop / reset

From another PowerShell terminal:

```powershell
cd .\_alfalfa_upstream
docker compose down
```

To **delete local volumes and simulation metadata** as well, use `docker compose down -v` (destructive).

## What is and isn't provided

- **Provided:** local launcher and an example using the official `pacer-client` package.
- **Not provided:** a hosted service, a custom REST API, a prepackaged EnergyPlus model, or verified end-to-end simulation results.
- **Upstream:** https://github.com/NatLabRockies/alfalfa
- **Python client:** https://github.com/NatLabRockies/alfalfa-client

This repository does not modify or vendor the national laboratory's source code.
