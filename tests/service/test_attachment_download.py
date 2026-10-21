"""Team version downloads, isolated fake inputs and credentials only."""

import hashlib
import io
import zipfile

from support.attachment_support import archive
from support.service_support import client

from harbor_helper.service import access
from harbor_helper.service.application import Application


def test_team_download_is_one_version_and_disabled_is_archivable(data):
    app = Application(data.root)
    alice = next(u for u in data.users() if u["username"] == "alice")
    first = app.attachments.write(alice, "attachment_create", "first", {"name": "附件"}, archive())
    aid, vid = first["attachment"]["id"], first["version"]["id"]
    app.attachments.write(
        alice, "attachment_publish", "second", {"attachment_id": aid}, archive(b"v2")
    )
    app.attachments.update(alice, aid, {"enabled": False}, vid)
    response = client(data, "bob").get(f"/api/v1/attachment-versions/{vid}/download")
    assert response.status_code == 200
    assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert z.namelist() == ["sdk/readme"]
        assert z.read("sdk/readme") == b"v1"
    (data.root / "bundles" / first["version"]["bundle_id"] / "sdk/readme").write_bytes(b"tampered")
    assert client(data, "bob").get(f"/api/v1/attachment-versions/{vid}/download").status_code == 409


def test_download_scope_is_separate_and_snapshot_survives_original_removal(data):
    app = Application(data.root)
    alice = next(u for u in data.users() if u["username"] == "alice")
    first = app.attachments.write(alice, "attachment_create", "first", {"name": "Input"}, archive())
    vid = first["version"]["id"]
    browser = client(data)
    for scopes, expected in [
        (["read"], 403),
        (["attachments"], 403),
        (["attachment_download"], 200),
    ]:
        issued = access.issue(data, alice, "download", "Fake-test-password-2026", scopes, None)
        response = browser.get(
            f"/api/v1/attachment-versions/{vid}/download",
            headers={"Authorization": "Bearer " + issued["token"]},
        )
        assert response.status_code == expected
    stream, size, sha, name = app.attachments.download(alice, vid)
    try:
        import shutil

        shutil.rmtree(data.root / "bundles" / first["version"]["bundle_id"])
        payload = stream.read()
        assert len(payload) == size and hashlib.sha256(payload).hexdigest() == sha
        assert name.endswith("-v1.zip")
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            assert z.read("sdk/readme") == b"v1"
    finally:
        stream.close()
