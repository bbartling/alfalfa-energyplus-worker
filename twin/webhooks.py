"""Webhook registration checks and delivery.

The stored secret is a random signing key. The secret sent at registration is not kept.
Delivery signs `{timestamp}.{body}` and retries with backoff. The host must be https and
must resolve to a public address, both when the hook is saved and when it is sent.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit

import httpx

from twin.service import sign_body


def public_webhook(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise ValueError("webhook url must be https")
    addresses = _addresses(host, parsed.port or 443)
    if not addresses or any(_blocked(item) for item in addresses):
        raise ValueError("webhook host must resolve to a public address")


def deliver(session, job, sleeper=time.sleep) -> None:
    event = "job.completed" if job.status == "completed" else "calibration.failed"
    payload = {
        "event": event,
        "job": {"id": job.id, "site_id": job.site_id, "kind": job.kind, "status": job.status},
    }
    body = json.dumps(payload).encode()
    hooks = session.scalars(select_hooks(job.tenant_id)).all()
    for hook in hooks:
        if event not in hook.events:
            continue
        _post(hook, body, sleeper)


def select_hooks(tenant_id: str):
    from sqlalchemy import select

    from twin.db import Webhook

    return select(Webhook).where(Webhook.tenant_id == tenant_id)


def _post(hook, body: bytes, sleeper) -> None:
    try:
        public_webhook(hook.url)
    except ValueError:
        return
    stamp = str(int(time.time()))
    signature = sign_body(hook.secret, stamp.encode() + b"." + body)
    headers = {"X-Twin-Signature": signature, "X-Twin-Timestamp": stamp}
    for attempt, delay in enumerate((0, 0.5, 2)):
        if delay:
            sleeper(delay)
        try:
            response = httpx.post(hook.url, content=body, headers=headers, timeout=5)
        except httpx.HTTPError:
            continue
        if response is None or response.status_code < 500:
            return
        if attempt == 2:
            return


def _addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(host)}
    except ValueError:
        found = set()
        for info in socket.getaddrinfo(host, port):
            found.add(ipaddress.ip_address(info[4][0]))
        return found


def _blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
