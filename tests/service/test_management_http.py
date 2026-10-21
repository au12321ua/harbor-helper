"""Production browser/HTTP management; fake inputs and no external execution."""

import pytest
from support.attachment_support import archive
from support.browser_support import run_browser
from support.paths import REPO

from harbor_helper.service.primitives import ServiceError


@pytest.mark.browser
def test_management_production_wiring(http_service, request):
    p, url, root = http_service
    admin = next(u for u in p.data.users() if u["role"] == "admin")
    uploaded = p.app.attachments.write(
        admin, "attachment_create", "browser-input", {"name": "Team input"}, archive()
    )
    with pytest.raises(ServiceError):
        p.app.accept(
            p.actor,
            {"agent": "oracle", "dataset_id": "missing", "name": "Browser rejected intention"},
            "browser-rejected",
        )
    result = run_browser(
        request,
        REPO / "frontend/qa/production/management-production.mjs",
        env={
            **p.env,
            "HH_BROWSER_URL": url,
            "HH_BROWSER_EVIDENCE": str(root),
            "HH_VERSION": uploaded["version"]["id"],
        },
        timeout=90,
    )
    (root / "management-browser.stdout").write_text(result.stdout)
    assert "production management passed" in result.stdout
