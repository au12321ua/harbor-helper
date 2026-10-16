"""Validate raw endpoint values before FastAPI can filter or add response fields."""

import functools
import inspect
import json
from types import UnionType
from typing import Annotated, Union, get_args, get_origin

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model
from starlette.responses import Response

from harbor_helper.service import dtos
from harbor_helper.service.browser_contracts import BROWSER, MACHINE
from harbor_helper.service.primitives import ServiceError


@functools.cache
def closed(annotation):
    """Close named DTOs recursively; explicit dictionaries stay open maps."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        annotation.model_rebuild()
        return create_model(
            annotation.__name__,
            __config__=ConfigDict(extra="forbid", strict=True),
            **{
                name: (closed(field.annotation), field)
                for name, field in annotation.model_fields.items()
            },
        )
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return Union[tuple(closed(a) for a in args)]  # noqa: UP007 (runtime type construction)
    if origin is Annotated:
        return Annotated[closed(args[0]), *args[1:]]
    if origin in (list, dict):
        return origin[tuple(closed(a) for a in args)]
    return annotation


@functools.cache
def adapter(annotation):
    return TypeAdapter(closed(annotation))


def validate_output(name, value, user=None, *, passthrough=False, status_code=200):
    model = (MACHINE if user and user.get("access_credential_id") else {}).get(
        name, BROWSER.get(name)
    )
    if model is None:
        return value
    try:
        raw = json.loads(value.body) if isinstance(value, Response) else value
        adapter(model).validate_python(raw, strict=True)
    except (ValueError, TypeError):
        # Do not let ValueError's request-error handler catch response validation.
        raise ServiceError(
            "service_unavailable", "Operation could not be completed safely", 503
        ) from None
    if passthrough:
        from fastapi.responses import JSONResponse

        return JSONResponse(raw, status_code=status_code)
    return value


class ContractRoute(APIRoute):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        call = self.dependant.call
        if call.__name__ not in BROWSER:
            return
        if inspect.iscoroutinefunction(call):

            @functools.wraps(call)
            async def checked(**values):
                return validate_output(
                    call.__name__,
                    await call(**values),
                    values.get("user"),
                    passthrough=self.response_model is dtos.Accepted,
                    status_code=self.status_code or 200,
                )
        else:

            @functools.wraps(call)
            def checked(**values):
                return validate_output(
                    call.__name__,
                    call(**values),
                    values.get("user"),
                    passthrough=self.response_model is dtos.Accepted,
                    status_code=self.status_code or 200,
                )

        self.dependant.call = checked
