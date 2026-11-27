"""Ingest summaries, infer missing setpoints, calibrate, and price what-ifs."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from twin.db import Batch, Job, ModelVersion, Policy, Scenario, Site, utcnow
from twin.energy import Params, fit, leave_one_out, predict
from twin.guideline14 import assess
from twin.infer import CONFIDENCE_FLOOR, Inferred, infer_quantile, infer_reset
from twin.schemas import UNITS, OperationsBatch
from twin.scope import current_tenant, get_site

DAY_WEIGHT = {
    "weekday": 5 / 7,
    "weekend": 2 / 7,
    "all": 1.0,
    "monday": 1 / 7,
    "tuesday": 1 / 7,
    "wednesday": 1 / 7,
    "thursday": 1 / 7,
    "friday": 1 / 7,
    "saturday": 1 / 7,
    "sunday": 1 / 7,
}
SENSOR_KIND = {
    "supply_air_temp": "supply_air_temp",
    "duct_static": "duct_static",
    "chw_temp": "chw",
    "hw_temp": "hw",
}


class Conflict(Exception):
    pass


class NotReady(Exception):
    pass


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def sign_body(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def apply_inference(batch: OperationsBatch) -> OperationsBatch:
    data = batch.model_dump(mode="json")
    existing = {(item.equipment_id, item.kind, item.period) for item in batch.setpoints}
    actual_kinds = {(item.equipment_id, item.kind) for item in batch.setpoints if item.source == "actual"}
    for sensor in batch.sensors:
        if sensor.kind == "zone_temp":
            for period, heating, cooling in (
                ("occupied", sensor.occupied_heating_active, sensor.occupied_cooling_active),
                ("unoccupied", sensor.unoccupied_heating_active, sensor.unoccupied_cooling_active),
            ):
                if heating is not None:
                    _add_mode(data, existing, actual_kinds, sensor.equipment_id, "zone_heating", period, heating, upper=True)
                if cooling is not None:
                    _add_mode(data, existing, actual_kinds, sensor.equipment_id, "zone_cooling", period, cooling, upper=False)
        elif len(sensor.reset_modes) >= 2:
            inferred = infer_reset([mode.model_dump() for mode in sensor.reset_modes])
            _add_setpoint(data, existing, actual_kinds, sensor.equipment_id, SENSOR_KIND[sensor.kind], "always", inferred)
        elif sensor.running is not None:
            inferred = infer_quantile(sensor.running.model_dump(), upper=False)
            inferred = Inferred(round(sensor.running.p50, 3), inferred.confidence, "mode-quantile")
            _add_setpoint(data, existing, actual_kinds, sensor.equipment_id, SENSOR_KIND[sensor.kind], "always", inferred)
    return OperationsBatch.model_validate(data)


def _add_mode(data, existing, actual_kinds, equipment_id, kind, period, summary, *, upper: bool) -> None:
    try:
        inferred = infer_quantile(summary.model_dump(), upper=upper)
    except ValueError:
        return
    _add_setpoint(data, existing, actual_kinds, equipment_id, kind, period, inferred)


def _add_setpoint(data, existing, actual_kinds, equipment_id, kind, period, inferred) -> None:
    if (equipment_id, kind) in actual_kinds:
        return
    if inferred.confidence < CONFIDENCE_FLOOR and inferred.method != "reset":
        return
    key = (equipment_id, kind, period)
    if key in existing:
        return
    data["setpoints"].append(
        {
            "equipment_id": equipment_id,
            "kind": kind,
            "period": period,
            "unit": UNITS[kind],
            "value": inferred.value,
            "source": "inferred",
            "confidence": inferred.confidence,
            "method": inferred.method,
            "modes": None if inferred.modes is None else list(inferred.modes),
        }
    )
    existing.add(key)


def store_batch(session: Session, batch: OperationsBatch) -> dict:
    site = get_site(session, batch.site_id)
    if site is None:
        raise NotReady("unknown site")
    raw = batch.model_dump(mode="json")
    digest = canonical_hash(raw)
    existing = session.scalar(
        select(Batch).where(
            Batch.tenant_id == current_tenant(session),
            Batch.site_id == batch.site_id,
            Batch.batch_id == str(batch.batch_id),
        )
    )
    for prior in session.scalars(
        select(Batch).where(Batch.tenant_id == current_tenant(session), Batch.site_id == batch.site_id)
    ):
        if prior.batch_id == str(batch.batch_id):
            continue
        if _overlaps(prior.period_start, prior.period_end, batch.period.start, batch.period.end):
            raise Conflict("period overlaps a summary that is already stored")
    if existing is not None:
        if existing.body_hash != digest:
            raise Conflict("batch_id was already stored with a different body")
        return {"batch_id": existing.batch_id, "duplicate": True, "payload": existing.payload}
    normalized = apply_inference(batch).model_dump(mode="json")
    row = Batch(
        tenant_id=current_tenant(session),
        site_id=batch.site_id,
        batch_id=str(batch.batch_id),
        body_hash=digest,
        period_start=normalized["period"]["start"],
        period_end=normalized["period"]["end"],
        payload=normalized,
    )
    session.add(row)
    session.commit()
    return {"batch_id": row.batch_id, "duplicate": False, "payload": normalized}


def coverage(session: Session, site_id: str, start: datetime, end: datetime) -> dict:
    present = sorted({month["start"][:7] for month in usable_months(session, site_id)})
    missing = []
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    stop = datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    while cursor < stop:
        key = cursor.strftime("%Y-%m")
        if key not in present:
            missing.append(key)
        cursor = _add_month(cursor)
    return {"site_id": site_id, "months_present": present, "months_missing": missing}


def create_job(session: Session, site_id: str, kind: str, spec: dict, created_at: datetime | None = None) -> Job:
    job = Job(
        id=str(uuid4()),
        tenant_id=current_tenant(session),
        site_id=site_id,
        kind=kind,
        status="queued",
        spec=spec,
        result=None,
        created_at=created_at or utcnow(),
    )
    session.add(job)
    session.flush()
    return job


def execute(session: Session, job: Job) -> Job:
    job.status = "running"
    session.commit()
    try:
        if job.kind == "calibration":
            job.result = calibrate(session, job.site_id)
        elif job.kind == "energyplus-calibration":
            job.result = calibrate_energyplus(session, job.site_id, span=job.spec.get("span") or "year")
        elif job.kind == "energyplus-scenario":
            row = run_scenario(session, job.site_id, job.spec["name"], job.spec["measures"], job.spec["costs"])
            job.result = {"scenario_id": row.id, **(row.result or {})}
        elif job.kind == "tracking":
            job.result = track(session, job.site_id)
        else:
            raise NotReady(f"unsupported job kind {job.kind}")
        job.status = "completed"
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)[:500]
        job.result = {"error": job.error}
    job.finished_at = utcnow()
    session.commit()
    return job


def calibrate(session: Session, site_id: str) -> dict:
    site = get_site(session, site_id)
    if site is None:
        raise NotReady("unknown site")
    months = usable_months(session, site_id)
    if len(months) < 4:
        raise NotReady("need at least four usable months to calibrate")
    try:
        best = fit(months, site.floor_area_m2)
    except ValueError as exc:
        raise NotReady(str(exc)) from exc
    ensemble = [params.as_dict() for params in leave_one_out(months, site.floor_area_m2)]
    metrics = _split_metrics(best, months, site.floor_area_m2, "all", claim="screening")
    return _save_model(
        session,
        site_id,
        False,
        best.as_dict(),
        ensemble,
        metrics,
        {
            "name": "quick-estimate",
            "label": "screening",
            "claim": "screening",
            "decision": "screening",
            "openstudio": None,
            "energyplus": None,
        },
        max(1, len(ensemble)),
    )


def _save_model(session, site_id, promoted, parameters, ensemble, metrics, engine, runs) -> dict:
    tenant = current_tenant(session)
    screening = engine.get("decision") == "screening"
    if screening:
        for prior in session.scalars(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant, ModelVersion.site_id == site_id, ModelVersion.status == "screening"
            )
        ):
            prior.status = "replaced"
        status = "screening"
    else:
        if promoted:
            for prior in session.scalars(
                select(ModelVersion).where(
                    ModelVersion.tenant_id == tenant, ModelVersion.site_id == site_id, ModelVersion.status == "active"
                )
            ):
                prior.status = "retired"
        status = "active" if promoted else "candidate"
    version = ModelVersion(
        id=str(uuid4()),
        tenant_id=tenant,
        site_id=site_id,
        status=status,
        parameters=parameters,
        ensemble=ensemble,
        metrics=metrics,
        engine=engine,
    )
    session.add(version)
    session.flush()
    return {
        "site_id": site_id,
        "model_version_id": version.id,
        "decision": engine.get("decision"),
        "parameters": parameters,
        "ensemble": ensemble,
        "metrics": metrics,
        "runs": runs,
        "engine": version.engine,
    }


def _payloads(session: Session, site_id: str) -> list[dict]:
    rows = session.scalars(
        select(Batch).where(Batch.tenant_id == current_tenant(session), Batch.site_id == site_id).order_by(Batch.period_start)
    ).all()
    return [row.payload for row in rows]


def calibrate_energyplus(session: Session, site_id: str, span: str = "year") -> dict:
    """Batch EnergyPlus calibration. This is the long job, not the quick estimate."""
    from twin.eplus import simulate
    from twin.eplus_calibrate import conditions_from_payloads, fit, prototype_match
    from twin.weather import nearest_station

    site = get_site(session, site_id)
    if site is None:
        raise NotReady("unknown site")
    months = usable_months(session, site_id)
    payloads = _payloads(session, site_id)
    station = nearest_station(site.latitude, site.longitude)
    weather = station["file"]

    def run_fn(case: dict, run_span: str) -> dict:
        return simulate(case, weather, run_span)

    mismatch = prototype_match(site)
    if mismatch:
        raise NotReady(mismatch)
    base = conditions_from_payloads(payloads)
    base["heating_fuel"] = site.heating_fuel
    try:
        fitted = fit(base, months, site.floor_area_m2, run_fn, span=span)
    except ValueError as exc:
        raise NotReady(str(exc)) from exc
    fitted["engine"]["weather"] = weather
    fitted["engine"]["weather_station"] = station["wmo"]
    fitted["engine"]["weather_kind"] = station["weather_kind"]
    fitted["engine"]["weather_note"] = "Nearest-station typical year. Not the actual year of the bills."
    return _save_model(
        session,
        site_id,
        fitted["decision"] == "promoted",
        fitted["parameters"],
        fitted["ensemble"],
        fitted["metrics"],
        fitted["engine"],
        fitted["runs"],
    )


def track(session: Session, site_id: str) -> dict:
    version = active_version(session, site_id)
    if version is None:
        raise NotReady("no active model to track")
    if version.engine.get("name") == "energyplus":
        return {
            "model_version_id": version.id,
            "mode": "stored",
            "metrics": version.metrics,
            "note": "EnergyPlus tracking reuses the last calibration until the next batch run.",
        }
    months = usable_months(session, site_id)
    window = months[-2:]
    if len(window) < 2:
        raise NotReady("not enough months to track")
    params = Params(**version.parameters)
    metrics = _split_metrics(params, window, get_site(session, site_id).floor_area_m2, "tracking", claim="screening")
    return {"model_version_id": version.id, "metrics": metrics}


def run_scenario(session: Session, site_id: str, name: str, measures: list[dict], costs: dict) -> Scenario:
    version = active_version(session, site_id)
    if version is None:
        raise NotReady("no active model for a what-if")
    area = get_site(session, site_id).floor_area_m2
    if version.engine.get("name") == "energyplus":
        result = _price_energyplus(session, site_id, version, measures, costs)
    else:
        months = usable_months(session, site_id)
        if len(months) < 2:
            raise NotReady("not enough months for a what-if")
        baseline = Params(**version.parameters)
        result = price_measures(baseline, months, area, measures, costs, version.ensemble)
        result["engine"] = "quick-estimate"
        result["label"] = "screening"
        result["claim"] = "screening"
    scenario = Scenario(
        id=str(uuid4()),
        tenant_id=current_tenant(session),
        site_id=site_id,
        name=name,
        model_version_id=version.id,
        spec={"measures": measures, "costs": costs},
        result=result,
        status="completed",
    )
    session.add(scenario)
    session.commit()
    return scenario


def price_measures(params: Params, months: list[dict], area: float, measures: list[dict], costs: dict, ensemble: list[dict]) -> dict:
    save_kwh, save_therms, save_usd, annualized = _savings(params, months, area, measures, costs)
    band = []
    for item in ensemble:
        _kwh, _therms, usd, _annualized = _savings(Params(**item), months, area, measures, costs)
        band.append(usd)
    annual = save_usd
    payback = None if annual <= 0 else costs["implementation_usd"] / annual
    return {
        "annual_kwh_savings": save_kwh,
        "annual_therm_savings": save_therms,
        "annual_cost_savings_usd": annual,
        "simple_payback_years": payback,
        "npv_usd": net_present_value(costs["implementation_usd"], annual, costs["discount_rate"], costs["horizon_years"]),
        "cost_savings_band_usd": [min(band), max(band)] if band else [annual, annual],
        "annualized": annualized,
    }


def active_engine(session: Session, site_id: str) -> str | None:
    version = active_version(session, site_id)
    if version is None:
        return None
    return version.engine.get("name")


def _price_energyplus(session: Session, site_id: str, version: ModelVersion, measures: list[dict], costs: dict) -> dict:
    from twin.eplus import simulate, weather_file
    from twin.eplus_calibrate import price_energyplus

    site = get_site(session, site_id)
    weather = weather_file(site.latitude, site.longitude)

    def run_fn(case: dict, span: str) -> dict:
        return simulate(case, weather, span)

    return price_energyplus(version.parameters, measures, costs, site.floor_area_m2, run_fn, version.ensemble)


def net_present_value(initial: float, annual: float, rate: float, years: int) -> float:
    total = -initial
    for year in range(1, years + 1):
        total += annual / ((1 + rate) ** year)
    return total


def tick(session: Session, now: datetime) -> list[Job]:
    created: list[Job] = []
    tenant = current_tenant(session)
    policies = session.scalars(select(Policy).where(Policy.tenant_id == tenant, Policy.enabled.is_(True))).all()
    for policy in policies:
        since = _month_start(now) if policy.cadence == "monthly" else now - timedelta(days=7)
        if _recent_job(session, policy.site_id, policy.kind, since):
            continue
        created.append(create_job(session, policy.site_id, policy.kind, {"reason": policy.cadence}, created_at=now))
    watched = {policy.site_id for policy in policies}
    watched.update(
        session.scalars(
            select(Job.site_id).where(Job.tenant_id == tenant, Job.kind == "tracking", Job.status == "completed")
        ).all()
    )
    for site_id in sorted(watched):
        if not is_drifting(session, site_id):
            continue
        if _recent_job(session, site_id, "calibration", now - timedelta(days=7)):
            continue
        created.append(create_job(session, site_id, "calibration", {"reason": "drift"}, created_at=now))
    session.commit()
    return created


def is_drifting(session: Session, site_id: str) -> bool:
    jobs = session.scalars(
        select(Job)
        .where(
            Job.tenant_id == current_tenant(session),
            Job.site_id == site_id,
            Job.kind == "tracking",
            Job.status == "completed",
        )
        .order_by(Job.created_at.desc())
    ).all()
    recent = list(jobs)[:2]
    if len(recent) < 2:
        return False
    return all(_cv_above(job, 30) for job in recent)


def usable_months(session: Session, site_id: str) -> list[dict]:
    rows = session.scalars(
        select(Batch).where(Batch.tenant_id == current_tenant(session), Batch.site_id == site_id)
    ).all()
    months = []
    for row in rows:
        month = month_from_payload(row.payload)
        if month["electric_kwh"] is None or month["exclude"]:
            continue
        months.append(month)
    months.sort(key=lambda item: item["start"])
    return months


def month_from_payload(payload: dict) -> dict:
    start = _parse_time(payload["period"]["start"])
    end = _parse_time(payload["period"]["end"])
    days = max(1.0, (end - start).total_seconds() / 86400)
    covered = _meter_coverage(payload.get("meters") or [], start, end)
    occupied = _occupied_hours(payload.get("schedules") or [], days)
    equipment = payload.get("run_hours") or []
    run_hours = sum(item["hours"] for item in equipment) / len(equipment) if equipment else 0.0
    if occupied is None:
        occupied = run_hours or days * 10
    if run_hours <= 0:
        run_hours = occupied
    oa_values = [item["oa_fraction_mean"] for item in payload.get("outdoor_air") or []]
    oa = sum(oa_values) / len(oa_values) if oa_values else 0.2
    weather = payload["weather"]
    return {
        "start": start.isoformat(),
        "days": days,
        "occupied_hours": occupied,
        "run_hours": run_hours,
        "cooling_sp": _setpoint(payload.get("setpoints") or [], "zone_cooling", "occupied", 24.0),
        "heating_sp": _setpoint(payload.get("setpoints") or [], "zone_heating", "occupied", 21.0),
        "oa_fraction": oa,
        "cdd": weather["cdd_base_18c"],
        "hdd": weather["hdd_base_18c"],
        "electric_kwh": _meter_total(payload.get("meters") or [], "electricity"),
        "gas_therms": _meter_total(payload.get("meters") or [], "natural_gas"),
        "exclude": any(item.get("exclude_from_calibration") for item in payload.get("faults") or [])
        or days < 0.95 * _days_in_month(start)
        or covered < 0.95,
    }


def report(session: Session, site_id: str) -> dict:
    site = get_site(session, site_id)
    if site is None:
        raise NotReady("unknown site")
    version = session.scalars(
        select(ModelVersion)
        .where(ModelVersion.tenant_id == current_tenant(session), ModelVersion.site_id == site_id)
        .order_by(ModelVersion.created_at.desc())
    ).first()
    tenant = current_tenant(session)
    scenarios = session.scalars(
        select(Scenario).where(Scenario.tenant_id == tenant, Scenario.site_id == site_id).order_by(Scenario.created_at)
    ).all()
    batches = session.scalars(
        select(Batch).where(Batch.tenant_id == tenant, Batch.site_id == site_id).order_by(Batch.period_start)
    ).all()
    setpoints = batches[-1].payload.get("setpoints", []) if batches else []
    calibration = None
    if version is not None:
        calibration = {
            "model_version_id": version.id,
            "status": version.status,
            "decision": version.engine.get("decision"),
            "parameters": version.parameters,
            "metrics": version.metrics,
            "engine": version.engine,
        }
    return {
        "site_id": site.site_id,
        "timezone": site.timezone,
        "floor_area_m2": site.floor_area_m2,
        "building_type": site.building_type,
        "latitude": site.latitude,
        "longitude": site.longitude,
        "calibration": calibration,
        "scenarios": [
            {"id": item.id, "name": item.name, "status": item.status, "result": item.result} for item in scenarios
        ],
        "setpoints": setpoints,
        "months_received": len(batches),
    }


def site_cards(session: Session) -> list[dict]:
    cards = []
    for site in session.scalars(select(Site).where(Site.tenant_id == current_tenant(session)).order_by(Site.site_id)).all():
        item = report(session, site.site_id)
        metric = _headline(None if item["calibration"] is None else item["calibration"]["metrics"])
        cards.append(
            {
                "site_id": site.site_id,
                "building_type": site.building_type,
                "decision": None if item["calibration"] is None else item["calibration"]["decision"],
                "cv_rmse_pct": None if metric is None else metric["cv_rmse_pct"],
                "nmbe_pct": None if metric is None else metric["nmbe_pct"],
                "fuel": None if metric is None else metric["fuel"],
                "split": None if metric is None else metric["split"],
            }
        )
    return cards


def _headline(metrics):
    if not metrics:
        return None
    holdout = [item for item in metrics if item["split"] == "holdout" and item["fuel"] == "electricity"]
    return (holdout or metrics)[0]


def _savings(params, months, area, measures, costs):
    base_e, base_g, alt_e, alt_g, days = [], [], [], [], []
    altered = [_apply_measures(month, measures) for month in months]
    for month, changed in zip(months, altered, strict=True):
        electric, gas = predict(params, month, area)
        electric_alt, gas_alt = predict(params, changed, area)
        base_e.append(electric)
        base_g.append(gas)
        alt_e.append(electric_alt)
        alt_g.append(gas_alt)
        days.append(month["days"])
    annualized = len(months) >= 12
    scale = 365 / sum(days) if annualized else 1.0
    save_kwh = (sum(base_e) - sum(alt_e)) * scale
    save_therms = (sum(base_g) - sum(alt_g)) * scale
    usd = save_kwh * costs["electricity_usd_per_kwh"] + save_therms * costs["gas_usd_per_therm"]
    return save_kwh, save_therms, usd, annualized


def _apply_measures(month: dict, measures: list[dict]) -> dict:
    updated = dict(month)
    for measure in measures:
        if measure["name"] == "raise_cooling_setpoint":
            updated["cooling_sp"] = updated["cooling_sp"] + measure["delta_c"]
        elif measure["name"] == "lower_heating_setpoint":
            updated["heating_sp"] = updated["heating_sp"] - measure["delta_c"]
        elif measure["name"] == "trim_run_hours":
            updated["run_hours"] = updated["run_hours"] * (1 - measure["fraction"])
    return updated


def _split_metrics(params: Params, months: list[dict], area: float, split: str, claim: str | None = None) -> list[dict]:
    electric_m, electric_s, gas_m, gas_s = [], [], [], []
    for month in months:
        electric, gas = predict(params, month, area)
        electric_m.append(month["electric_kwh"])
        electric_s.append(electric)
        if month.get("gas_therms") is not None:
            gas_m.append(month["gas_therms"])
            gas_s.append(gas)
    rows = [_assess_row(split, "electricity", "monthly", electric_m, electric_s, claim)]
    if len(gas_m) >= 2:
        rows.append(_assess_row(split, "natural_gas", "monthly", gas_m, gas_s, claim))
    return rows


def _assess_row(split, fuel, granularity, measured, simulated, claim: str | None = None) -> dict:
    stats = assess(measured, simulated, granularity)
    if claim == "screening":
        stats = {**stats, "claim": "screening", "pass": None, "limits": None}
    return {"split": split, "fuel": fuel, **stats}


def _split_passes(metrics: list[dict], split: str) -> bool:
    rows = [item for item in metrics if item["split"] == split and item["claim"] == "guideline14"]
    return bool(rows) and all(item["pass"] for item in rows)


def _days_in_month(start: datetime) -> float:
    nxt = _add_month(start)
    return (nxt - datetime(start.year, start.month, 1, tzinfo=timezone.utc)).total_seconds() / 86400


def _meter_coverage(meters: list[dict], start: datetime, end: datetime) -> float:
    span = (end - start).total_seconds()
    if span <= 0:
        return 0.0
    best = 0.0
    for meter in meters:
        if meter.get("role", "main") != "main" or meter.get("fuel") != "electricity":
            continue
        if "start" not in meter or "end" not in meter:
            best = 1.0
            continue
        left = max(_parse_time(meter["start"]), start)
        right = min(_parse_time(meter["end"]), end)
        best = max(best, max(0.0, (right - left).total_seconds()) / span)
    return best


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    a0, a1 = _parse_time(a_start), _parse_time(a_end)
    b0, b1 = _parse_time(b_start), _parse_time(b_end)
    return a0 < b1 and b0 < a1


def _meter_total(meters: list[dict], fuel: str) -> float | None:
    chosen = [item for item in meters if item["fuel"] == fuel and item.get("role", "main") == "main"]
    monthly = [item for item in chosen if item["granularity"] == "month"]
    use = monthly or chosen
    if not use:
        return None
    return sum(item["value"] for item in use)


def _setpoint(setpoints: list[dict], kind: str, period: str, default: float) -> float:
    actual = [item for item in setpoints if item["kind"] == kind and item.get("source") == "actual"]
    if actual:
        exact = [item for item in actual if item["period"] == period] or actual
        return sum(item["value"] for item in exact) / len(exact)
    usable = [
        item
        for item in setpoints
        if item["kind"] == kind
        and item.get("source") == "inferred"
        and (item.get("confidence") or 0) >= CONFIDENCE_FLOOR
        and item["period"] in {period, "always"}
    ]
    exact = [item for item in usable if item["period"] == period] or usable
    if not exact:
        return default
    return sum(item["value"] for item in exact) / len(exact)


def _occupied_hours(schedules: list[dict], days: float) -> float | None:
    if not schedules:
        return None
    best = 0.0
    for schedule in schedules:
        hours = 0.0
        for window in schedule["windows"]:
            hours += _clock_hours(window["start"], window["end"]) * DAY_WEIGHT[window["days"]] * days
        best = max(best, hours)
    return best


def _clock_hours(start: str, end: str) -> float:
    start_h, start_m = (int(part) for part in start.split(":"))
    end_h, end_m = (int(part) for part in end.split(":"))
    return max(0.0, (end_h * 60 + end_m) - (start_h * 60 + start_m)) / 60


def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def _add_month(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _recent_job(session: Session, site_id: str, kind: str, since: datetime) -> bool:
    jobs = session.scalars(
        select(Job).where(Job.tenant_id == current_tenant(session), Job.site_id == site_id, Job.kind == kind)
    ).all()
    for job in jobs:
        created = job.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= since:
            return True
    return False


def _cv_above(job: Job, limit: float) -> bool:
    metrics = (job.result or {}).get("metrics") or []
    return any(item.get("cv_rmse_pct", 0) > limit for item in metrics)


def active_version(session: Session, site_id: str) -> ModelVersion | None:
    tenant = current_tenant(session)
    active = session.scalar(
        select(ModelVersion).where(
            ModelVersion.tenant_id == tenant,
            ModelVersion.site_id == site_id,
            ModelVersion.status == "active",
        )
    )
    if active is not None:
        return active
    return session.scalars(
        select(ModelVersion)
        .where(ModelVersion.tenant_id == tenant, ModelVersion.site_id == site_id, ModelVersion.status == "screening")
        .order_by(ModelVersion.created_at.desc())
    ).first()
