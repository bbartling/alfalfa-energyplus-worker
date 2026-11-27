from datetime import datetime, timezone

import pytest
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
    assert result["decision"] == "screening"
    assert result["engine"]["name"] == "quick-estimate"
    assert result["engine"]["label"] == "screening"
    assert result["engine"]["claim"] == "screening"
    truth = spec["truth"]
    for name, value in truth.items():
        assert result["parameters"][name] == pytest.approx(value, rel=0.15)
    assert all(item["claim"] == "screening" and item["pass"] is None for item in result["metrics"])
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
    assert priced["annualized"] is True
    assert priced["label"] == "screening"
    assert priced["claim"] == "screening"
    assert priced["simple_payback_years"] > 0
    low, high = priced["cost_savings_band_usd"]
    assert low <= priced["annual_cost_savings_usd"] <= high
    page = client.get(f"/sites/{spec['site_id']}")
    assert "CV(RMSE)" in page.text and "NMBE" in page.text and "NPV" in page.text
    assert "Screening estimate" in page.text
    assert "Guideline 14" not in page.text
    coverage = client.get(
        f"/v1/sites/{spec['site_id']}/coverage",
        headers=auth,
        params={"start": "2025-03-01T00:00:00Z", "end": "2026-05-01T00:00:00Z"},
    ).json()
    assert "2025-03" in coverage["months_missing"]
    assert "2025-04" in coverage["months_present"]


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
                    tenant_id="local",
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


def test_energyplus_rejects_a_building_the_prototype_does_not_represent(client, auth):
    spec = SITES[1]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    rejected = client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth, params={"engine": "energyplus"})
    assert rejected.status_code == 422
    other = site_record(SITES[0]) | {"site_id": "site-vav", "system_type": "vav"}
    client.post("/v1/sites", json=other, headers=auth)
    assert client.post("/v1/sites/site-vav/calibrations", headers=auth, params={"engine": "energyplus"}).status_code == 422


def test_energyplus_calibration_is_queued_for_the_worker(client, auth):
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False):
        client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth)
    queued = client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth, params={"engine": "energyplus"})
    assert queued.status_code == 202
    body = queued.json()
    assert body["status"] == "queued"
    assert body["kind"] == "energyplus-calibration"
    assert client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth, params={"engine": "other"}).status_code == 422


def test_energyplus_what_if_is_queued_until_the_worker_runs_it(client, auth):
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    from twin.db import ModelVersion
    from twin.eplus_calibrate import base_case

    with client.app.state.Session() as session:
        session.add(
            ModelVersion(
                id="ep-model",
                tenant_id="local",
                site_id=spec["site_id"],
                status="active",
                parameters=base_case(),
                ensemble=[base_case()],
                metrics=[],
                engine={"name": "energyplus", "label": "EnergyPlus"},
            )
        )
        session.commit()
    queued = client.post(
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
    assert queued.status_code == 202
    assert queued.json()["kind"] == "energyplus-scenario"
    assert queued.json()["status"] == "queued"


def test_a_tenant_star_key_cannot_read_another_tenant(client, auth):
    import hashlib

    from twin.db import ApiKey

    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False):
        client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth)
    job = client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth)
    token = "other-tenant-key"
    with client.app.state.Session() as session:
        session.add(
            ApiKey(
                key_hash=hashlib.sha256(token.encode()).hexdigest(),
                tenant="other",
                sites=["*"],
                label="other",
            )
        )
        session.commit()
    other = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/v1/sites/{spec['site_id']}", headers=other).status_code == 404
    assert client.get(f"/v1/sites/{spec['site_id']}/report", headers=other).status_code == 404
    assert client.get(f"/v1/jobs/{job.json()['id']}", headers=other).status_code == 404
    assert client.get("/").text.find(spec["site_id"]) != -1
    denied = client.get("/", headers=other)
    assert spec["site_id"] not in denied.text


def test_webhook_events_stay_inside_the_tenant(client, auth, monkeypatch):
    from twin.db import Webhook

    seen = []

    def fake_post(url, **kwargs):
        seen.append(url)

    monkeypatch.setattr("httpx.post", fake_post)
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False):
        client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth)
    registered = client.post(
        "/v1/webhooks",
        json={"url": "http://tenant-a.example/hook", "secret": "tenant-a-secret", "events": ["job.completed"]},
        headers=auth,
    )
    assert registered.status_code == 201
    with client.app.state.Session() as session:
        session.add(
            Webhook(
                tenant_id="other",
                url="http://tenant-b.example/hook",
                secret="tenant-b-secret",
                events=["job.completed"],
            )
        )
        session.commit()
    assert client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth).status_code == 200
    assert seen == ["http://tenant-a.example/hook"]


def test_prod_refuses_the_demo_key_and_an_open_dashboard(tmp_path):
    from twin.factory import create_app
    from twin.settings import Settings

    common = {
        "database_url": f"sqlite:///{tmp_path}/prod.db",
        "inline_jobs": True,
        "alfalfa_url": None,
        "env": "prod",
    }
    with pytest.raises(RuntimeError):
        create_app(Settings(bootstrap_key="local-demo-key", dashboard_open=False, **common))
    with pytest.raises(RuntimeError):
        create_app(Settings(bootstrap_key="x" * 40, dashboard_open=True, **common))


def test_live_alfalfa_is_optional(client, auth):
    response = client.post("/v1/sites/site-cold-office/live-runs", headers=auth)
    assert response.status_code == 404
    client.post("/v1/sites", json=site_record(SITES[0]), headers=auth)
    response = client.post(f"/v1/sites/{SITES[0]['site_id']}/live-runs", headers=auth)
    assert response.status_code == 409
