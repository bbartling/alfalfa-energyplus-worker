"""Exercise the OFFICIAL Alfalfa REST API via the upstream pacer-client.

Requires the locally running official Alfalfa Docker Compose stack.
The supplied model must be an upstream-compatible model folder or file.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://localhost", help="Real Alfalfa server URL")
    parser.add_argument("--check", action="store_true", help="Check API reachability without submitting a model")
    parser.add_argument("--model", type=Path, help="Upstream-compatible EnergyPlus model folder or file")
    parser.add_argument("--start", default="2024-07-01T00:00:00")
    parser.add_argument("--end", default="2024-07-02T00:00:00")
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--input-name", help="Exposed control point name")
    parser.add_argument("--input-value", type=float, help="Value for exposed control point")
    args = parser.parse_args()

    from pacer_client.pacer_client import PacerClient

    client = PacerClient(args.host)
    print("Official Alfalfa API:", client.url)
    if args.check:
        import requests
        response = requests.get(args.host.rstrip("/") + "/docs", timeout=30)
        response.raise_for_status()
        print("API documentation endpoint:", response.status_code)
        return 0
    if not args.model or not args.model.exists():
        parser.error("--model must refer to an existing Alfalfa-compatible model")
    if args.steps < 1:
        parser.error("--steps must be at least 1")
    if (args.input_name is None) != (args.input_value is None):
        parser.error("--input-name and --input-value must be supplied together")
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if end <= start:
        parser.error("--end must be after --start")

    print("Submitting:", args.model)
    run_id = client.submit(str(args.model))
    print("Run ID:", run_id)
    started = False
    try:
        client.start(run_id, start, end, external_clock=True)
        started = True
        print("Inputs:", json.dumps(client.get_inputs(run_id), indent=2))
        if args.input_name is not None:
            available = client.get_inputs(run_id)
            if args.input_name not in available:
                raise ValueError(f"Input {args.input_name!r} not exposed by model; available: {available}")
            client.set_inputs(run_id, {args.input_name: args.input_value})
            print("Wrote control:", args.input_name, args.input_value)
        for step in range(1, args.steps + 1):
            client.advance(run_id)
            print(json.dumps({
                "step": step,
                "sim_time": str(client.get_sim_time(run_id)),
                "outputs": client.get_outputs(run_id),
            }, indent=2, default=str))
    finally:
        if started:
            print("Stopping simulation", run_id)
            client.stop(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
