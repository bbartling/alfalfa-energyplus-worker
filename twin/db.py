from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Site(Base):
    __tablename__ = "sites"
    site_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    floor_area_m2: Mapped[float] = mapped_column(Float)
    building_type: Mapped[str] = mapped_column(String(80))
    weather_station: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(80), default="local")
    sites: Mapped[list] = mapped_column(JSON)
    label: Mapped[str] = mapped_column(String(80), default="key")


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(String(80), index=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    body_hash: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[str] = mapped_column(String(40))
    period_end: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("site_id", "batch_id"),)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(String(80), index=True)
    cadence: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("site_id", "cadence", "kind"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(16))
    parameters: Mapped[dict] = mapped_column(JSON)
    ensemble: Mapped[list] = mapped_column(JSON)
    metrics: Mapped[list] = mapped_column(JSON)
    engine: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    model_version_id: Mapped[str] = mapped_column(String(36))
    spec: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(300))
    secret: Mapped[str] = mapped_column(String(200))
    events: Mapped[list] = mapped_column(JSON)


def make_engine(url: str):
    if url.startswith("sqlite"):
        connect = {"check_same_thread": False}
    else:
        connect = {"connect_timeout": 5}
    return create_engine(url, connect_args=connect, pool_pre_ping=True, future=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
