"""Bind the caller's tenant to the session and to Postgres row security."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from twin.db import Site


def bind_tenant(session: Session, tenant: str) -> None:
    session.info["tenant"] = tenant
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text("SELECT set_config('twin.tenant_id', :tenant, true)"), {"tenant": tenant})


def bind_worker(session: Session) -> None:
    """Let the runner see every tenant's queue. The job then rebinds its tenant."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text("SELECT set_config('twin.role', 'worker', true)"))


def current_tenant(session: Session) -> str:
    tenant = session.info.get("tenant")
    if not tenant:
        raise RuntimeError("tenant is not bound")
    return tenant


def get_site(session: Session, site_id: str) -> Site | None:
    return session.get(Site, (current_tenant(session), site_id))
