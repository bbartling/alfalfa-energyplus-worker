"""Pull queued jobs. Use this when calibrations should not run inside the API process."""

import time

from twin.db import make_engine, make_session_factory
from twin.scope import bind_tenant, bind_worker
from twin.service import claim_next, execute
from twin.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    factory = make_session_factory(make_engine(settings.database_url))
    while True:
        with factory() as session:
            bind_worker(session)
            job = claim_next(session)
            if job is not None:
                bind_tenant(session, job.tenant_id)
                execute(session, job)
                continue
        time.sleep(2)


if __name__ == "__main__":
    main()
