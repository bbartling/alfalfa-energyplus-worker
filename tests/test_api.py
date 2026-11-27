from datetime import datetime, timezone

import pytest
from tools.fdd_sim.synthetic import SITES, batches_for, site_record


def test_request_body_is_capped_at_one_megabyte(client, auth):
    response = client.post("/v1/sites", content=b"{" + b"x" * 1_000_000, headers={**auth, "content-type": "application/json"})
    assert response.status_code == 413


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
    assert heating["method"] == "mode-quantile"
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
        for _ in range(3):
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
    import socket

    from twin.db import Webhook

    seen = []

    def fake_post(url, **kwargs):
        seen.append((url, kwargs["headers"]["X-Twin-Timestamp"]))

    def public_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("twin.webhooks.socket.getaddrinfo", public_dns)
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False):
        client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth)
    registered = client.post(
        "/v1/webhooks",
        json={"url": "https://tenant-a.example/hook", "secret": "tenant-a-secret", "events": ["job.completed"]},
        headers=auth,
    )
    assert registered.status_code == 201
    with client.app.state.Session() as session:
        session.add(
            Webhook(
                tenant_id="other",
                url="https://tenant-b.example/hook",
                secret="tenant-b-secret",
                events=["job.completed"],
            )
        )
        session.commit()
    assert client.post(f"/v1/sites/{spec['site_id']}/calibrations", headers=auth).status_code == 200
    assert [item[0] for item in seen] == ["https://tenant-a.example/hook"]
    assert seen[0][1].isdigit()
    refused = client.post(
        "/v1/webhooks",
        json={"url": "https://127.0.0.1/hook", "secret": "tenant-a-secret", "events": ["job.completed"]},
        headers=auth,
    )
    assert refused.status_code == 422
    plain = client.post(
        "/v1/webhooks",
        json={"url": "http://tenant-a.example/hook", "secret": "tenant-a-secret", "events": ["job.completed"]},
        headers=auth,
    )
    assert plain.status_code == 422


def test_a_submeter_a_short_period_and_an_overlap_do_not_enter_calibration(client, auth):
    spec = dict(SITES[0])
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    start = "2024-01-01T00:00:00+00:00"
    end = "2024-02-01T00:00:00+00:00"
    week_start = "2024-02-01T00:00:00+00:00"
    week_end = "2024-02-08T00:00:00+00:00"

    def batch(batch_id, period_end, meters):
        return {
            "schema_version": "1.0",
            "batch_id": batch_id,
            "site_id": spec["site_id"],
            "generated_at": "2024-02-02T00:00:00+00:00",
            "period": {"start": start, "end": period_end, "label": "month"},
            "meters": meters,
            "weather": {"source": "test", "drybulb_mean_c": 0, "hdd_base_18c": 10, "cdd_base_18c": 0},
        }

    full = [
        {"meter_id": "elec-main", "fuel": "electricity", "unit": "kWh", "start": start, "end": end, "value": 100, "role": "main"},
        {"meter_id": "rtu", "fuel": "electricity", "unit": "kWh", "start": start, "end": end, "value": 900, "role": "sub"},
    ]
    assert client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch("00000000-0000-0000-0000-0000000000a1", end, full), headers=auth).status_code == 200
    short = [
        {"meter_id": "elec-main", "fuel": "electricity", "unit": "kWh", "start": week_start, "end": week_end, "value": 20, "role": "main"},
    ]
    week = batch("00000000-0000-0000-0000-0000000000a2", week_end, short)
    week["period"] = {"start": week_start, "end": week_end, "label": "week"}
    assert client.post(f"/v1/sites/{spec['site_id']}/operations", json=week, headers=auth).status_code == 200
    overlap = client.post(
        f"/v1/sites/{spec['site_id']}/operations",
        json=batch("00000000-0000-0000-0000-0000000000a3", end, full),
        headers=auth,
    )
    assert overlap.status_code == 409
    report = client.get(f"/v1/sites/{spec['site_id']}/report", headers=auth).json()
    assert report["months_received"] == 2
    from twin.scope import bind_tenant
    from twin.service import usable_months

    with client.app.state.Session() as session:
        bind_tenant(session, "local")
        months = usable_months(session, spec["site_id"])
    assert [item["electric_kwh"] for item in months] == [100.0]
    present = client.get(
        f"/v1/sites/{spec['site_id']}/coverage",
        params={"start": "2024-01-01T00:00:00+00:00", "end": "2024-03-01T00:00:00+00:00"},
        headers=auth,
    ).json()
    assert present["months_present"] == ["2024-01"]
    assert "2024-02" in present["months_missing"]


