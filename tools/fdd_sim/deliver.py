"""POST summaries with retries. 4xx is returned immediately; connection errors and 5xx retry."""

from __future__ import annotations

import time

import httpx


def post_json(client: httpx.Client, url: str, payload: dict, key: str, *, attempts: int = 5, sleeper=time.sleep):
    headers = {"Authorization": f"Bearer {key}"}
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            response = client.post(url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            if response.status_code < 500:
                return response
            last_error = httpx.HTTPStatusError("server error", request=response.request, response=response)
        if attempt + 1 < attempts:
            sleeper(0.2 * (2**attempt))
    raise RuntimeError(f"POST {url} failed after {attempts} attempts") from last_error
