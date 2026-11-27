"""Pull queued jobs. Use this when calibrations should not run inside the API process."""

import time

from twin.db import Job, make_engine, make_session_factory
from twin.scope import bind_tenant, bind_worker
from twin.service import execute
from twin.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    factory = make_session_factory(make_engine(settings.database_url))
    while True:
        with factory() as session:
            from sqlalchemy import select

            bind_worker(session)
            job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at))
            if job is not None:
                bind_tenant(session, job.tenant_id)
                execute(session, job)
                continue
        time.sleep(2)


if __name__ == "__main__":
    main()
