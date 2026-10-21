"""Safe source diagnostics exercise the real child entry point without network."""

import io
import json
from contextlib import ExitStack

import httpx
import pytest
from harbor.auth.errors import NotAuthenticatedError
from harbor.registry.client.package import PackageDatasetClient

from harbor_helper.service import sources


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("secret-in-remote-error"), "source_network"),
        (httpx.ReadTimeout("secret-in-remote-error"), "source_network"),
        (httpx.ProxyError("secret-in-remote-error"), "source_network"),
        (NotAuthenticatedError("secret-in-remote-error"), "source_auth"),
        (ValueError("secret-in-remote-error"), "source_access"),
    ],
)
def test_source_child_errors_are_distinct_and_never_echo_remote_text(
    monkeypatch, capsys, error, expected
):
    async def fail(*_):
        raise error

    monkeypatch.setattr(PackageDatasetClient, "get_dataset_metadata", fail)
    monkeypatch.setattr(
        sources.sys, "stdin", io.StringIO(json.dumps({"reference": "team/data@1", "target": None}))
    )
    with ExitStack() as leases, pytest.raises(SystemExit):
        sources._main(leases, None)
    output = capsys.readouterr()
    assert json.loads(output.out)["error"] == expected
    assert "secret-in-remote-error" not in output.out + output.err


def test_wrapped_network_error_is_still_network():
    error = RuntimeError("outer")
    error.__cause__ = httpx.ConnectError("hidden")
    assert sources.source_error(error)["error"] == "source_network"
