"""Real alfalfa-client 1.0.0 smoke test against a separately running Alfalfa server.

Default: offline import/configuration check. --live: read-only server status.
--control: intentionally write one input and advance one externally clocked test run.
"""
from __future__ import annotations

import argparse
import os
import sys

from alfalfa_client.alfalfa_client import AlfalfaClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Read status from an existing Alfalfa run")
    parser.add_argument("--control", action="store_true", help="Write one test input and advance a run once")
    args = parser.parse_args()
    host = os.environ.get("ALFALFA_URL", "http://localhost")
    client = AlfalfaClient(host)
    print(f"AlfalfaClient initialized for {host}")
    if not (args.live or args.control):
        return 0

    run_id = os.environ.get("ALFALFA_RUN_ID", "")
    if not run_id:
        print("ALFALFA_RUN_ID is required for live tests", file=sys.stderr)
        return 2
    print(f"Run {run_id}: {client.status(run_id)}")
    if args.control:
        name = os.environ.get("ALFALFA_CONTROL_INPUT", "")
        value = os.environ.get("ALFALFA_CONTROL_VALUE", "")
        if not name or not value:
            print("Set ALFALFA_CONTROL_INPUT and ALFALFA_CONTROL_VALUE", file=sys.stderr)
            return 2
        if name not in client.get_inputs(run_id):
            print(f"Input not found: {name}", file=sys.stderr)
            return 2
        client.set_inputs(run_id, {name: float(value)})
        client.advance(run_id)
        print(f"Advanced externally clocked test run once after writing {name}")
    else:
        print("Available inputs:", client.get_inputs(run_id))
        print("Outputs:", client.get_outputs(run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
