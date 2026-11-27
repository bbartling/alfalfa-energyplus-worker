# A simpler alternative

The workload in [data-contract.md](data-contract.md) is a weekly or monthly JSON post and a batch calibration against monthly meters. That does not need a co-simulation cluster.

## This repository

| Piece | Role |
|---|---|
| Twin API + Postgres | Sites, summaries, calibration, ROI, HTML report |
| Summary energy model | Quickstart calibration from run hours, setpoints, and degree days |
| Optional OpenStudio runner | Same Guideline 14 math on EnergyPlus meter output for long batch runs |
| Optional Alfalfa | Unmodified upstream web, worker, MongoDB, Redis, and MinIO for a live model |

Alfalfa's own images are several gigabytes. The stack idles around 1 GB of RAM and publishes internal services that have no authentication upstream. Calibration through Alfalfa is the wrong tool: it steps one minute at a time and a simulated year takes hours, while a batch EnergyPlus run of the same engine version takes seconds to a few minutes.

## One container

A single FastAPI process plus the EnergyPlus or OpenStudio CLI, with SQLite or a managed Postgres, is enough for the contract:

- accept the same JSON summaries
- infer setpoints the same way
- run a batch model (the summary model, or `openstudio` / `energyplus` on `nrel/openstudio:3.9.0`)
- compute CV(RMSE) and NMBE
- price what-ifs
- serve the site report

On a simple PaaS (Render is a typical example) that is one web service, one bill, and the platform's TLS proxy. The image is large because EnergyPlus is large, but there is still one process to patch. A background job on the same service can run a calibration that takes hours.

Rough cost, as an order of magnitude: a small PaaS instance is the price of one modest web service. The Alfalfa VM has to be big enough for MongoDB, Redis, MinIO, the worker, and the twin, and someone has to upgrade those images together.

## What you give up without Alfalfa

- Changing points while a simulation is running (a setpoint write every minute)
- Sub-hourly grid response at a 1-minute timestep
- The upstream virtual-building UI

You do not give up monthly calibration, Guideline 14 on metered energy, schedules and setpoints driven by FDD summaries, or ROI.

## Recommendation

Ship the single-container batch service. That is the quickstart in this repo. Add Alfalfa only when an operator needs a live model with point writes. Do not send calibration sweeps or annual ROI runs through Alfalfa.
