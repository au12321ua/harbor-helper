#!/usr/bin/env python3
"""Non-mutating inspection, scoped snapshots and new-target OFFLINE validation.

This module deliberately imports no harbor_helper application or Store classes.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import time
import urllib.request
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import quote

FORMAT = "harbor-helper-ops-v1"
TERMINAL = {"succeeded", "failed", "cancelled"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plain(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink path refused")
    return path


class NonregularFileError(ValueError):
    """Invalid local input must fail the command rather than appear merely unknown."""


@contextmanager
def regular_reader(path):
    path = plain(path)
    # Reject special files before opening (including devices). NONBLOCK and fstat
    # also cover replacement with a FIFO between the path check and open.
    if not stat.S_ISREG(path.lstat().st_mode):
        raise NonregularFileError("nonregular file refused")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise NonregularFileError("nonregular file refused")
        yield file


def read_json(path):
    with regular_reader(path) as file:
        return json.load(file)


def write_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x") as file:
        json.dump(data, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def digest(path):
    with regular_reader(path) as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def inventory(root):
    result = {}
    for path in sorted(plain(root).rglob("*")):
        plain(path)
        if path.is_dir():
            continue
        result[path.relative_to(root).as_posix()] = digest(path)
    return result


def key_bytes(path):
    path = plain(path)
    with regular_reader(path) as file:
        meta = os.fstat(file.fileno())
        require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == os.getuid()
            and stat.S_IMODE(meta.st_mode) == 0o600,
            "master requires owner 0600 regular file",
        )
        raw = file.read(33)
    require(len(raw) == 32, "master requires 32 bytes")
    return raw


@contextmanager
def ro_db(state):
    path = plain(state / "queue.sqlite")
    with regular_reader(path) as header:
        prefix = header.read(20)
    require(
        prefix[:16] == b"SQLite format 3\0" and prefix[18:20] == b"\1\1",
        "unsupported SQLite journal mode; read-only tool requires rollback journal",
    )
    db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        yield db
    finally:
        db.close()


def rows(db, table):
    require(
        table
        in {"runs", "submissions", "users", "credential_versions", "source_credentials", "bundles"},
        "unsupported table",
    )
    return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def schema(db):
    return {
        r[0]: [c[1] for c in db.execute(f'PRAGMA table_info("{r[0]}")')]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if re.fullmatch("[a-z_]+", r[0])
    }


def validate_db(state, master):
    # Validate raw source schema without constructing/migrating a product Store.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with ro_db(state) as db:
        require(
            db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "database integrity failed"
        )
        shape = schema(db)
        require(
            all(
                t in shape
                for t in ("runs", "submissions", "users", "credential_versions", "bundles")
            ),
            "unsupported schema",
        )
        users = {r["id"] for r in rows(db, "users")}
        runs = rows(db, "runs")
        ids = {r["id"] for r in runs}
        submissions = rows(db, "submissions")
        for r in runs:
            require(not r.get("parent") or r["parent"] in ids, "run parent missing")
        for r in submissions:
            require(
                r["user_id"] in users and (not r["run_id"] or r["run_id"] in ids),
                "submission ownership missing",
            )
        for row in submissions:
            frozen = json.loads(row["frozen"])["service"]
            require(
                all(
                    frozen.get(k) == row[column]
                    for k, column in (
                        ("user_id", "user_id"),
                        ("submitter", "submitter"),
                        ("submission_id", "id"),
                    )
                ),
                "submission frozen ownership mismatch",
            )
        encrypted = rows(db, "credential_versions")
        for r in encrypted:
            AESGCM(master).decrypt(
                r["nonce"], r["ciphertext"], f"{r['provider_id']}/{r['id']}/{r['version']}".encode()
            ).decode()
        hubs = rows(db, "source_credentials") if "source_credentials" in shape else []
        for r in hubs:
            AESGCM(master).decrypt(
                r["nonce"], r["ciphertext"], f"hub/{r['version']}".encode()
            ).decode()
        return {
            "schema": shape,
            "runs": runs,
            "submissions": submissions,
            "credentials_checked": len(encrypted) + len(hubs),
            "bundles": [r["id"] for r in rows(db, "bundles")],
        }


def birth(pid):
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except FileNotFoundError:
        return None


def identity(path, state, http=False):
    if not path.exists():
        return {"state": "absent"}
    try:
        record = read_json(path)
        pid = record["pid"]
        require(
            type(pid) is int and pid > 0 and isinstance(record["birth"], str),
            "invalid process record",
        )
        actual = birth(pid)
        if actual is None:
            return {"state": "stopped"}
        if actual != record["birth"]:
            return {"state": "unknown", "reason": "birth_mismatch"}
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
        require(str(state) in " ".join(argv), "state identity mismatch")
        if http:
            require(
                argv == record["argv"]
                and Path(f"/proc/{pid}/cwd").resolve() == Path(record["code"]),
                "http identity mismatch",
            )
        else:
            require(
                "supervise" in argv and any("harbor_helper" in a for a in argv),
                "scheduler argv mismatch",
            )
        result = {"state": "running", "pid": pid, "birth": actual}
        if not http:
            heartbeat = record.get("observed")
            result["heartbeat_age_seconds"] = (
                time.time() - heartbeat if type(heartbeat) in (int, float) else None
            )
        return result
    except NonregularFileError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unknown", "reason": "identity_unavailable"}


def inspect(base, backup_directory=None):
    state = plain(base / "state")
    result = {
        "http": identity(base / "http.json", state, True),
        "scheduler": identity(state / "scheduler.json", state),
        "api": {"alive": "unknown", "ready": "unknown"},
        "disk_free_bytes": shutil.disk_usage(state).free,
    }
    if result["http"]["state"] == "running":
        try:
            record = read_json(base / "http.json")
            # Bind HTTP response to this exact process's loopback listening socket.
            sockets = {os.readlink(p) for p in Path(f"/proc/{record['pid']}/fd").iterdir()}
            listening = any(
                line.split()[1] == f"0100007F:{record['port']:04X}"
                and line.split()[3] == "0A"
                and f"socket:[{line.split()[9]}]" in sockets
                for line in Path("/proc/net/tcp").read_text().splitlines()[1:]
            )
            require(listening, "listener identity unavailable")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(
                f"http://127.0.0.1:{record['port']}/api/v1/health", timeout=2
            ) as response:
                data = json.load(response)
            result["api"] = {
                k: data[k] if type(data.get(k)) is bool else "unknown" for k in ("alive", "ready")
            }
        except NonregularFileError:
            raise
        except (OSError, ValueError, KeyError):
            pass
    try:
        with ro_db(state) as db:
            result["runs"] = {
                r[0]: r[1] for r in db.execute("SELECT status,count(*) FROM runs GROUP BY status")
            }
    except NonregularFileError:
        raise
    except (sqlite3.Error, ValueError, OSError):
        result["database"] = "unknown/unsupported"
    completed = []
    if backup_directory and backup_directory.exists():
        for p in backup_directory.glob("snapshot-*/manifest.json"):
            try:
                manifest = read_json(p)
                if manifest.get("format") == FORMAT and manifest.get("completed"):
                    completed.append(manifest["created"])
            except NonregularFileError:
                raise
            except (OSError, ValueError, KeyError):
                pass
    result["backup_age_seconds"] = time.time() - max(completed) if completed else None
    return result


@contextmanager
def control(state, timeout):
    with regular_reader(state / "control.lock") as file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, "deferred: control lock timeout")
                time.sleep(0.05)
        yield


def writers(base, db_data):
    state = base / "state"
    result = []
    for path, http in ((base / "http.json", True), (state / "scheduler.json", False)):
        observed = identity(path, state, http)
        if (
            observed["state"] not in {"absent", "stopped"}
            and observed.get("reason") != "birth_mismatch"
        ):
            result.append({"kind": "record", "state": observed["state"]})
    for row in db_data["runs"]:
        if row.get("pid"):
            actual = birth(row["pid"])
            if actual and actual == row.get("birth"):
                result.append({"kind": "worker", "run": row["id"]})
            elif actual and not row.get("birth"):
                result.append({"kind": "unknown_worker_identity", "run": row["id"]})
    # Catch preparation threads/subprocesses and unrecorded HTTP/SQLite users.
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            if birth(int(proc.name)) is None:
                continue
            argv = (proc / "cmdline").read_bytes()
            cwd = (proc / "cwd").resolve()
            has_fd = any(
                Path(os.readlink(fd).removesuffix(" (deleted)")).is_relative_to(state)
                for fd in (proc / "fd").iterdir()
            )
            if str(state).encode() in argv or cwd.is_relative_to(state) or has_fd:
                result.append({"kind": "state_reference", "pid": int(proc.name)})
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            result.append({"kind": "unknown", "pid": int(proc.name)})
    return result


def safe_id(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value), "unsafe reference id"
    )
    return value


def copy_stable(source, destination):
    before = inventory(source) if source.is_dir() else digest(source)
    if source.is_dir():
        shutil.copytree(source, destination)
        after = inventory(source)
        copied = inventory(destination)
    else:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        after = digest(source)
        copied = digest(destination)
    require(before == after == copied, "source changed during snapshot")


def backup(args):
    base = plain(args.directory)
    state = base / "state"
    require(
        state.stat().st_uid == os.getuid() and not state.stat().st_mode & 0o077,
        "state requires owner-only directory",
    )
    output = plain(args.output)
    # Require a private destination outside all Git worktrees and the instance.
    require(
        not output.is_relative_to(base)
        and not any(
            ((p / ".git/HEAD").is_file() or (p / ".git").is_file())
            for p in (output, *output.parents)
        ),
        "backup output must be outside instance/Git",
    )
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(
        output.stat().st_uid == os.getuid() and stat.S_IMODE(output.stat().st_mode) == 0o700,
        "backup directory requires owner 0700",
    )
    identifier = "snapshot-" + uuid.uuid4().hex
    target = output / (identifier + ".incomplete")
    target.mkdir(mode=0o700)
    master_target = output / (identifier + ".master")
    manifest = {
        "format": FORMAT,
        "created": time.time(),
        "kind": args.kind,
        "full_state": False,
        "completed": False,
        "source_release": args.release,
        "included_runs": [],
        "active_runs": [],
        "preparing_submissions": [],
        "missing": [],
        "excluded": ["runtime process records and locks", "active run evidence (online)"],
    }
    require(re.fullmatch("[a-f0-9]{40}", args.release), "source release must be full SHA")
    try:
        record = read_json(base / "http.json") if (base / "http.json").exists() else None
        if record:
            require(Path(record["code"]).name == args.release, "release/process record mismatch")
        service = read_json(state / "service.json")
        master_path = plain(service["master_file"])
        require(not master_path.is_relative_to(state), "master must be outside state")
        master = key_bytes(master_path)
        with control(state, args.lock_timeout), ExitStack() as evidence_locks:
            data = validate_db(state, master)
            if args.kind == "offline":
                observed_writers = writers(base, data)
                require(
                    not observed_writers,
                    "busy/unknown: state writers have not exited " + json.dumps(observed_writers),
                )
            if args.kind == "online":
                # Never wait for a long archive/audit while holding global control.
                folder = plain(state / "evidence-locks")
                folder.mkdir(mode=0o700, exist_ok=True)
                for row in data["runs"]:
                    if row["status"] in TERMINAL and row.get("audit_status") == "clean":
                        path = plain(folder / (safe_id(row["id"]) + ".lock"))
                        fd = os.open(
                            path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
                        )
                        file = evidence_locks.enter_context(os.fdopen(fd, "rb"))
                        require(stat.S_ISREG(os.fstat(fd).st_mode), "nonregular evidence lock")
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            raise ValueError("deferred: run evidence busy") from None
            snapshot = target / "state"
            snapshot.mkdir(mode=0o700)
            with ro_db(state) as source, sqlite3.connect(snapshot / "queue.sqlite") as dest:
                # Bound backup retries; sqlite backup otherwise waits indefinitely on a busy DB.
                deadline = time.monotonic() + 10

                def progress(status, remaining, total):
                    require(time.monotonic() < deadline, "database snapshot timeout")

                source.backup(dest, pages=256, progress=progress, sleep=0.05)
            manifest["db_snapshot_time"] = time.time()
            frozen = validate_db(snapshot, master)
            manifest["schema"] = frozen["schema"]
            manifest["master_sha256"] = hashlib.sha256(master).hexdigest()
            manifest["active_runs"] = [
                r["id"] for r in frozen["runs"] if r["status"] not in TERMINAL
            ]
            manifest["preparing_submissions"] = [
                r["id"] for r in frozen["submissions"] if r["status"] == "preparing"
            ]
            config_names = [
                "service.json",
                "team.json",
                "limits.json",
                "web.json",
                "admission.json",
            ]
            before_configs = {
                name: digest(state / name) for name in config_names if (state / name).exists()
            }
            for name in before_configs:
                copy_stable(state / name, snapshot / name)
            require(
                "service.json" in before_configs and "team.json" in before_configs,
                "required configuration missing",
            )
            if args.kind == "offline":
                excluded = {
                    "queue.sqlite",
                    "queue.sqlite-wal",
                    "queue.sqlite-shm",
                    "queue.sqlite-journal",
                    "control.lock",
                    "scheduler.json",
                    "supervisor.lock",
                    "scheduler.wake",
                    "scheduler-stop.json",
                    "evidence-locks",
                } | set(config_names)
                for path in state.iterdir():
                    if path.name not in excluded:
                        copy_stable(path, snapshot / path.name)
            else:
                for name in ("bundles", "author-inputs"):
                    if (state / name).exists():
                        copy_stable(state / name, snapshot / name)
                (snapshot / "runs").mkdir()
                for row in frozen["runs"]:
                    if row["status"] not in TERMINAL:
                        continue
                    run_id = safe_id(row["id"])
                    # Audit-incomplete evidence must not be treated as safe export.
                    if row.get("audit_status") != "clean":
                        manifest["missing"].append({"run": run_id, "reason": "audit_not_clean"})
                        continue
                    path = state / "runs" / run_id
                    if path.is_dir():
                        copy_stable(path, snapshot / "runs" / run_id)
                        manifest["included_runs"].append(run_id)
                    else:
                        manifest["missing"].append({"run": run_id, "reason": "evidence_missing"})
            for bundle_id in frozen["bundles"]:
                if not (snapshot / "bundles" / safe_id(bundle_id)).is_dir():
                    manifest["missing"].append({"bundle": bundle_id})
            require(
                all(digest(state / name) == value for name, value in before_configs.items()),
                "configuration changed during snapshot",
            )
            require(
                key_bytes(master_path) == master
                and read_json(snapshot / "service.json") == service,
                "source/master changed during snapshot",
            )
            if args.kind == "offline":
                observed_writers = writers(base, data)
                require(
                    not observed_writers,
                    "busy/unknown: writer appeared during snapshot " + json.dumps(observed_writers),
                )
                manifest["included_runs"] = [r["id"] for r in frozen["runs"]]
                require(not manifest["missing"], "offline evidence missing")
                manifest["full_state"] = True
            validate_evidence(snapshot, frozen, manifest["included_runs"])
            with master_target.open("xb") as file:
                file.write(master)
            master_target.chmod(0o600)
            manifest["excluded_root_entries"] = sorted(
                p.name for p in state.iterdir() if not (snapshot / p.name).exists()
            )
            manifest["files"] = inventory(snapshot)
            manifest["completed"] = True
            manifest["scope"] = (
                "partial"
                if manifest["active_runs"]
                or manifest["preparing_submissions"]
                or manifest["missing"]
                else "listed_content_verified"
            )
            write_json(target / "manifest.json", manifest)
            os.rename(target, output / identifier)
        # No automatic retention: unknown/user files and all backups are retained.
        return {
            "snapshot": str(output / identifier),
            "kind": args.kind,
            "full_state": manifest["full_state"],
            "scope": manifest["scope"],
            "active_runs": manifest["active_runs"],
            "preparing_submissions": manifest["preparing_submissions"],
            "missing": manifest["missing"],
        }
    except BaseException:
        # Preserve incomplete evidence, but do not leave a key for a failed snapshot.
        master_target.unlink(missing_ok=True)
        raise


def validate_evidence(state, data, included):
    submissions = {r["id"]: r for r in data["submissions"]}
    for run_id in included:
        binding = read_json(state / "runs" / safe_id(run_id) / "manifest.json").get("service", {})
        row = submissions.get(binding.get("submission_id"))
        require(
            row is not None
            and run_id in (row["run_id"], row["target_id"])
            and binding.get("user_id") == row["user_id"]
            and binding.get("submitter") == row["submitter"],
            "run evidence ownership mismatch",
        )


def restore(args):
    source = plain(args.snapshot)
    require(
        re.fullmatch("snapshot-[a-f0-9]{32}", source.name), "incomplete/unpublished snapshot path"
    )
    manifest = read_json(source / "manifest.json")
    require(
        manifest.get("format") == FORMAT and manifest.get("completed") is True,
        "incomplete/unsupported snapshot",
    )
    require(manifest["source_release"] == args.release, "source release mismatch")
    require(inventory(source / "state") == manifest["files"], "snapshot digest mismatch")
    master = key_bytes(args.master_file)
    require(
        hashlib.sha256(master).hexdigest() == manifest["master_sha256"],
        "master does not match snapshot",
    )
    validated = validate_db(source / "state", master)
    require(validated["schema"] == manifest["schema"], "schema mismatch")
    validate_evidence(source / "state", validated, manifest["included_runs"])
    target = plain(args.target)
    require(not target.exists(), "target already exists")
    # Stage next to the new target; failures never leave a seemingly valid target.
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / (target.name + ".restore-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    try:
        copy_stable(source / "state", staging / "state")
        (staging / "private").mkdir(mode=0o700)
        (staging / "private/master.key").write_bytes(master)
        (staging / "private/master.key").chmod(0o600)
        config = read_json(staging / "state/service.json")
        config["master_file"] = str(target / "private/master.key")
        write_json(staging / "state/service.json", config)
        # All original process records removed; this tool never starts anything.
        for name in (
            "scheduler.json",
            "supervisor.lock",
            "control.lock",
            "scheduler.wake",
            "scheduler-stop.json",
        ):
            (staging / "state" / name).unlink(missing_ok=True)
        result = {
            "format": FORMAT,
            "source_release": args.release,
            "offline_validation": "passed",
            "credentials_checked": validated["credentials_checked"],
            "scope": manifest["scope"],
            "full_state": manifest["full_state"],
            "active_runs": manifest["active_runs"],
            "preparing_submissions": manifest["preparing_submissions"],
            "missing": manifest["missing"],
            "automatically_startable": False,
            "warning": "Offline content validation only. Review absolute frozen paths and interrupted work before any manual start.",
        }
        write_json(staging / "restore-check.json", result)
        os.rename(staging, target)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--directory", type=Path, required=True)
    check.add_argument("--backups", type=Path)
    snap = commands.add_parser("backup")
    snap.add_argument("--directory", type=Path, required=True)
    snap.add_argument("--output", type=Path, required=True)
    snap.add_argument("--release", required=True)
    snap.add_argument("--kind", choices=["online", "offline"], default="online")
    snap.add_argument("--lock-timeout", type=float, default=2)
    restored = commands.add_parser("restore-check")
    restored.add_argument("--snapshot", type=Path, required=True)
    restored.add_argument("--master-file", type=Path, required=True)
    restored.add_argument("--target", type=Path, required=True)
    restored.add_argument("--release", required=True)
    args = parser.parse_args()
    try:
        result = (
            inspect(plain(args.directory), args.backups)
            if args.command == "check"
            else backup(args)
            if args.command == "backup"
            else restore(args)
        )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001
        # Exception details can contain DB/config/credential values. Output class only.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "reason": str(error)
                    if isinstance(error, ValueError)
                    else "operation unavailable; inspect private inputs",
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
