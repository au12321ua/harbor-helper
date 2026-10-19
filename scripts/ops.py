#!/usr/bin/env python3
"""Non-mutating inspection, scoped snapshots and new-target OFFLINE validation.

This module deliberately imports no harbor_helper application or Store classes.
"""

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
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


def write_key(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


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
    except sqlite3.DatabaseError as error:
        raise ValueError(
            "Read-only database unavailable; recover hot journal with the product before retrying"
        ) from error
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


def active_reference(db):
    found = db.execute("SELECT * FROM master_active").fetchall()
    require(len(found) == 1 and found[0]["singleton"] == 1, "invalid active master reference")
    ref = dict(found[0])
    require(
        type(ref["generation"]) is int
        and ref["generation"] > 0
        and isinstance(ref["basename"], str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ref["basename"])
        and isinstance(ref["kcv"], str)
        and re.fullmatch("[a-f0-9]{64}", ref["kcv"]),
        "invalid active master reference",
    )
    return ref


def check_kcv(master, ref):
    expected = hmac.new(
        master, f"harbor-helper/master/{ref['generation']}".encode(), hashlib.sha256
    ).hexdigest()
    require(hmac.compare_digest(expected, ref["kcv"]), "active master KCV mismatch")


def startup_master(state):
    """Read-only preflight for one-time legacy upgrade, never active fallback."""
    with ro_db(state) as db:
        imported = db.execute("SELECT 1 FROM sqlite_master WHERE name='master_active'").fetchone()
    if imported:
        return current_master(state)
    config = read_json(state / "service.json")
    require("master_file" in config, "active master metadata missing")
    path = plain(config["master_file"])
    require(not path.resolve().is_relative_to(state.resolve()), "master must be outside state")
    meta = path.parent.stat()
    require(
        stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid() and not meta.st_mode & 0o022,
        "master directory must be protected",
    )
    return key_bytes(path)


def current_master(state, ref=None):
    config = read_json(state / "service.json")
    folder = plain(config["master_directory"])
    require(not folder.resolve().is_relative_to(state.resolve()), "master must be outside state")
    meta = folder.stat()
    require(
        stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid() and not meta.st_mode & 0o022,
        "master directory must be protected",
    )
    if ref is None:
        with ro_db(state) as db:
            ref = active_reference(db)
    raw = key_bytes(folder / ref["basename"])
    check_kcv(raw, ref)
    return raw


def validate_db(state, master):
    # Validate raw source schema without constructing/migrating a product Store.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with ro_db(state) as db:
        require(
            db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "database integrity failed"
        )
        ref = active_reference(db)
        check_kcv(master, ref)
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
            "master_active": ref,
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


def managed_http(base):
    """Resolve only the exact unit owned by a recorded systemd installation."""
    path = base / "instance.json"
    if not path.exists():
        return None
    record = read_json(path)
    require(
        record.get("format") == "harbor-helper-systemd-v1" and record.get("directory") == str(base),
        "invalid systemd instance identity",
    )
    name = record["instance"]
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name), "invalid systemd instance name")
    unit = f"harbor-helper-{name}-http.service"
    unit_file = plain(base / "units" / unit)
    if not record.get("installed", True):
        return None
    require(
        unit_file.read_text().startswith(f"# harbor-helper instance {record['owner']}\n"),
        "foreign systemd unit",
    )
    environment = {
        k: os.environ[k]
        for k in ("PATH", "LANG", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
        if k in os.environ
    }
    environment.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    result = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=MainPID,FragmentPath"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    require(Path(values["FragmentPath"]).resolve() == unit_file, "foreign systemd fragment")
    pid = int(values["MainPID"])
    if not pid:
        return None
    code = base / "releases" / record["release"]
    argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
    require(
        argv[:6]
        == [
            str(code / ".venv/bin/python"),
            "-m",
            "harbor_helper.commands.main",
            "service",
            "serve",
            "--root",
        ]
        and len(argv) > 6
        and argv[6] == str(base / "state"),
        "managed HTTP argv mismatch",
    )
    return {
        "pid": pid,
        "birth": birth(pid),
        "argv": argv,
        "code": str(code),
        "port": record["port"],
    }


def identity(path, state, http=False, *, record=None):
    if record is None and not path.exists():
        return {"state": "absent"}
    try:
        record = record if record is not None else read_json(path)
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
                ("supervise" in argv or ("service" in argv and "scheduler" in argv))
                and any("harbor_helper" in a for a in argv),
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
    managed = None
    managed_error = False
    try:
        managed = managed_http(base)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        managed_error = True
    result = {
        "http": {"state": "unknown", "reason": "systemd_identity_unavailable"}
        if managed_error
        else identity(base / "http.json", state, True, record=managed),
        "scheduler": identity(state / "scheduler.json", state),
        "api": {"alive": "unknown", "ready": "unknown"},
        "disk_free_bytes": shutil.disk_usage(state).free,
    }
    if result["http"]["state"] == "running":
        try:
            record = managed or read_json(base / "http.json")
            # Bind HTTP response to this exact process's loopback listening socket.
            sockets = {os.readlink(p) for p in Path(f"/proc/{record['pid']}/fd").iterdir()}
            listening = any(
                line.split()[1]
                in {f"0100007F:{record['port']:04X}", f"00000000:{record['port']:04X}"}
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
    result.extend(host_processes(state)["conflicts"])
    return result


def host_processes(state):
    """Detect readable references; unavailable metadata is an explicit scope limit."""
    conflicts, uninspectable = [], []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            pid = int(proc.name)
            identity = birth(pid)
            if identity is None:
                continue
            unreadable, referenced = False, False
            try:
                referenced = str(state).encode() in (proc / "cmdline").read_bytes()
            except (PermissionError, FileNotFoundError):
                unreadable = True
            try:
                referenced |= (proc / "cwd").resolve(strict=True).is_relative_to(state)
            except (PermissionError, FileNotFoundError):
                unreadable = True
            try:
                for fd in (proc / "fd").iterdir():
                    try:
                        referenced |= Path(
                            os.readlink(fd).removesuffix(" (deleted)")
                        ).is_relative_to(state)
                    except FileNotFoundError:
                        continue
                    except PermissionError:
                        unreadable = True
            except (PermissionError, FileNotFoundError):
                unreadable = True
            if birth(pid) != identity:
                continue
            if referenced:
                conflicts.append({"kind": "state_reference", "pid": pid, "birth": identity})
            if unreadable:
                detail = {"pid": pid, "birth": identity}
                for name in ("comm", "cgroup"):
                    try:
                        detail[name] = (proc / name).read_text()[:4096].strip()
                    except (PermissionError, FileNotFoundError):
                        detail[name] = "unavailable"
                try:
                    detail["status"] = {
                        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                        for line in (proc / "status").read_text().splitlines()
                        if line.split(":", 1)[0] in {"Uid", "Gid", "CapPrm"}
                    }
                except (PermissionError, FileNotFoundError):
                    detail["status"] = {}
                uninspectable.append(detail)
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            conflicts.append({"kind": "unknown", "pid": int(proc.name)})
    return {"conflicts": conflicts, "uninspectable": uninspectable}


def uninspectable_ids(observation):
    return {(row["pid"], row["birth"]) for row in observation["uninspectable"]}


def execution_quiescence(base, data):
    require(
        all(row["status"] in TERMINAL for row in data["runs"])
        and all(row["status"] != "preparing" for row in data["submissions"]),
        "unfinished work/resources; offline snapshot refused",
    )
    clean = []
    for row in data["runs"]:
        path = plain(base / "state/runs" / safe_id(row["id"]))
        if (path / "projects.json").exists() or row.get("started") is not None:
            projects = (
                read_json(path / "projects.json") if (path / "projects.json").exists() else []
            )
            cleanup = read_json(path / "cleanup.json") if (path / "cleanup.json").exists() else {}
            require(
                cleanup.get("confirmed") is True
                and set(projects) <= set(cleanup.get("projects", [])),
                "execution cleanup unconfirmed",
            )
            clean.append(row["id"])
    units = {}
    if (base / "instance.json").exists() and read_json(base / "instance.json").get(
        "installed", True
    ):
        record = read_json(base / "instance.json")
        require(
            record.get("format") == "harbor-helper-systemd-v1"
            and record.get("directory") == str(base),
            "instance ownership mismatch",
        )
        require(
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", record["instance"]), "invalid unit identity"
        )
        for part in ("http", "scheduler"):
            unit = f"harbor-helper-{record['instance']}-{part}.service"
            environment = {
                **os.environ,
                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
            }
            result = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ActiveState,MainPID,FragmentPath",
                ],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            value = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            require(
                value.get("ActiveState") in {"inactive", "failed"} and value.get("MainPID") == "0",
                "instance units not stopped",
            )
            require(
                Path(value["FragmentPath"]).resolve() == base / "units" / unit,
                "foreign unit identity",
            )
            units[part] = value
    return {
        "product_writer_lease": "exclusive",
        "units": units,
        "runs_terminal": len(data["runs"]),
        "resource_cleanup_confirmed": clean,
        "preparing_submissions": 0,
    }


@contextmanager
def writer_lease(state, existing=None, *, shared=False):
    """Coordinate all product Store users; an inherited manager lease stays held."""
    path = plain(state / "writer.lock")
    fd = (
        os.dup(existing.fileno())
        if existing is not None
        else os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    )
    with os.fdopen(fd, "rb") as file:
        meta = os.fstat(fd)
        require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == os.getuid()
            and not meta.st_mode & 0o077
            and meta.st_nlink == 1,
            "writer lease requires owned private regular file",
        )
        current = path.stat()
        require(
            (meta.st_dev, meta.st_ino) == (current.st_dev, current.st_ino),
            "writer lease identity mismatch",
        )
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("busy: product writers lease unavailable") from None
        yield file


