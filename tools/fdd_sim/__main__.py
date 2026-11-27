"""Historical backfill, then one incremental push, for two or more sites."""

from __future__ import annotations

import os
import sys
import time

import httpx

from tools.fdd_sim.deliver import post_json
from tools.fdd_sim.synthetic import SITES, batches_for, site_record

API = os.environ.get("TWIN_API_URL", "http://127.0.0.1:18080")
KEY = os.environ.get("TWIN_API_KEY", "local-demo-key")


def main() -> int:
    deadline = time.time() + 90
    with httpx.Client(timeout=30) as client:
        while True:
            try:
                health = client.get(f"{API}/health")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.time() > deadline:
                print("API did not become ready", file=sys.stderr)
                return 1
            time.sleep(0.5)
        for spec in SITES:
            _deliver_site(client, spec)
        _assert_isolation(client)
        page = client.get(f"{API}/")
        page.raise_for_status()
        for spec in SITES:
            if spec["site_id"] not in page.text or "CV(RMSE)" not in page.text or "screening" not in page.text.lower():
                print("dashboard is missing a site or the screening estimate", file=sys.stderr)
                return 1
            if "Guideline 14" in page.text:
                print("the quick estimate is presented as Guideline 14", file=sys.stderr)
                return 1
    print("Poster delivered two sites and the reports show a screening estimate.")
    return 0


def _deliver_site(client: httpx.Client, spec: dict) -> None:
    created = post_json(client, f"{API}/v1/sites", site_record(spec), KEY)
    if created.status_code not in (200, 201):
        raise RuntimeError(created.text)
    history = batches_for(spec, include_incremental=False)
    first = post_json(client, f"{API}/v1/sites/{spec['site_id']}/operations", history[0], KEY)
    _expect(first, 200)
    again = post_json(client, f"{API}/v1/sites/{spec['site_id']}/operations", history[0], KEY)
    body = again.json()
    if not body.get("duplicate"):
        raise RuntimeError("re-posting a batch must be a no-op")
    for batch in history[1:]:
        _expect(post_json(client, f"{API}/v1/sites/{spec['site_id']}/operations", batch, KEY), 200)
    calibrated = post_json(client, f"{API}/v1/sites/{spec['site_id']}/calibrations", None, KEY)
    _expect(calibrated, 200)
    result = calibrated.json()["result"]
    if result["decision"] != "screening" or result["engine"].get("claim") != "screening":
        raise RuntimeError(f"{spec['site_id']} was not kept as a screening estimate: {calibrated.text}")
    for name, value in spec["truth"].items():
        recovered = result["parameters"][name]
        if abs(recovered - value) / value > 0.2:
            raise RuntimeError(f"{spec['site_id']} {name} recovered {recovered}, truth {value}")
    scenario = {
        "name": "Raise occupied cooling setpoint 1 C",
        "measures": [{"name": "raise_cooling_setpoint", "delta_c": 1.0}],
        "costs": {
            "implementation_usd": 2500,
            "electricity_usd_per_kwh": 0.14,
            "gas_usd_per_therm": 1.1,
            "discount_rate": 0.05,
            "horizon_years": 10,
        },
    }
    _expect(post_json(client, f"{API}/v1/sites/{spec['site_id']}/scenarios", scenario, KEY), 200)
    incremental = batches_for(spec, include_incremental=True)[-1]
    _expect(post_json(client, f"{API}/v1/sites/{spec['site_id']}/operations", incremental, KEY), 200)
    report = client.get(f"{API}/v1/sites/{spec['site_id']}/report", headers={"Authorization": f"Bearer {KEY}"})
    report.raise_for_status()
    payload = report.json()
    if payload["months_received"] < 14:
        raise RuntimeError("incremental month was not stored")
    sat = [item for item in payload["setpoints"] if item["kind"] == "supply_air_temp"]
    if not sat or sat[0]["source"] != "inferred" or abs(sat[0]["value"] - spec["sat"]) > 0.05:
        raise RuntimeError(f"supply air setpoint was not inferred: {sat}")
    duct = [item for item in payload["setpoints"] if item["kind"] == "duct_static"]
    if not duct or duct[0]["source"] != "actual" or duct[0]["value"] != 375:
        raise RuntimeError(f"actual duct static setpoint was overwritten: {duct}")
    html = client.get(f"{API}/sites/{spec['site_id']}")
    html.raise_for_status()
    if "CV(RMSE)" not in html.text or "NMBE" not in html.text or "NPV" not in html.text:
        raise RuntimeError("site report is missing calibration or ROI")
    if "Guideline 14" in html.text or "Screening estimate" not in html.text:
        raise RuntimeError("site report must label the quick estimate as screening")


def _assert_isolation(client: httpx.Client) -> None:
    minted = post_json(client, f"{API}/v1/api-keys", {"site_ids": ["site-cold-office"]}, KEY)
    _expect(minted, 201)
    scoped = minted.json()["api_key"]
    denied = client.get(
        f"{API}/v1/sites/site-mixed-office/report",
        headers={"Authorization": f"Bearer {scoped}"},
    )
    if denied.status_code != 403:
        raise RuntimeError("a site key was able to read another site")


def _expect(response: httpx.Response, status: int) -> None:
    if response.status_code != status:
        raise RuntimeError(f"expected {status}, got {response.status_code}: {response.text}")


if __name__ == "__main__":
    raise SystemExit(main())