def test_energyplus_refuses_an_office_outside_the_area_band(client, auth):
    spec = dict(SITES[0])
    spec["floor_area_m2"] = 100
    spec["stories"] = 1
    client.post("/v1/sites", json=site_record(spec) | {"stories": 1, "system_type": "psz-ac", "heating_fuel": "heat_pump"}, headers=auth)
    for batch in batches_for(spec, include_incremental=False)[:4]:
        assert client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth).status_code == 200
    response = client.post(f"/v1/sites/{spec['site_id']}/calibrations?engine=energyplus", headers=auth)
    assert response.status_code == 422


def test_jobs_are_leased_and_an_expired_lease_fails_after_three_attempts(client):
    from datetime import timedelta

    from twin.db import Job, utcnow
    from twin.service import claim_next

    with client.app.state.Session() as session:
        session.add(
            Job(
                id="leased-job",
                tenant_id="local",
                site_id="site-cold-office",
                kind="calibration",
                status="queued",
                spec={},
                created_at=utcnow(),
            )
        )
        session.commit()
        claimed = claim_next(session)
        assert claimed.id == "leased-job"
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.lease_until > utcnow()
        claimed.attempts = 3
        claimed.lease_until = utcnow() - timedelta(seconds=5)
        session.commit()
        assert claim_next(session) is None
        assert session.get(Job, "leased-job").status == "failed"


def test_energyplus_tracking_scores_the_typical_year(client, auth, monkeypatch):
    spec = SITES[0]
    client.post("/v1/sites", json=site_record(spec), headers=auth)
    for batch in batches_for(spec, include_incremental=False)[:4]:
        assert client.post(f"/v1/sites/{spec['site_id']}/operations", json=batch, headers=auth).status_code == 200
    from twin.db import Job, ModelVersion
    from twin.eplus_calibrate import base_case

    with client.app.state.Session() as session:
        session.add(
            ModelVersion(
                id="ep-track",
                tenant_id="local",
                site_id=spec["site_id"],
                status="active",
                parameters=base_case(),
                ensemble=[base_case()],
                metrics=[],
                engine={"name": "energyplus", "label": "EnergyPlus"},
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

    def fake_simulate(_case, _weather, _span, timeout=3600):
        return {"electric": {month: 100.0 for month in range(1, 13)}, "gas": {}}

    monkeypatch.setattr("twin.eplus.simulate", fake_simulate)
    registered = client.post(
        f"/v1/sites/{spec['site_id']}/policies",
        headers=auth,
        json={"cadence": "monthly", "kind": "tracking", "engine": "energyplus"},
    )
    assert registered.status_code == 201
    ticked = client.post(
        "/v1/scheduler/tick",
        headers=auth,
        params={"now": datetime(2026, 6, 2, tzinfo=timezone.utc).isoformat()},
    ).json()
    job_id = next(job["id"] for job in ticked["jobs"] if job["kind"] == "energyplus-tracking")
    with client.app.state.Session() as session:
        result = session.get(Job, job_id).result
    assert result["mode"] == "typical-year"
    assert result["weather_kind"] != "amy"
    assert "not the actual weather" in result["note"]


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