RUNTIME_ENTRIES = {
    "queue.sqlite-wal",
    "queue.sqlite-shm",
    "queue.sqlite-journal",
    "control.lock",
    "writer.lock",
    "preparation.lock",
    "scheduler.json",
    "supervisor.lock",
    "scheduler.wake",
    "scheduler-stop.json",
    "evidence-locks",
}


def state_inventory(state):
    require(not (state / "queue.sqlite-journal").exists(), "busy: database journal present")
    result = {}
    for path in state.iterdir():
        if path.name in RUNTIME_ENTRIES:
            continue
        if path.is_dir():
            result.update({path.name + "/" + key: value for key, value in inventory(path).items()})
        else:
            result[path.name] = digest(path)
    return result


def content_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


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


def backup(args, *, writer=None):
    journal = Path(args.directory) / "updates/journal.json"
    if journal.exists():
        task = read_json(journal)
        require(
            task.get("phase") in {"succeeded", "failed", "cancelled"}
            or getattr(args, "upgrade_job", None) == task.get("id"),
            "upgrade_in_progress: backup deferred",
        )
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
        if (base / "instance.json").exists():
            deployment = read_json(base / "instance.json")
            require(
                deployment.get("format") == "harbor-helper-systemd-v1"
                and deployment.get("directory") == str(base)
                and deployment.get("release") == args.release,
                "systemd instance/release mismatch",
            )
            copy_stable(base / "instance.json", target / "deployment.json")
            metadata = target / "release-metadata"
            metadata.mkdir(mode=0o700)
            for name in ("pyproject.toml", "uv.lock"):
                source = base / "releases" / args.release / name
                if source.exists():
                    copy_stable(source, metadata / name)
            manifest["deployment_sha256"] = digest(target / "deployment.json")
            manifest["release_metadata"] = inventory(metadata)
        record = read_json(base / "http.json") if (base / "http.json").exists() else None
        if record:
            require(Path(record["code"]).name == args.release, "release/process record mismatch")
        read_json(state / "service.json")  # Validate nonregular input before opening the DB.
        with (
            writer_lease(state, writer, shared=args.kind == "online"),
            control(state, args.lock_timeout),
            ExitStack() as evidence_locks,
        ):
            before_state = state_inventory(state) if args.kind == "offline" else None
            with ro_db(state) as db:
                data = {"runs": rows(db, "runs"), "submissions": rows(db, "submissions")}
            if args.kind == "offline":
                quiescence = execution_quiescence(base, data)
                before_host = host_processes(state)
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
                        evidence_locks.enter_context(os.fdopen(fd, "rb"))
                        require(stat.S_ISREG(os.fstat(fd).st_mode), "nonregular evidence lock")
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            raise ValueError("deferred: run evidence busy") from None
            snapshot = target / "state"
            snapshot.mkdir(mode=0o700)
            if args.kind == "offline":
                # No journal and no product writer: preserve exact database bytes
                # so whole-state/source/snapshot inventories can be compared.
                copy_stable(state / "queue.sqlite", snapshot / "queue.sqlite")
            else:
                with ro_db(state) as source, sqlite3.connect(snapshot / "queue.sqlite") as dest:
                    deadline = time.monotonic() + 10

                    def progress(status, remaining, total):
                        require(time.monotonic() < deadline, "database snapshot timeout")

                    source.backup(dest, pages=256, progress=progress, sleep=0.05)
            manifest["db_snapshot_time"] = time.time()
            with ro_db(snapshot) as db:
                ref = active_reference(db)
            master = current_master(state, ref)
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
                    "writer.lock",
                    "preparation.lock",
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
                current_master(state, ref) == master
                and read_json(snapshot / "service.json") == read_json(state / "service.json"),
                "source/master changed during snapshot",
            )
            if args.kind == "offline":
                observed_writers = writers(base, data)
                require(
                    not observed_writers,
                    "busy/unknown: writer appeared during snapshot " + json.dumps(observed_writers),
                )
                after_host = host_processes(state)
                require(
                    uninspectable_ids(before_host) == uninspectable_ids(after_host),
                    "deferred: uninspectable process set changed",
                )
                manifest["host_observation"] = {
                    "scope": "same_uid_readable",
                    "other_uids": "not_observed",
                    "uninspectable": after_host["uninspectable"],
                }
                manifest["quiescence"] = quiescence
                manifest["claim"] = "product_writers_stopped_and_content_stable"
                manifest["included_runs"] = [r["id"] for r in frozen["runs"]]
                require(not manifest["missing"], "offline evidence missing")
                manifest["full_state"] = True
            validate_evidence(snapshot, frozen, manifest["included_runs"])
            if args.kind == "offline":
                after_state = state_inventory(state)
                copied_state = state_inventory(snapshot)
                require(
                    before_state == after_state == copied_state,
                    "state changed during offline snapshot",
                )
                manifest["content_stability"] = {
                    "files": after_state,
                    "inventory_sha256": content_digest(after_state),
                    "database_sha256": after_state["queue.sqlite"],
                }
            write_key(master_target, master)
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
    if "deployment_sha256" in manifest:
        require(
            digest(source / "deployment.json") == manifest["deployment_sha256"],
            "deployment metadata digest mismatch",
        )
        require(
            inventory(source / "release-metadata") == manifest["release_metadata"],
            "release metadata digest mismatch",
        )
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
    require(
        not (target.parent / "updates/journal.json").exists(),
        "upgrade-owned restore target refused",
    )
    require(not target.exists(), "target already exists")
    # Stage next to the new target; failures never leave a seemingly valid target.
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / (target.name + ".restore-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    try:
        copy_stable(source / "state", staging / "state")
        (staging / "private").mkdir(mode=0o700)
        basename = validated["master_active"]["basename"]
        write_key(staging / "private" / basename, master)
        config = read_json(staging / "state/service.json")
        config.pop("master_file", None)
        config["master_directory"] = str(target / "private")
        write_json(staging / "state/service.json", config)
        # All original process records removed; this tool never starts anything.
        for name in (
            "scheduler.json",
            "supervisor.lock",
            "control.lock",
            "writer.lock",
            "preparation.lock",
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
