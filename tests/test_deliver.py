import httpx
from tools.fdd_sim.deliver import post_json


def test_retries_connection_errors_then_returns_the_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = post_json(client, "http://twin/v1", {"batch_id": "1"}, "key", sleeper=lambda _delay: None)
    assert response.status_code == 200
    assert calls["n"] == 3


def test_does_not_retry_a_client_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(422, json={"detail": "no"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = post_json(client, "http://twin/v1", {}, "key", sleeper=lambda _delay: None)
    assert response.status_code == 422
    assert calls["n"] == 1
