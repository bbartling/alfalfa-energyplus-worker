"""HTTP API and HTML reports."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from twin.dashboard import index_page, site_page
from twin.db import ApiKey, Job, Policy, Site, Webhook, init_db, make_engine, make_session_factory
from twin.schemas import ApiKeyIn, OperationsBatch, PolicyIn, ScenarioIn, SiteIn, WebhookIn
from twin.service import (
    Conflict,
    NotReady,
    coverage,
    create_job,
    execute,
    report,
    run_scenario,
    sign_body,
    site_cards,
    store_batch,
    tick,
)
from twin.settings import Settings


class APIError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    _wait_for_database(engine)
    factory = make_session_factory(engine)
    app = FastAPI(title="Building twin", version="1.0.0", docs_url="/docs")
    app.state.settings = settings
    app.state.Session = factory

    with factory() as session:
        _ensure_bootstrap(session, settings.bootstrap_key)

    def db():
        with factory() as session:
            yield session

    def principal(authorization: str | None = Header(default=None), session: Session = Depends(db)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise APIError(401, "missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        row = session.get(ApiKey, hashlib.sha256(token.encode()).hexdigest())
        if row is None:
            raise APIError(401, "unknown API key")
        return row

    def allow(site_id: str, key: ApiKey):
        if "*" not in key.sites and site_id not in key.sites:
            raise APIError(403, "API key cannot access this site")

    @app.exception_handler(APIError)
    def on_api_error(_request, exc: APIError):
        return _problem(exc.status, exc.detail)

    @app.exception_handler(RequestValidationError)
    def on_invalid(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"type": "about:blank", "title": "Invalid request", "status": 422, "detail": exc.errors()},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(session: Session = Depends(db)):
        _dashboard_guard()
        return index_page(site_cards(session))

    @app.get("/sites/{site_id}", response_class=HTMLResponse)
    def site_dashboard(site_id: str, session: Session = Depends(db)):
        _dashboard_guard()
        try:
            return site_page(report(session, site_id))
        except NotReady as exc:
            raise APIError(404, str(exc)) from exc

    @app.post("/v1/sites", status_code=201)
    def create_site(body: SiteIn, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        if "*" not in key.sites:
            raise APIError(403, "only an unrestricted key can register a site")
        if session.get(Site, body.site_id) is None:
            session.add(Site(**body.model_dump()))
            session.commit()
        return body.model_dump()

    @app.get("/v1/sites/{site_id}")
    def get_site(site_id: str, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        site = session.get(Site, site_id)
        if site is None:
            raise APIError(404, "unknown site")
        return {
            "site_id": site.site_id,
            "timezone": site.timezone,
            "latitude": site.latitude,
            "longitude": site.longitude,
            "floor_area_m2": site.floor_area_m2,
            "building_type": site.building_type,
            "weather_station": site.weather_station,
        }

    @app.post("/v1/sites/{site_id}/operations")
    def operations(site_id: str, body: OperationsBatch, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        return _accept(site_id, body, session)

    @app.post("/v1/hooks/operations")
    def operations_hook(body: OperationsBatch, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(body.site_id, key)
        return _accept(body.site_id, body, session)

    @app.get("/v1/sites/{site_id}/coverage")
    def site_coverage(
        site_id: str,
        start: datetime,
        end: datetime,
        key: ApiKey = Depends(principal),
        session: Session = Depends(db),
    ):
        allow(site_id, key)
        return coverage(session, site_id, start, end)

    @app.post("/v1/sites/{site_id}/policies", status_code=201)
    def add_policy(site_id: str, body: PolicyIn, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        existing = session.scalar(
            select(Policy).where(Policy.site_id == site_id, Policy.cadence == body.cadence, Policy.kind == body.kind)
        )
        if existing is None:
            session.add(Policy(site_id=site_id, cadence=body.cadence, kind=body.kind, enabled=True))
            session.commit()
        return body.model_dump()

    @app.post("/v1/scheduler/tick")
    def scheduler_tick(now: datetime | None = None, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        if "*" not in key.sites:
            raise APIError(403, "only an unrestricted key can run the scheduler")
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise APIError(422, "now must be timezone-aware")
        jobs = tick(session, moment)
        if settings.inline_jobs:
            for job in jobs:
                execute(session, job)
                _notify(session, job)
        return {"jobs": [{"id": job.id, "site_id": job.site_id, "kind": job.kind, "status": job.status, "spec": job.spec} for job in jobs]}

    @app.post("/v1/sites/{site_id}/calibrations")
    def calibrate(site_id: str, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        job = create_job(session, site_id, "calibration", {"reason": "manual"})
        session.commit()
        if settings.inline_jobs:
            execute(session, job)
            _notify(session, job)
        return JSONResponse(status_code=200 if job.status == "completed" else 202, content=_job_body(job))

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        job = session.get(Job, job_id)
        if job is None:
            raise APIError(404, "unknown job")
        allow(job.site_id, key)
        return _job_body(job)

    @app.get("/v1/sites/{site_id}/report")
    def site_report(site_id: str, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        try:
            return report(session, site_id)
        except NotReady as exc:
            raise APIError(404, str(exc)) from exc

    @app.post("/v1/sites/{site_id}/scenarios")
    def scenario(site_id: str, body: ScenarioIn, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        try:
            row = run_scenario(
                session,
                site_id,
                body.name,
                [item.model_dump() for item in body.measures],
                body.costs.model_dump(),
            )
        except NotReady as exc:
            raise APIError(409, str(exc)) from exc
        return {"id": row.id, "status": row.status, "result": row.result}

    @app.post("/v1/api-keys", status_code=201)
    def mint_key(body: ApiKeyIn, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        if "*" not in key.sites:
            raise APIError(403, "only an unrestricted key can mint keys")
        token = "twin_" + secrets.token_urlsafe(24)
        session.add(
            ApiKey(key_hash=hashlib.sha256(token.encode()).hexdigest(), tenant=key.tenant, sites=body.site_ids, label="scoped")
        )
        session.commit()
        return {"api_key": token, "site_ids": body.site_ids}

    @app.post("/v1/webhooks", status_code=201)
    def add_webhook(body: WebhookIn, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        if "*" not in key.sites:
            raise APIError(403, "only an unrestricted key can register webhooks")
        session.add(Webhook(url=body.url, secret=body.secret, events=body.events))
        session.commit()
        return {"status": "registered"}

    @app.post("/v1/sites/{site_id}/live-runs")
    def live_run(site_id: str, key: ApiKey = Depends(principal), session: Session = Depends(db)):
        allow(site_id, key)
        if session.get(Site, site_id) is None:
            raise APIError(404, "unknown site")
        if not settings.alfalfa_url:
            raise APIError(409, "Alfalfa is not configured. Batch calibration and scenarios do not need it.")
        return {"alfalfa_url": settings.alfalfa_url, "status": "not-started"}

    def _dashboard_guard():
        if not settings.dashboard_open:
            raise APIError(401, "dashboard is closed")

    def _accept(site_id: str, body: OperationsBatch, session: Session):
        if body.site_id != site_id:
            raise APIError(422, "site_id does not match the path")
        try:
            return store_batch(session, body)
        except Conflict as exc:
            raise APIError(409, str(exc)) from exc
        except NotReady as exc:
            raise APIError(404, str(exc)) from exc

    def _notify(session: Session, job):
        event = "job.completed" if job.status == "completed" else "calibration.failed"
        payload = {"event": event, "job": _job_body(job)}
        body = json.dumps(payload).encode()
        hooks = session.scalars(select(Webhook)).all()
        for hook in hooks:
            if event not in hook.events:
                continue
            signature = sign_body(hook.secret, body)
            try:
                httpx.post(hook.url, content=body, headers={"X-Twin-Signature": signature}, timeout=2)
            except httpx.HTTPError:
                continue

    return app


def _job_body(job) -> dict:
    return {
        "id": job.id,
        "site_id": job.site_id,
        "kind": job.kind,
        "status": job.status,
        "spec": job.spec,
        "result": job.result,
        "error": job.error,
    }


def _wait_for_database(engine) -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            init_db(engine)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    if last_error:
        raise last_error


def _ensure_bootstrap(session: Session, token: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    if session.get(ApiKey, digest) is None:
        session.add(ApiKey(key_hash=digest, tenant="local", sites=["*"], label="bootstrap"))
        session.commit()


def _problem(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"type": "about:blank", "title": detail, "status": status, "detail": detail})
