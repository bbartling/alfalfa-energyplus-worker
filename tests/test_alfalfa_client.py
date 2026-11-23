"""Package-level tests: offline, no running Alfalfa server required."""
from __future__ import annotations

import pytest
from alfalfa_client.alfalfa_client import AlfalfaClient


def test_installed_client_is_real_package() -> None:
    from importlib.metadata import version

    assert version("alfalfa-client") == "1.0.0"
    client = AlfalfaClient("http://localhost:80")
    assert client.url.endswith("/api/v2/")


def test_interactive_operations_use_official_client(monkeypatch) -> None:
    client = AlfalfaClient("http://localhost")
    actions = []
    monkeypatch.setattr(client, "status", lambda run_id: actions.append(("status", run_id)) or "RUNNING")
    monkeypatch.setattr(client, "get_inputs", lambda run_id: ["Heating Setpoint"])
    monkeypatch.setattr(client, "set_inputs", lambda run_id, points: actions.append(("set", points)))
    monkeypatch.setattr(client, "advance", lambda run_id: actions.append(("advance", run_id)))
    assert client.status("test-run") == "RUNNING"
    assert "Heating Setpoint" in client.get_inputs("test-run")
    client.set_inputs("test-run", {"Heating Setpoint": 22.0})
    client.advance("test-run")
    assert actions == [("status", "test-run"), ("set", {"Heating Setpoint": 22.0}), ("advance", "test-run")]


@pytest.mark.integration
def test_live_alfalfa_run_status() -> None:
    """Opt-in network test: pytest -m integration; requires env configuration."""
    import os

    host = os.getenv("ALFALFA_URL")
    run_id = os.getenv("ALFALFA_RUN_ID")
    if not host or not run_id:
        pytest.skip("Set ALFALFA_URL and ALFALFA_RUN_ID for live Alfalfa tests")
    assert AlfalfaClient(host).status(run_id)
