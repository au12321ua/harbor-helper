"""M5 attachments (03 sections 6-7): fixed packages members publish, checked on upload,
resolved in load order into run configurations, and kept out of new runs once deleted."""

import io
import json
import tarfile
import uuid
import zipfile

import pytest
from support import (
    create_pat,
    invite_member,
    running,
    setup_admin,
    submit,
    wait_operation,
)
from test_configuration import agent_body, codes, error, resolve
from test_e2e_run import prepare_model
from test_recycle import bin_entry, purge

from maestro.db import schema as t
from maestro.execution.attachments import AttachmentStore, PackageError

BOOTSTRAP = b"#!/bin/bash\nset -e\necho installed\n"


def manifest(name="tools", version="1.0.0", **extra) -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "version": version,
        "effects": ["agent_tools"],
        "compatible_harnesses": ["fake-agent"],
        **extra,
    }


def tar_package(files: dict, wrapper: str | None = None, compress=True) -> bytes:
    """``files``: name -> bytes, or (bytes, mode), or a TarInfo type for special entries."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz" if compress else "w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(f"{wrapper}/{name}" if wrapper else name)
            if isinstance(content, bytes) and content in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.type = content
                info.linkname = "/etc/passwd"
                archive.addfile(info)
                continue
            data, mode = content if isinstance(content, tuple) else (content, 0o644)
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def zip_package(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            data, mode = content if isinstance(content, tuple) else (content, 0o644)
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def package(name="tools", version="1.0.0", bootstrap=True, extra_files=None, **fields) -> bytes:
    files = {"manifest.json": json.dumps(manifest(name, version, **fields)).encode()}
    if bootstrap:
        files["bootstrap.sh"] = (BOOTSTRAP, 0o755)
    files["tools/hello"] = (b"#!/bin/sh\necho hello\n", 0o755)
    files.update(extra_files or {})
    return tar_package(files)


def publish(api, data: bytes, expect=None):
    response = api.client.post(
        "/api/v1/attachments",
        content=data,
        headers=api._headers({"Content-Type": "application/gzip"}),
    )
    if expect is not None:
        assert response.status_code == expect, response.text
    return response


def problems(error: PackageError) -> set[tuple[str, str]]:
    return {(path, code) for path, code, _ in error.problems}


# --- package checks -----------------------------------------------------------------


@pytest.fixture
def packages(tmp_path):
    return AttachmentStore(tmp_path)


def unpack(packages, data):
    return packages.unpack(data, max_files=20, max_bytes=10_000)


def test_tar_and_zip_of_the_same_files_have_one_digest(packages):
    files = {
        "manifest.json": json.dumps(manifest()).encode(),
        "bootstrap.sh": (BOOTSTRAP, 0o755),
        "tools/hello": (b"hello\n", 0o644),
    }
    wrapped = unpack(packages, tar_package(files, wrapper="tools-1.0.0"))
    zipped = unpack(packages, zip_package(files))
    plain = unpack(packages, tar_package(files, compress=False))
    assert wrapped.content_digest == zipped.content_digest == plain.content_digest
    assert wrapped.has_bootstrap and wrapped.manifest["provides"] == {"tools": [], "env": []}
    assert [f["path"] for f in wrapped.files] == ["bootstrap.sh", "manifest.json", "tools/hello"]
    assert [f["executable"] for f in wrapped.files] == [True, False, False]
    # The mode is content: the same bytes without the executable bit are another package.
    files["tools/hello"] = (b"hello\n", 0o755)
    executable = unpack(packages, zip_package(files))
    assert executable.content_digest != plain.content_digest
    for staged in (wrapped, zipped, plain, executable):
        packages.discard(staged)
    assert [p.name for p in packages.root.iterdir()] == []


@pytest.mark.parametrize(
    ("entry", "content", "code"),
    [
        ("/etc/cron.d/x", b"x", "PATH"),
        ("../escape", b"x", "PATH"),
        ("a/../../escape", b"x", "PATH"),
        ("has space", b"x", "PATH"),
        ("link", tarfile.SYMTYPE, "FILE_TYPE"),
        ("hard", tarfile.LNKTYPE, "FILE_TYPE"),
    ],
)
def test_unsafe_entries_are_refused_before_anything_is_written(
    packages, tmp_path, entry, content, code
):
    data = tar_package({"manifest.json": json.dumps(manifest()).encode(), entry: content})
    with pytest.raises(PackageError) as raised:
        unpack(packages, data)
    assert code in {c for _, c in problems(raised.value)}
    assert not (tmp_path / "etc").exists() and not (tmp_path.parent / "escape").exists()
    assert [p.name for p in packages.root.iterdir()] == []


def test_duplicates_sizes_and_counts_are_limited(packages):
    duplicate = io.BytesIO()
    with tarfile.open(fileobj=duplicate, mode="w") as archive:
        for data in (b"one", b"two"):
            info = tarfile.TarInfo("same")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(PackageError) as raised:
        unpack(packages, duplicate.getvalue())
    assert ("/archive/same", "DUPLICATE") in problems(raised.value)
    with pytest.raises(PackageError) as raised:
        unpack(packages, tar_package({"big": b"x" * 10_001}))
    assert ("/archive/big", "TOO_LARGE") in problems(raised.value)
    many = {f"f{i}": b"" for i in range(21)}
    with pytest.raises(PackageError) as raised:
        unpack(packages, tar_package(many))
    assert "TOO_MANY_FILES" in {c for _, c in problems(raised.value)}
    with pytest.raises(PackageError, match="Not a tar or zip"):
        unpack(packages, b"not an archive at all")
    assert [p.name for p in packages.root.iterdir()] == []


def test_the_manifest_is_checked_strictly(packages):
    def fails(**fields):
        body = {k: v for k, v in {**manifest(), **fields}.items() if v is not None}
        with pytest.raises(PackageError) as raised:
            unpack(packages, tar_package({"manifest.json": json.dumps(body).encode()}))
        return problems(raised.value)

    with pytest.raises(PackageError, match="no manifest"):
        unpack(packages, tar_package({"bootstrap.sh": BOOTSTRAP}))
    assert fails(effects=["verifier"]) == {("/manifest/effects", "UNSUPPORTED")}
    assert fails(effects=["telepathy"]) == {("/manifest/effects", "ENUM")}
    assert fails(parameter_schema={}) == {("/manifest/parameter_schema", "UNSUPPORTED")}
    assert fails(surprise=1) == {("/manifest/surprise", "UNKNOWN_FIELD")}
    assert fails(name="../x", compatible_harnesses=[]) == {
        ("/manifest/name", "PATTERN"),
        ("/manifest/compatible_harnesses", "INVALID"),
    }
    assert fails(provides={"tools": ["a", "a"]}) == {("/manifest/provides/tools", "INVALID")}


# --- publishing ------------------------------------------------------------------------


def test_members_publish_fixed_versions_and_everyone_reads_them(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        member = invite_member(service, admin, "member")
        pat = create_pat(member)
        reader = create_pat(member, scope="read")
        assert publish(reader, package()).status_code == 403
        created = publish(pat, package(), expect=201).json()["data"]
        assert created["owner_username"] == "member" and created["has_bootstrap"]
        assert created["file_count"] == 3 and created["files"][0]["path"] == "bootstrap.sh"
        # Same name, version and content: the same version back, nothing new stored.
        again = publish(member, package(), expect=200).json()["data"]
        assert again["id"] == created["id"]
        changed = publish(member, package(extra_files={"README": b"new"}))
        assert error(changed) == (409, "ATTACHMENT_VERSION_EXISTS")
        assert changed.json()["error"]["suggested_actions"][0]["attachment_id"] == created["id"]
        unknown = publish(member, package("other", compatible_harnesses=["opencode"]))
        assert error(unknown) == (422, "ATTACHMENT_INVALID")
        bad = publish(member, package(effects=["scoring"]))
        assert bad.json()["error"]["field_errors"][0]["path"] == "/manifest/effects"
        listed = reader.get("/api/v1/attachments", expect=200).json()["data"]
        assert [a["id"] for a in listed] == [created["id"]] and listed[0]["files"] is None
        # The owner or an administrator disables; another member cannot.
        other = invite_member(service, admin, "other")
        path = f"/api/v1/attachments/{created['id']}/enabled"
        assert other.post(path, json={"enabled": False}).status_code == 403
        assert not pat.post(path, json={"enabled": False}, expect=200).json()["data"]["enabled"]
        assert admin.post(path, json={"enabled": True}, expect=200).json()["data"]["enabled"]
    stored = list((service.settings.data_dir / "attachments").iterdir())
    assert [p.name for p in stored] == [created["content_digest"].removeprefix("sha256:")]
    assert (stored[0] / "bootstrap.sh").read_bytes() == BOOTSTRAP


# --- resolution ------------------------------------------------------------------------


def attach(api, **kw) -> str:
    return publish(api, package(**kw), expect=201).json()["data"]["id"]


def test_attachments_resolve_in_order_with_sources_and_limits(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        model_id, harness_id = prepare_model(admin)
        member = invite_member(service, admin, "member")
        first = attach(member, name="sdk", provides={"env": ["SDK_HOME"]})
        second = attach(member, name="tools", bootstrap=False, provides={"tools": ["hello"]})
        body = agent_body(model_id, harness_id, attachments=[second, first])
        resolution = resolve(member, version_id, **body)
        assert resolution["blockers"] == []
        effective = resolution["effective_config"]
        assert [a["name"] for a in effective["attachments"]] == ["tools", "sdk"]
        assert effective["attachments"][1]["provides"] == {"env": ["SDK_HOME"], "tools": []}
        assert effective["bootstrap_timeout_sec"] == 600
        assert resolution["field_sources"]["/attachments"] == {"layer": "override"}
        assert resolution["field_sources"]["/timeouts/bootstrap_sec"]["layer"] == "team"
        # The order is part of the configuration.
        swapped = resolve(
            member, version_id, **agent_body(model_id, harness_id, attachments=[first, second])
        )
        assert swapped["config_digest"] != resolution["config_digest"]
        over = resolve(member, version_id, **body, timeouts={"bootstrap_sec": 4000})
        assert codes(over) == ["LIMIT_EXCEEDED"] and over["blockers"][0]["limit"] == 3600
        quiet = resolve(
            member, version_id, **agent_body(model_id, harness_id, attachments=[second])
        )
        assert quiet["effective_config"]["bootstrap_timeout_sec"] is None
        oracle = member.post(
            "/api/v1/config-resolutions",
            json={
                "dataset_version_id": version_id,
                "execution_mode": "oracle",
                "attachments": [first],
            },
        )
        assert oracle.json()["error"]["field_errors"][0]["code"] == "ORACLE_HAS_NO_ATTACHMENTS"


def test_attachment_blockers(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        model_id, harness_id = prepare_model(admin)
        service.attachments.adapters = None  # publish for a harness this executor lacks
        tools = attach(admin, name="tools", provides={"tools": ["hello"]})
        clash = attach(admin, name="more-tools", provides={"tools": ["hello"]})
        newer = attach(admin, name="tools", version="2.0.0")
        elsewhere = attach(admin, name="elsewhere", compatible_harnesses=["opencode"])
        anywhere = attach(admin, name="anywhere", compatible_harnesses=["*"])
        off = attach(admin, name="off")
        admin.post(f"/api/v1/attachments/{off}/enabled", json={"enabled": False}, expect=200)

        def blockers(*ids):
            found = resolve(
                admin, version_id, **agent_body(model_id, harness_id, attachments=list(ids))
            )
            return [(b["code"], b["path"]) for b in found["blockers"]]

        assert blockers(tools, anywhere) == []
        assert blockers(tools, clash) == [("ATTACHMENT_CONFLICT", "/attachments/1")]
        assert blockers(tools, newer) == [("ATTACHMENT_CONFLICT", "/attachments/1")]
        assert blockers(elsewhere) == [("ATTACHMENT_INCOMPATIBLE", "/attachments/0")]
        assert blockers(off) == [("DISABLED", "/attachments/0")]
        assert blockers("att_missing") == [("NOT_FOUND", "/attachments/0")]
        admin.put(
            "/api/v1/admin/team-policy",
            json={"values": {"run_max_attachments": 1}, "expected_revision": 0},
            expect=200,
        )
        assert blockers(tools, anywhere)[0] == ("LIMIT_EXCEEDED", "/attachments")


def test_runs_record_their_attachments_and_disabling_before_acceptance_refuses(service, version_id):
    with running(service) as client:
        admin = setup_admin(service, client)
        model_id, harness_id = prepare_model(admin)
        member = invite_member(service, admin, "member")
        tools = attach(member)
        body = agent_body(model_id, harness_id, attachments=[tools], timeouts={"bootstrap_sec": 90})
        accepted = submit(member, version_id, **body).json()["data"]
        wait_operation(member, accepted["operation_id"])
        run = member.get(f"/api/v1/runs/{accepted['run_id']}").json()["data"]
        effective = run["snapshot"]["effective"]
        assert effective["bootstrap_timeout_sec"] == 90
        assert effective["attachments"][0]["version_id"] == tools
        assert run["snapshot"]["provenance"]["reference_revisions"]["attachments"] == [tools]
        found = member.get(f"/api/v1/runs?attachment_version_id={tools}").json()["data"]
        assert [r["id"] for r in found] == [accepted["run_id"]]

        resolution = resolve(member, version_id, **body)
        member.post(f"/api/v1/attachments/{tools}/enabled", json={"enabled": False}, expect=200)
        refused = member.post(
            "/api/v1/runs",
            json={"name": "late", "resolution_id": resolution["resolution_id"]},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert error(refused) == (422, "CONFIG_UNAVAILABLE")
        assert refused.json()["error"]["field_errors"][0]["path"] == "/attachments/0"


def test_disabling_during_acceptance_is_caught_in_the_transaction(service, version_id, monkeypatch):
    from maestro.services.configuration import Resolver

    original = Resolver.resolve

    def resolve_then_disable(self, conn, request):
        resolved = original(self, conn, request)
        with service.db.write() as other:
            other.execute(t.attachment_versions.update().values(enabled=False))
        return resolved

    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        model_id, harness_id = prepare_model(admin)
        tools = attach(admin)
        monkeypatch.setattr(Resolver, "resolve", resolve_then_disable)
        refused = submit(admin, version_id, **agent_body(model_id, harness_id, attachments=[tools]))
        assert error(refused) == (409, "CONFIG_CHANGED")
        assert refused.json()["error"]["field_errors"][0]["path"] == "/attachments/0"


def test_deleting_and_purging_an_attachment(service, version_id):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        model_id, harness_id = prepare_model(admin)
        member = invite_member(service, admin, "member")
        other = invite_member(service, admin, "other")
        tools = attach(member)
        body = agent_body(model_id, harness_id, attachments=[tools])
        accepted = submit(member, version_id, **body).json()["data"]
        assert error(other.delete(f"/api/v1/attachments/{tools}")) == (403, "FORBIDDEN")
        busy = member.delete(f"/api/v1/attachments/{tools}")
        assert error(busy) == (409, "ATTACHMENT_IN_USE")
        member.post(f"/api/v1/runs/{accepted['run_id']}/cancel", expect=200)
        member.delete(f"/api/v1/attachments/{tools}", expect=200)
        assert member.get("/api/v1/attachments").json()["data"] == []
        assert codes(resolve(member, version_id, **body)) == ["DELETED"]
        assert purge(member, {"id": "x", "object_id": tools}).status_code == 403
        purge(admin, bin_entry(admin, tools)).raise_for_status()
        assert admin.get(f"/api/v1/attachments/{tools}").status_code == 410
        # The run keeps what it used; the files are gone.
        run = admin.get(f"/api/v1/runs/{accepted['run_id']}").json()["data"]
        assert run["snapshot"]["effective"]["attachments"][0]["name"] == "tools"
    assert list((service.settings.data_dir / "attachments").iterdir()) == []


def test_a_purge_keeps_files_another_version_still_holds(service):
    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        first = attach(admin)
        admin.delete(f"/api/v1/attachments/{first}", expect=200)
        purge(admin, bin_entry(admin, first)).raise_for_status()
        # Republishing the purged name and version is allowed; the content is stored again.
        again = attach(admin)
        stored = service.settings.data_dir / "attachments"
        assert again != first and len(list(stored.iterdir())) == 1
        assert (
            service.recycle.remove_attachment_files(
                admin.get(f"/api/v1/attachments/{again}").json()["data"]["content_digest"]
            )
            is None
        )
        assert len(list(stored.iterdir())) == 1


def test_uploads_are_size_limited_and_never_left_on_disk(service, monkeypatch):
    from maestro.domain import limits

    with running(service, run_worker=False) as client:
        admin = setup_admin(service, client)
        assert error(publish(admin, b"")) == (422, "ATTACHMENT_INVALID")
        monkeypatch.setattr(limits, "ATTACHMENT_UPLOAD_MAX_BYTES", 100)
        assert error(publish(admin, package())) == (413, "ATTACHMENT_TOO_LARGE")
        streamed = admin.client.post(
            "/api/v1/attachments",
            content=iter([b"x" * 60, b"x" * 60]),  # no Content-Length: counted while read
            headers=admin._headers({"Content-Type": "application/gzip"}),
        )
        assert error(streamed) == (413, "ATTACHMENT_TOO_LARGE")
        monkeypatch.setattr(limits, "ATTACHMENT_UPLOAD_MAX_BYTES", 1 << 20)
        assert error(publish(admin, b"garbage")) == (422, "ATTACHMENT_INVALID")
    leftovers = list((service.settings.data_dir / "attachments").iterdir())
    assert leftovers == []


def test_staging_left_by_a_stopped_process_is_removed_at_start(service):
    root = service.settings.data_dir / "attachments"
    (root / ".upload-x" / "files").mkdir(parents=True)
    (root / ".receive-y").write_bytes(b"half an upload")
    (root / ("a" * 64)).mkdir()  # published content stays
    assert service.maintenance.start()["attachment_staging_removed"] == 2
    assert [p.name for p in root.iterdir()] == ["a" * 64]
