import pytest
from fastapi.testclient import TestClient
from twin.factory import create_app
from twin.settings import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path}/twin.db",
            bootstrap_key="test-key",
            dashboard_open=True,
            inline_jobs=True,
            alfalfa_url=None,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth():
    return {"Authorization": "Bearer test-key"}
