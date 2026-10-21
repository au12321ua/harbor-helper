"""Shared test factories; each call owns its mutable state."""

from fastapi.testclient import TestClient

from harbor_helper.service.api import create_app
from support.service_support import PASSWORD, WRITE, client


def issue(data, username="alice", scopes=None, expires=None):
    c = client(data, username)
    body = {"name": "research", "current_password": PASSWORD}
    if scopes is not None:
        body["scopes"] = scopes
    if expires is not None:
        body["expires"] = expires
    r = c.post("/api/v1/access-credentials", json=body, headers=WRITE)
    assert r.status_code == 201, r.text
    value = r.json()
    p = TestClient(create_app(data.root, start_scheduler=False), raise_server_exceptions=False)
    p.headers.update({**WRITE, "Authorization": "Bearer " + value["token"]})
    return c, p, value
