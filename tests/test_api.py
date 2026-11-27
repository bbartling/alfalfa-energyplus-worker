from datetime import datetime, timezone

from tools.fdd_sim.synthetic import SITES, batches_for, site_record


def test_rejects_missing_key_raw_telemetry_and_other_sites(client, auth):
    assert client.get("/v1/sites/missing", headers=auth).status_code == 404
    assert client.post("/v1/sites", json=site_record(SITES[0])).status_code == 401
    client.post("/v1/sites", json=site_record(SITES[0]), headers=auth)
    batch = batches_for(SITES[0], include_incremental=False)[0]
    batch["records"] = [{"point_id": "raw"}]
    rejected = client.post(f"/v1/sites/{SITES[0]['site_id']}/operations", json=batch, headers=auth)
    assert rejected.status_code == 422
    minted = client.post("/v1/api-keys", json={"site_ids": ["site-cold-office"]}, headers=auth)
    scoped = {"Authorization": f"Bearer {minted.json()['api_key']}"}
    assert client.get("/v1/sites/site-mixed-office", headers=scoped).status_code == 403


def test_infers_setpoints_calibrates_and_prices_a_what_if(client, auth):
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    history = batches_for(spec, include_incremental=False)
    first = client.post(f"/v1/sites/{spec['site_id']}/operations", json=history[0], headers=auth)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    again = client.post(f"/v1/sites/{spec['site_id']}/operations", json=history[0], headers=auth)
    assert again.json()["duplicate"] is True
    changed = dict(history[0])
    changed["weather"] = dict(history[0]["weather"], drybulb_mean_c=99)
    conflict = client.post(f"/v1/sites/{spec['site_id']}/operations", json=changed, headers=auth)
    assert conflict.status_code == 409
    for batch in history[1:]:
        assert client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth).status_code == 200
    report = client.get(f"/v1/sites/{spec['site_id']}/report", headers=auth).json()
    sat = next(item for item in report["setpoints"] if item["kind"] == "supply_air_temp")
    assert sat["source"] == "inferred"
    assert sat["value"] == spec["sat"]
    duct = next(item for item in report["setpoints"] if item["kind"] == "duct_static")
    assert duct["source"] == "actual"
    assert duct["value"] == 375
    heating = next(item for item in report["setpoints"] if item["kind"] == "zone_heating" and item["period"] == "occupied")
    assert heating["source"] == "inferred"
    assert heating["method"] == "deadband-percentile"
    assert heating["value"] == spec["heating"]
    calibrated = client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth)
    assert calibrated.status_code == 200
    result = calibrated.json()["result"]
    assert result["decision"] == "promoted"
    assert result["parameters"] == {"lighting_w_m2": 10.0, "cooling_cop": 3.5, "infiltration_ach": 0.6}
    assert all(item["pass"] for item in result["metrics"])
    scenario = client.post(
        f"/v1/sites/{spec['site_id']}/scenarios",
        headers=auth,
        json={
            "name": "Raise occupied cooling setpoint 1 C",
            "measures": [{"name": "raise_cooling_setpoint", "delta_c": 1}],
            "costs": {
                "implementation_usd": 2500,
                "electricity_usd_per_kwh": 0.14,
                "gas_usd_per_therm": 1.1,
                "discount_rate": 0,
                "horizon_years": 3,
            },
        },
    )
    assert scenario.status_code == 200
    priced = scenario.json()["result"]
    assert priced["annual_kwh_savings"] > 0
    assert priced["simple_payback_years"] > 0
    low, high = priced["cost_savings_band_usd"]
    assert low <= priced["annual_cost_savings_usd"] <= high
    page = client.get(f"/sites/{spec['site_id']}")
    assert "CV(RMSE)" in page.text and "NMBE" in page.text and "NPV" in page.text
    coverage = client.get(
        f"/v1/sites/{spec['site_id']}/coverage",
        headers=auth,
        params={"start": "2025-10-01T00:00:00Z", "end": "2026-05-01T00:00:00Z"},
    ).json()
    assert "2025-10" in coverage["months_missing"]
    assert "2025-11" in coverage["months_present"]


def test_scheduler_is_idempotent_within_a_month_and_drift_recalibrates(client, auth):
    spec = SITES[1]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False):
        client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth)
    client.post(
        f"/v1/sites/{spec['site_id']}/policies",
        headers=auth,
        json={"cadence": "monthly", "kind": "calibration"},
    )
    moment = datetime(2026, 4, 15, tzinfo=timezone.utc).isoformat()
    first = client.post("/v1/scheduler/tick", headers=auth, params={"now": moment}).json()
    assert any(job["kind"] == "calibration" and job["status"] == "completed" for job in first["jobs"])
    second = client.post("/v1/scheduler/tick", headers=auth, params={"now": moment}).json()
    assert second["jobs"] == []
    from twin.db import Job

    with client.app.state.Session() as session:
        for _ in range(2):
            session.add(
                Job(
                    id=f"track-{_}-{spec['site_id']}",
                    site_id=spec["site_id"],
                    kind="tracking",
                    status="completed",
                    spec={"reason": "test"},
                    result={"metrics": [{"cv_rmse_pct": 42, "nmbe_pct": 12}]},
                    created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                )
            )
        session.commit()
    drifted = client.post(
        "/v1/scheduler/tick",
        headers=auth,
        params={"now": datetime(2026, 4, 28, tzinfo=timezone.utc).isoformat()},
    ).json()
    assert any(job["spec"].get("reason") == "drift" for job in drifted["jobs"])


def test_live_alfalfa_is_optional(client, auth):
    response = client.post("/v1/sites/site-cold-office/live-runs", headers=auth)
    assert response.status_code == 404
    client.post("/v1/sites", json=site_record(SITES[0]), headers=auth)
    response = client.post(f"/v1/sites/{SITES[0]['site_id']}/live-runs", headers=auth)
    assert response.status_code == 409
