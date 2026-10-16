from typing import Annotated

from fastapi import Depends, Request

from harbor_helper.service import policy
from harbor_helper.service.permissions import admin


def token(request):
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("hh_session", "")


class Dependencies:
    """Live application lookup; setup refreshes app.state without replacing closures."""

    def __init__(self, app, store):
        self.app = app
        self.store = store

        def actor(request: Request):
            user = self.data.actor(token(request))
            policy.authorize(user, request.scope["route"].endpoint.__name__)
            request.state.actor = user
            return user

        def administrator(user: Annotated[dict, Depends(actor)]):
            admin(user)
            return user

        self.actor = actor
        self.administrator = administrator

    @property
    def application(self):
        return self.app.state.application

    @application.setter
    def application(self, value):
        self.app.state.application = value

    @property
    def data(self):
        return self.application.data if self.application else None
