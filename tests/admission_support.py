"""Shared test factories; each call owns its mutable state."""

from harbor_helper.service import admission
from harbor_helper.service.application import Application


def actor(data, name="alice"):
    return next(u for u in data.users() if u["username"] == name)


def accept(data, key, name="alice"):
    return Application(data.root).accept(actor(data, name), {"agent": "oracle"}, key)


def pause(data, paused=True):
    with data.store.control():
        return admission.set_maintenance(
            data, {"paused": paused, "reason": "scheduled maintenance"}
        )
