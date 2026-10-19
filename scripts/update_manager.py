"""Single-instance, durable host upgrade executor. HTTP only writes its spool."""

import fcntl
import hashlib
import importlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import ops

# Executor owns the only live migration capability.
import service as host
import service_environment

# Copy of this exact stdlib-only protocol ships in every immutable manager set.
try:
    protocol = importlib.import_module("upgrade_protocol")
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from harbor_helper.persistence import upgrades as protocol


def save(base, value, **fields):
    following = {
        **value,
        **fields,
        "sequence": value.get("sequence", 0) + 1,
        "updated": time.time(),
    }
    protocol.durable(base / "updates/journal.json", following)
    value.clear()
    value.update(following)


def command(argv, *, env, cwd=None, timeout=120, pass_fds=()):
    """Disk-backed bounded diagnostics; no credential-bearing command output in errors."""
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            pass_fds=pass_fds,
            start_new_session=True,
        )
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise ValueError("Upgrade subprocess timed out") from None
        if child.returncode:
            raise ValueError("Upgrade subprocess failed")
        output.seek(0, 2)
        ops.require(output.tell() <= 1048576, "Upgrade output exceeds limit")
        output.seek(0)
        return output.read().decode().strip()


def environment(base, *, network=False):
    env = {
        "PATH": os.defpath + ":/usr/local/bin",
        "HOME": str(base / "home"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "UV_CACHE_DIR": str(base / "updates/uv-cache"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if network:
        configured = service_environment.environment(base)
        env.update(
            {key: configured[key] for key in service_environment.TRANSPORT if key in configured}
        )
    return env


def source(base):
    path = base / "private/update.toml"
    with ops.regular_reader(path) as file:
        raw = file.read(16385)
        metadata = os.fstat(file.fileno())
        ops.require(
            metadata.st_uid == os.getuid() and metadata.st_nlink == 1,
            "Update config ownership invalid",
        )
    ops.require(
        len(raw) <= 16384 and not path.stat().st_mode & 0o077,
        "Update config must be private and bounded",
    )
    config = tomllib.loads(raw.decode("utf-8"))["updates"]
    ops.require(
        set(config) <= {"repository", "branch"} and config["branch"] in {"master", "dev"},
        "Invalid update source",
    )
    repository = config["repository"]
    ops.require(
        isinstance(repository, str)
        and len(repository) < 2048
        and not any(c in repository for c in "\0\r\n"),
        "Invalid repository",
    )
    parsed = urllib.parse.urlsplit(repository)
    ops.require(
        parsed.password is None
        and (parsed.username is None or parsed.scheme == "ssh")
        and not parsed.query
        and not parsed.fragment,
        "Credentials in repository URL forbidden",
    )
    ops.require(
        parsed.scheme in {"https", "ssh", "file"} or repository.startswith("/"),
        "Use explicit HTTPS or SSH URL",
    )
    env = environment(base, network=True)
    if parsed.scheme == "ssh":
        known = base / "private/known_hosts"
        key = base / "private/deploy-key"
        for item in (known, key):
            with ops.regular_reader(item):
                ops.require(not item.stat().st_mode & 0o077, "SSH trust and key must be private")
        # base has already passed the installer's strict path grammar.
        env["GIT_SSH_COMMAND"] = (
            f"/usr/bin/ssh -F /dev/null -oBatchMode=yes -oStrictHostKeyChecking=yes -oUserKnownHostsFile={known} -oIdentitiesOnly=yes -i {key} -oConnectTimeout=15"
        )
    helper = base / "private/git-askpass"
    if parsed.scheme == "https" and helper.exists():
        with ops.regular_reader(helper):
            ops.require(not helper.stat().st_mode & 0o077, "HTTPS askpass must be private")
        env["GIT_ASKPASS"] = str(helper)
    return config, hashlib.sha256(raw).hexdigest(), env


def git(base, env, *arguments):
    return command(["git", "--git-dir", str(base / "updates/mirror.git"), *arguments], env=env)


def fetch(base):
    config, digest, env = source(base)
    mirror = base / "updates/mirror.git"
    if not mirror.exists():
        command(["git", "init", "--bare", str(mirror)], env=env)
    git(
        base,
        env,
        "-c",
        "protocol.file.allow=always",
        "fetch",
        "--no-tags",
        "--force",
        "--",
        config["repository"],
        f"refs/heads/{config['branch']}:refs/heads/source",
    )
    return config, digest, env, git(base, env, "rev-parse", "refs/heads/source")


def ancestor(base, env, first, second):
    try:
        git(base, env, "merge-base", "--is-ancestor", first, second)
        return True
    except ValueError:
        return False


def relation(base, env, current, target):
    try:
        git(base, env, "cat-file", "-e", current + "^{commit}")
    except ValueError:
        return "unknown"
    if current == target:
        return "current"
    if ancestor(base, env, current, target):
        return "update"
    if ancestor(base, env, target, current):
        return "behind"
    return "diverged"


def contract(base, env, target):
    value = json.loads(git(base, env, "show", target + ":update-contract.json"))
    ops.require(
        value
        == {
            "format": 1,
            "manager_protocol": 1,
            "journal_protocol": 1,
            "barrier": True,
            "probe_protocol": 1,
            "python": ">=3.12,<3.14",
        },
        "Target update contract unsupported",
    )
    project = tomllib.loads(git(base, env, "show", target + ":pyproject.toml"))["project"]
    ops.require(
        project.get("requires-python", "").replace(" ", "") == value["python"],
        "Target Python requirements unsupported",
    )
    return value


def check(base, record, identifier):
    config, digest, env, target = fetch(base)
    result = {
        "check_id": identifier,
        "target_sha": target,
        "config_digest": digest,
        "source": config,
        "relation": relation(base, env, record["release"], target),
    }
    contract(base, env, target)
    result["metadata"] = "passed"
    result["message"] = git(base, env, "log", "-1", "--format=%s", target)[:512]
    return result


def install_target(base, value):
    config, digest, env, tip = fetch(base)
    target = value["target"]
    ops.require(digest == value["config_digest"], "Update configuration changed; check again")
    ops.require(
        relation(base, env, value["source_release"], target) == "update"
        and ancestor(base, env, target, tip),
        "Target withdrawn or relationship changed; check again",
    )
    contract(base, env, target)
    code = base / "releases" / target
    if not code.exists():
        stage = base / "releases" / (".prepare-" + value["id"])
        stage.mkdir(mode=0o700)
        archive = base / "updates" / (value["id"] + ".tar")
        git(base, env, "archive", "--format=tar", "--output=" + str(archive), target)
        command(["tar", "-xf", str(archive), "-C", str(stage)], env=env)
        archive.unlink()
        stage.rename(code)
    ops.require(
        (code / "src/harbor_helper/static/index.html").is_file(), "Production static missing"
    )
    static = {
        str(p.relative_to(code)): ops.digest(p)
        for p in (code / "src/harbor_helper/static").rglob("*")
        if p.is_file()
    }
    build = hashlib.sha256()
    static_root = code / "src/harbor_helper/static"
    for path in sorted(static_root.rglob("*")):
        if path.is_file() and path.name != "index.html":
            build.update(str(path.relative_to(static_root)).encode())
            build.update(path.read_bytes())
    embedded = re.search(
        r'<meta name="hh-build" content="([a-f0-9]{64})"', (static_root / "index.html").read_text()
    )
    ops.require(
        embedded and embedded.group(1) == build.hexdigest(),
        "Production page build metadata mismatch",
    )
    save(base, value, build_manifest=static)
    installed = protocol.private_json(base / "updates/enabled.json")
    uv = installed.get("uv") or shutil.which("uv")
    ops.require(uv, "uv unavailable")
    command(
        [uv, "sync", "--locked", "--no-dev", "--python", sys.executable],
        env=env,
        cwd=code,
        timeout=600,
    )
    ops.require(
        all(ops.digest(code / path) == sha for path, sha in static.items()),
        "Static build changed during installation",
    )
    protocol.durable(code / ".release-source.json", {**config, "commit": target})
    (code / ".installed").touch(mode=0o600)
    return code


def snapshot(base, record, value, kind, lease=None):
    output = base.parent / (base.name + "-update-backups")
    saved = ops.backup(
        SimpleNamespace(
            directory=base,
            output=output,
            release=record["release"],
            kind=kind,
            lock_timeout=5,
            upgrade_job=value["id"],
        ),
        writer=lease,
    )
    path = Path(saved["snapshot"])
    ops.restore(
        SimpleNamespace(
            snapshot=path,
            master_file=output / (path.name + ".master"),
            target=output / (path.name + "-restore-check"),
            release=record["release"],
        )
    )
    if kind == "offline":
        private = path / "deployment-private"
        ops.copy_stable(base / "private", private)
        save(
            base,
            value,
            snapshot=str(path),
            private_inventory=ops.inventory(base / "private"),
            baseline=ops.state_inventory(base / "state"),
            host_uninspectable=sorted(ops.uninspectable_ids(ops.host_processes(base / "state"))),
        )
    return path


def probe(base, value, code, snap, *, complete):
    folder = (
        base / "updates" / ("probe-" + value["id"] + "-" + ("offline" if complete else "online"))
    )
    ops.require(not folder.exists(), "Probe directory already exists; inspect retained task")
    folder.mkdir(mode=0o700)
    ops.copy_stable(snap / "state", folder / "state")
    (folder / "private").mkdir(mode=0o700)
    master = ops.key_bytes(snap.parent / (snap.name + ".master"))
    with ops.ro_db(folder / "state") as db:
        basename = ops.active_reference(db)["basename"]
    ops.write_key(folder / "private" / basename, master)
    result = command(
        [
            str(code / ".venv/bin/python"),
            str(code / "scripts/update_probe.py"),
            "--root",
            str(folder / "state"),
            "--release",
            value["target"],
            "--original",
            str(base / "state"),
            "--master-directory",
            str(folder / "private"),
            *(["--complete"] if complete else []),
        ],
        env=environment(base),
        timeout=120,
    )
    parsed = json.loads(result)
    save(base, value, **{"offline_probe" if complete else "online_probe": parsed})
    return parsed


def observe(base, record):
    return json.loads(host.run_python(base, record, host.OBSERVE))


def restore_semantics(base, value):
    state = base / "state"
    with ops.control(state, 5):
        for name, content in value["original_files"].items():
            if content is None:
                (state / name).unlink(missing_ok=True)
            else:
                protocol.durable(state / name, content)
    protocol.sync_directory(state)


def unit_states(record):
    return {
        part: host.systemctl(
            "show", host.unit_name(record, part), "--property=ActiveState", "--value"
        )
        for part in ("http", "scheduler")
    }


def start_original(base, value):
    record = ops.read_json(base / "instance.json")
    for part, status in value["original_units"].items():
        host.systemctl(
            "start" if status in {"active", "activating"} else "stop", host.unit_name(record, part)
        )


def target_validate(base, value, lease, release):
    code = base / "releases" / release
    command(
        [
            str(code / ".venv/bin/python"),
            str(code / "scripts/update_probe.py"),
            "--root",
            str(base / "state"),
            "--release",
            release,
            "--lease-fd",
            str(lease.fileno()),
            "--complete",
        ],
        env=environment(base),
        timeout=120,
        pass_fds=(lease.fileno(),),
    )


def ready(base, value):
    record = ops.read_json(base / "instance.json")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            http_ready = True
            if value["original_units"]["http"] in {"active", "activating"}:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(
                    f"http://{record['host']}:{record['port']}/api/v1/build", timeout=2
                ) as response:
                    http_ready = bool(json.load(response)["build"])
            scheduler_ready = True
            if value["original_units"]["scheduler"] in {"active", "activating"}:
                identity = ops.read_json(base / "state/scheduler.json")
                scheduler_ready = (
                    identity.get("state") == "ready"
                    and time.time() - identity.get("observed", 0) <= 10
                )
            if http_ready and scheduler_ready:
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.2)
    raise ValueError("Post-release HTTP/scheduler readiness failed")


def _barrier_ready_once(base, value):
    record = ops.read_json(base / "instance.json")
    for part, original in value["original_units"].items():
        if original in {"active", "activating"}:
            ops.require(
                host.systemctl(
                    "show", host.unit_name(record, part), "--property=ActiveState", "--value"
                )
                == "active",
                "Target unit not active under barrier",
            )
    if value["original_units"]["http"] in {"active", "activating"}:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(
            f"http://{record['host']}:{record['port']}/api/v1/build", timeout=3
        ) as response:
            expected = hashlib.sha256()
            static = base / "releases" / record["release"] / "src/harbor_helper/static"
            for path in sorted(static.rglob("*")):
                if path.is_file() and path.name != "index.html":
                    expected.update(str(path.relative_to(static)).encode())
                    expected.update(path.read_bytes())
            ops.require(
                json.load(response) == {"build": expected.hexdigest()},
                "Target HTTP build identity mismatch",
            )


def barrier_ready(base, value):
    deadline = time.monotonic() + 20
    while True:
        try:
            return _barrier_ready_once(base, value)
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def clear_barrier(base, value):
    marker = base / "state/.upgrade.json"
    if marker.exists():
        ops.require(
            protocol.private_json(marker)["job"] == value["id"], "Barrier ownership mismatch"
        )
        marker.unlink()
    else:
        ops.require(value.get("commit_decided"), "Missing barrier before commit")
    protocol.sync_directory(marker.parent)
    save(base, value, barrier=False, phase="releasing")


def activate(base, release):
    manager = base / "manager"
    sets = manager / "sets"
    sets.mkdir(mode=0o700, exist_ok=True)
    target = sets / release
    code = base / "releases" / release
    if not target.exists():
        stage = sets / (".stage-" + release)
        stage.mkdir(mode=0o700, exist_ok=True)
        for path in (code / "scripts").glob("*.py"):
            shutil.copyfile(path, stage / path.name)
        shutil.copyfile(
            code / "src/harbor_helper/persistence/upgrades.py", stage / "upgrade_protocol.py"
        )
        (stage / "collection.json").unlink(missing_ok=True)
        manifest = ops.inventory(stage)
        protocol.durable(stage / "collection.json", manifest)
        protocol.sync_directory(stage)
        stage.rename(target)
        protocol.sync_directory(sets)
    manifest = protocol.private_json(target / "collection.json")
    ops.require(
        {
            k: v
            for k, v in ops.inventory(target).items()
            if k != "collection.json" and not ("__pycache__/" in k and k.endswith(".pyc"))
        }
        == manifest,
        "Manager collection modified",
    )
    # Bootstrap never changes when a later collection is activated.
    bootstrap = manager / "service.py"
    text = """#!/usr/bin/env python3
import json, os, runpy, sys
sys.dont_write_bytecode = True
from pathlib import Path
base = Path(__file__).resolve().parent
with (base / "current.json").open() as file:
    release = json.load(file)["release"]
if len(release) != 40 or any(c not in "0123456789abcdef" for c in release):
    raise ValueError("Invalid manager pointer")
code = base / "sets" / release
sys.path.insert(0, str(code))
runpy.run_path(str(code / "service.py"), run_name="__main__")
"""
    if not bootstrap.exists() or bootstrap.read_text() != text:
        temporary = manager / ".bootstrap-next"
        temporary.write_text(text)
        os.replace(temporary, bootstrap)
    protocol.durable(manager / "current.json", {"release": release, "protocol": 1})


def finish(base, value):
    ops.require(value.get("commit_decided"), "No durable commit decision")
    start_original(base, value)
    if value.get("barrier"):
        clear_barrier(base, value)
    ready(base, value)
    save(base, value, phase="succeeded", manager_activation_pending=True)
    activate(base, value.get("accepted_release", value["target"]))
    save(base, value, manager_activation_pending=False)


def rollback(base, value):
    """Only before commit; staging/rename boundaries are journalled, never guessed."""
    ops.require(
        not value.get("commit_decided"), "Committed business state must never be rolled back"
    )
    host.stop(base, ops.read_json(base / "instance.json"))
    snap = Path(value["snapshot"])
    manifest = ops.read_json(snap / "manifest.json")
    ops.require(ops.inventory(snap / "state") == manifest["files"], "Snapshot changed")
    ops.require(
        ops.inventory(base / "private") == value["private_inventory"],
        "External configuration/key changed",
    )
    ops.validate_db(snap / "state", ops.key_bytes(snap.parent / (snap.name + ".master")))
    state, stage = base / "state", base / ("state-restore-" + value["id"])
    failed = base / ("state-failed-" + value["id"])
    if value.get("restore_step") is None:
        with ops.writer_lease(state):
            ops.require(
                ops.state_inventory(state) == value["live_baseline"],
                "Live state changed; manual recovery required",
            )
            ops.copy_stable(snap / "state", stage)
            protocol.durable(stage / ".upgrade.json", {"protocol": 1, "job": value["id"]})
            save(
                base,
                value,
                phase="restoring",
                restore_step="staged",
                restore_baseline=ops.state_inventory(stage),
            )
    if value["restore_step"] == "staged":
        if state.exists():
            with ops.writer_lease(state):
                ops.require(
                    not failed.exists() and ops.state_inventory(state) == value["live_baseline"],
                    "Restore source changed",
                )
                save(base, value, restore_step="rename_old_pending")
                state.rename(failed)
                protocol.sync_directory(base)
        else:
            raise ValueError("Missing state before journalled rename")
    if value["restore_step"] == "rename_old_pending":
        if state.exists() and not failed.exists():
            with ops.writer_lease(state):
                ops.require(
                    ops.state_inventory(state) == value["live_baseline"], "Restore source changed"
                )
                state.rename(failed)
                protocol.sync_directory(base)
        ops.require(
            not state.exists() and failed.exists() and stage.exists(),
            "Unexpected restore directories",
        )
        ops.require(
            ops.state_inventory(stage) == value["restore_baseline"], "Restore staging changed"
        )
        save(base, value, restore_step="rename_new_pending")
    if value["restore_step"] == "rename_new_pending":
        if stage.exists() and not state.exists():
            stage.rename(state)
            protocol.sync_directory(base)
        ops.require(
            state.exists()
            and not stage.exists()
            and ops.state_inventory(state) == value["restore_baseline"],
            "Restore destination changed",
        )
        save(base, value, restore_step="installed")
    previous = value["original_record"]
    host.units(base, previous)
    protocol.durable(base / "instance.json", previous)
    with ops.writer_lease(state) as lease:
        target_validate(base, value, lease, previous["release"])
        restore_semantics(base, value)
        save(base, value, live_baseline=ops.state_inventory(state))
    start_original(base, value)
    save(
        base,
        value,
        commit_decided=True,
        accepted_release=previous["release"],
        recovery=True,
        phase="commit_decided",
    )
    clear_barrier(base, value)
    ready(base, value)
    save(base, value, phase="failed", recovered=True, manager_activation_pending=False)


def upgrade(base, record, request, identifier):
    payload = request["payload"]
    checked = protocol.private_json(base / "updates/results" / (payload["check_id"] + ".json"))[
        "result"
    ]
    ops.require(
        checked["relation"] == "update"
        and checked["target_sha"] == payload["target_sha"]
        and checked["config_digest"] == payload["config_digest"],
        "Confirmed metadata mismatch",
    )
    value: dict = {
        "protocol": 1,
        "id": identifier,
        "actor": request["actor"],
        "phase": "preparing",
        "source_release": record["release"],
        "target": payload["target_sha"],
        "config_digest": payload["config_digest"],
        "barrier": False,
        "commit_decided": False,
        "migration_crash_policy": "needs_manual",
        "original_record": record,
    }
    save(base, value)
    try:
        code = install_target(base, value)
        ops.require(
            shutil.disk_usage(base).free
            > sum(p.stat().st_size for p in (base / "state").rglob("*") if p.is_file()) * 4
            + 104857600,
            "Insufficient backup/staging space",
        )
        online = snapshot(base, record, value, "online")
        probe(base, value, code, online, complete=False)
        with ops.control(base / "state", 5):
            previous = observe(base, record)
            ops.require(
                previous["intent"]["phase"] != "draining",
                "External draining already owns maintenance",
            )
            original = {
                name: ops.read_json(base / "state" / name)
                if (base / "state" / name).exists()
                else None
                for name in ("admission.json", "shutdown.json")
            }
            save(
                base,
                value,
                phase="waiting",
                original_files=original,
                original_units=unit_states(record),
            )
            admission = previous["maintenance"]
            protocol.durable(
                base / "state/admission.json",
                {**admission, "paused": True, "reason": "Service update"},
            )
        while True:
            controls(base, value)
            if value["phase"] == "cancelled":
                return
            counts = observe(base, record)["counts"]
            save(base, value, waiting_counts=counts)
            if not sum(v for k, v in counts.items() if k != "audit_incomplete"):
                break
            if value["original_units"]["scheduler"] not in {"active", "activating"}:
                host.systemctl("start", host.unit_name(record, "scheduler"))
            time.sleep(1)
        _config, digest, env, tip = fetch(base)
        ops.require(
            digest == value["config_digest"] and ancestor(base, env, value["target"], tip),
            "Confirmed source changed while waiting",
        )
        # Persist external ownership before the state marker; both make starts fail closed.
        save(base, value, barrier=True, phase="backup")
        protocol.durable(base / "state/.upgrade.json", {"protocol": 1, "job": value["id"]})
        host.stop(base, record)
        with ops.writer_lease(base / "state") as lease:
            host.safe_offline(base)
            offline = snapshot(base, record, value, "offline", lease)
            save(base, value, phase="adapting", live_baseline=ops.state_inventory(base / "state"))
            probe(base, value, code, offline, complete=True)
            ops.require(
                ops.state_inventory(base / "state") == value["baseline"],
                "Source changed during adaptation",
            )
            ops.require(
                ops.inventory(base / "private") == value["private_inventory"],
                "External configuration/key drift",
            )
            ops.require(
                sorted(ops.uninspectable_ids(ops.host_processes(base / "state")))
                == [tuple(item) for item in value["host_uninspectable"]],
                "Host process set changed",
            )
            host.safe_offline(base)
            save(base, value, phase="migrating")
            protocol.durable(base / "state/release.json", {"release": value["target"]})
            try:
                target_validate(base, value, lease, value["target"])
            except Exception:
                save(
                    base,
                    value,
                    phase="verifying",
                    live_baseline=ops.state_inventory(base / "state"),
                )
                raise
            save(base, value, phase="switching", live_baseline=ops.state_inventory(base / "state"))
            next_record = {**record, "release": value["target"]}
            host.units(base, next_record)
            protocol.durable(base / "instance.json", next_record)
        save(base, value, phase="verifying")
        start_original(base, value)
        time.sleep(0.5)
        barrier_ready(base, value)
        # Barrier units cannot construct Application: target_validate above was authoritative.
        ops.require(
            ops.state_inventory(base / "state") == value["live_baseline"],
            "Unexpected writes under barrier",
        )
        host.stop(base, next_record)
        with ops.writer_lease(base / "state") as lease:
            target_validate(base, value, lease, value["target"])
            restore_semantics(base, value)
            save(base, value, live_baseline=ops.state_inventory(base / "state"))
        save(base, value, commit_decided=True, phase="commit_decided")
        finish(base, value)
    except Exception as error:  # noqa: BLE001 - never publish secret exception messages
        save(base, value, error=type(error).__name__)
        if value.get("commit_decided"):
            save(base, value, phase="needs_manual")
        elif value.get("snapshot") and value.get("live_baseline") and value["phase"] != "migrating":
            try:
                rollback(base, value)
            except Exception:  # noqa: BLE001 - retain protected recovery evidence
                save(base, value, phase="needs_manual")
        elif value.get("barrier"):
            save(base, value, phase="needs_manual")
        else:
            if value.get("original_files"):
                restore_semantics(base, value)
                start_original(base, value)
            save(base, value, phase="failed")


def controls(base, value):
    for path in sorted((base / "updates/spool").glob("*.json")):
        request = protocol.private_json(path)
        if request.get("action") not in {"cancel", "cancel-all"}:
            continue
        try:
            protocol.validate_request(request, value["original_record"]["owner"], path.stem)
            ops.require(request["payload"] == {"job": value["id"]}, "Control ownership mismatch")
            ops.require(
                value["phase"] == "waiting" and not value["barrier"],
                "Cancellation unavailable after barrier",
            )
        except ValueError:
            protocol.durable(
                base / "updates/results" / path.name,
                {
                    "request": request,
                    "request_id": path.stem,
                    "error": "invalid_control",
                    "result": {},
                },
            )
            path.unlink()
            continue
        if request["action"] == "cancel":
            restore_semantics(base, value)
            start_original(base, value)
            save(base, value, phase="cancelled")
        else:
            script = "from harbor_helper.service.data import ServiceData; from harbor_helper.service.shutdown import cancel_all; import sys; d=ServiceData(sys.argv[1]);\nwith d.store.control(): cancel_all(d.store)"
            host.run_python(base, value["original_record"], script)
            save(base, value, cancellation_actor=request["actor"])
        protocol.durable(
            base / "updates/results" / path.name,
            {"request": request, "request_id": path.stem, "result": {"phase": value["phase"]}},
        )
        path.unlink()


def run(base):
    record = ops.read_json(base / "instance.json")
    host.validate(base, record)
    with (base / ".manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = protocol.journal(base / "state")
        if previous and previous.get("protocol") != 1:
            raise ValueError("Unknown journal protocol; host intervention required")
        if (
            previous
            and previous.get("commit_decided")
            and previous["phase"] not in {"failed", "cancelled"}
            and (previous["phase"] != "succeeded" or previous.get("manager_activation_pending"))
        ):
            try:
                finish(base, previous)
            except Exception:  # noqa: BLE001 - commit forbids snapshot rollback
                save(
                    base,
                    previous,
                    interrupted_phase=previous.get("interrupted_phase", previous["phase"]),
                    phase="needs_manual",
                )
        elif previous and previous["phase"] not in protocol.TERMINAL:
            if not previous.get("barrier"):
                if previous.get("original_files"):
                    restore_semantics(base, previous)
                    start_original(base, previous)
                save(base, previous, phase="failed", error="executor_interrupted_before_barrier")
            else:
                # Explicit policy: migration and ambiguous crash windows require host resolve.
                save(
                    base,
                    previous,
                    interrupted_phase=previous.get("interrupted_phase", previous["phase"]),
                    phase="needs_manual",
                )
        for path in sorted((base / "updates/spool").glob("*.json")):
            request = protocol.private_json(path)
            identifier = path.stem
            result_path = base / "updates/results" / path.name
            if result_path.exists():
                path.unlink()
                continue
            try:
                protocol.validate_request(request, record["owner"], identifier)
                remembered = protocol.journal(base / "state")
                if remembered and remembered.get("id") == identifier:
                    protocol.durable(
                        result_path,
                        {
                            "request": request,
                            "request_id": identifier,
                            "result": {"job": identifier, "phase": remembered["phase"]},
                        },
                    )
                    path.unlink()
                    continue
                record = ops.read_json(base / "instance.json")
                ops.require(
                    not protocol.busy(base / "state"), "Upgrade task still owns this instance"
                )
                if request["action"] == "check":
                    result = check(base, record, identifier)
                elif request["action"] == "upgrade":
                    upgrade(base, record, request, identifier)
                    result = {"job": identifier}
                    record = ops.read_json(base / "instance.json")
                else:
                    raise ValueError("No cancellable waiting upgrade")
                response = {"request": request, "request_id": identifier, "result": result}
            except Exception as error:  # noqa: BLE001 - safe bounded public failure classification
                response = {
                    "request": request,
                    "request_id": identifier,
                    "error": type(error).__name__,
                    "result": {"relation": "check_failed"},
                }
            protocol.durable(result_path, response)
            path.unlink()
        protocol.sync_directory(base / "updates/spool")


def pending(base):
    """Read-only ExecCondition: idle/manual instances do not run the executor."""
    try:
        previous = protocol.journal(base / "state")
        if previous and (
            previous.get("protocol") != 1
            or previous.get("phase") not in protocol.PUBLIC_PHASES
            or previous.get("phase") == "needs_manual"
            or not previous.get("id")
        ):
            return False
        if any((base / "updates/spool").glob("*.json")):
            return True
        return bool(
            previous
            and (
                previous.get("phase") not in protocol.TERMINAL
                or (
                    previous.get("phase") == "succeeded"
                    and previous.get("manager_activation_pending")
                )
            )
        )
    except (OSError, ValueError, TypeError):
        # Corrupt ownership metadata needs host intervention, never a busy loop.
        return False


def activation_units(base, record, runtime_release, *, clean_environment=True):
    name = f"harbor-helper-{record['instance']}-updates"
    command = f"{base}/releases/{runtime_release}/.venv/bin/python {base}/manager/service.py"
    if clean_environment:
        command = (
            f"/usr/bin/env -i HOME={base}/home PATH={os.defpath}:/usr/local/bin "
            f"LANG=C.UTF-8 PYTHONUNBUFFERED=1 {command}"
        )
    service = f"""# harbor-helper instance {record["owner"]}
[Unit]
Description=Harbor Helper update executor {record["instance"]}
StartLimitIntervalSec=0
[Service]
Type=oneshot
UMask=0077
ExecCondition={command} update-pending --directory {base}
ExecStart={command} update-run --directory {base}
TimeoutStartSec=infinity
KillMode=mixed
[Install]
WantedBy=default.target
"""
    path = f"""# harbor-helper instance {record["owner"]}
[Unit]
Description=Harbor Helper update spool {record["instance"]}
[Path]
DirectoryNotEmpty={base}/updates/spool
Unit={name}.service
[Install]
WantedBy=default.target
"""
    timer = f"""# harbor-helper instance {record["owner"]}
[Unit]
Description=Harbor Helper update recovery polling {record["instance"]}
[Timer]
OnCalendar=*-*-* *:*:00/10
AccuracySec=1s
Persistent=false
Unit={name}.service
[Install]
WantedBy=timers.target
"""
    return {".service": service, ".path": path, ".timer": timer}


def validate_activation_units(base, record, runtime_release, *, installing):
    """Validate the entire owned set before changing any unit, including legacy v1."""
    texts = activation_units(base, record, runtime_release)
    preceding = activation_units(base, record, runtime_release, clean_environment=False)
    name = f"harbor-helper-{record['instance']}-updates"
    for suffix, content in texts.items():
        destination = base / "units" / (name + suffix)
        actual = host.systemctl("show", name + suffix, "--property=FragmentPath", "--value")
        ops.require(
            not actual or Path(actual).resolve() == destination,
            "Update unit belongs to another instance",
        )
        if destination.exists():
            legacy = "\n".join(
                line
                for line in preceding[suffix].split("\n")
                if not line.startswith("ExecCondition=")
            )
            ops.require(
                not destination.is_symlink()
                and destination.read_text() in {content, preceding[suffix], legacy},
                "Update unit content mismatch",
            )
        else:
            ops.require(
                installing or (suffix == ".timer" and not actual),
                "Missing owned update unit",
            )
    return texts


def enable(base, record, repository, branch):
    ops.require(not protocol.busy(base / "state"), "Upgrade busy")
    contract_path = base / "releases" / record["release"] / "update-contract.json"
    ops.require(contract_path.exists(), "One-time host upgrade to barrier-capable release required")
    for name in ("updates", "updates/spool", "updates/results"):
        (base / name).mkdir(mode=0o700, exist_ok=True)
    config = base / "private/update.toml"
    if not config.exists():
        ops.require(
            repository and branch in {"master", "dev"}, "Configure repository and master/dev branch"
        )
        config.write_text(
            "[updates]\nrepository = "
            + json.dumps(repository)
            + "\nbranch = "
            + json.dumps(branch)
            + "\n"
        )
    source(base)
    enabled_path = base / "updates/enabled.json"
    enabled = (
        protocol.private_json(enabled_path)
        if enabled_path.exists()
        else {"protocol": 1, "owner": record["owner"], "runtime_release": record["release"]}
    )
    ops.require(
        enabled.get("protocol") == 1 and enabled.get("owner") == record["owner"],
        "Update installation ownership mismatch",
    )
    runtime_release = enabled.get("runtime_release", record["release"])
    ops.require(re.fullmatch("[a-f0-9]{40}", runtime_release), "Invalid executor runtime release")
    uv = enabled.get("uv") or shutil.which("uv")
    if not isinstance(uv, str) or not Path(uv).is_absolute():
        raise ValueError("Install uv before enabling updates")
    uv_path = ops.plain(Path(uv).resolve())
    with ops.regular_reader(uv_path) as binary:
        metadata = os.fstat(binary.fileno())
        ops.require(
            metadata.st_uid in {0, os.getuid()}
            and not metadata.st_mode & 0o022
            and os.access(uv_path, os.X_OK),
            "uv must be a protected executable",
        )
    enabled["uv"] = str(uv_path)
    texts = validate_activation_units(base, record, runtime_release, installing=True)
    migrate_timers(base, record)
    activate(base, record["release"])
    protocol.durable(enabled_path, enabled)
    name = f"harbor-helper-{record['instance']}-updates"
    for suffix, content in texts.items():
        destination = base / "units" / (name + suffix)
        destination.write_text(content)
        host.systemctl("enable", *(["--runtime"] if record["runtime"] else []), destination)
    host.systemctl("daemon-reload")
    host.systemctl("start", name + ".timer")
    ops.require(
        host.systemctl("show", name + ".timer", "--property=ActiveState", "--value") == "active",
        "Update fallback timer is not active",
    )
    try:
        host.systemctl("start", name + ".path")
        path_state = host.systemctl("show", name + ".path", "--property=ActiveState", "--value")
    except subprocess.CalledProcessError:
        path_state = "failed"
    print(
        json.dumps({"activation": {"path": path_state, "timer": "active", "interval_seconds": 10}})
    )


def migrate_timers(base, record):
    """Migrate only the exact owned legacy backup invocation, keep its timer schedule."""
    name = "hh-ops-" + hashlib.sha256(str(base).encode()).hexdigest()[:16]
    roots = {
        Path.home() / ".config/systemd/user",
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "systemd/user",
    }
    for root in roots:
        unit = root / (name + "-backup.service")
        if not unit.exists():
            continue
        text = unit.read_text()
        ops.require(
            not unit.is_symlink() and text.startswith(f"# {name} {base}\n"),
            "Backup timer ownership mismatch",
        )
        lines = text.splitlines()
        commands = [line for line in lines if line.startswith("ExecStart=")]
        ops.require(len(commands) == 1, "Unknown backup timer command")
        argv = shlex.split(commands[0].removeprefix("ExecStart="))
        # argv: python code backup --directory BASE --output OUTPUT --release SHA --kind online
        ops.require(
            len(argv) == 11
            and argv[2:5] == ["backup", "--directory", str(base)]
            and argv[5] == "--output"
            and argv[7] == "--release"
            and argv[9:] == ["--kind", "online"],
            "Unknown backup timer invocation; migrate explicitly",
        )
        if Path(argv[1]).name == "ops_timer.py":
            continue
        code = ops.plain(argv[1])
        ops.require(
            code.name == "ops-" + ops.digest(code) + ".py"
            and Path(argv[0]) == code.parent / "venv/bin/python",
            "Legacy timer executable ownership mismatch",
        )
        # Never overwrite the old executable: install a complete new immutable set.
        release = base / "releases" / record["release"]
        sha = hashlib.sha256(
            (release / "scripts/ops.py").read_bytes()
            + (release / "scripts/ops_timer.py").read_bytes()
        ).hexdigest()
        destination = code.parent / ("timer-" + sha)
        destination.mkdir(mode=0o700, exist_ok=True)
        for filename in ("ops.py", "ops_timer.py"):
            target = destination / filename
            content = (release / "scripts" / filename).read_bytes()
            if target.exists():
                ops.require(target.read_bytes() == content, "Timer collection mismatch")
            else:
                target.write_bytes(content)
        argv[1] = str(destination / "ops_timer.py")
        from install_ops import systemd_quote

        replacement = "ExecStart=" + " ".join(map(systemd_quote, argv))
        temporary = unit.with_suffix(".service.next")
        temporary.write_text(text.replace(commands[0], replacement))
        os.replace(temporary, unit)
        host.systemctl("daemon-reload")


def resolve(base, mode, *, expected_state_digest=None):
    with (base / ".manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = protocol.journal(base / "state")
        ops.require(value and value.get("protocol") == 1, "Known journal required")
        if mode == "stop":
            save(base, value, phase="needs_manual", barrier=True)
            protocol.durable(base / "state/.upgrade.json", {"protocol": 1, "job": value["id"]})
            host.stop(base, ops.read_json(base / "instance.json"))
        elif mode == "restore":
            ops.require(
                value.get("barrier") and not value.get("commit_decided"),
                "Rollback unavailable after commit",
            )
            if expected_state_digest is not None:
                ops.require(
                    value.get("interrupted_phase") == "migrating",
                    "Explicit fingerprint only applies to interrupted migration",
                )
                marker = protocol.private_json(base / "state/.upgrade.json")
                ops.require(marker["job"] == value["id"], "Barrier mismatch")
                host.stop(base, ops.read_json(base / "instance.json"))
                with ops.writer_lease(base / "state"):
                    host.safe_offline(base)
                    observed = ops.state_inventory(base / "state")
                    ops.require(
                        ops.content_digest(observed) == expected_state_digest,
                        "Observed migration fingerprint changed",
                    )
                    ops.require(
                        ops.inventory(base / "private") == value["private_inventory"],
                        "External key/config changed",
                    )
                    save(base, value, live_baseline=observed, explicit_migration_recovery=True)
            rollback(base, value)
        elif mode == "accept":
            host.stop(base, ops.read_json(base / "instance.json"))
            marker = ops.read_json(base / "state/.upgrade.json")
            ops.require(marker == {"protocol": 1, "job": value["id"]}, "Barrier mismatch")
            protocol.durable(base / "state/.upgrade.json", marker)
            with ops.writer_lease(base / "state") as lease:
                current = ops.read_json(base / "instance.json")["release"]
                target_validate(base, value, lease, current)
                restore_semantics(base, value)
                save(
                    base,
                    value,
                    commit_decided=True,
                    accepted_release=current,
                    barrier=True,
                    phase="commit_decided",
                )
            finish(base, value)
        else:
            raise ValueError("Choose stop, restore or accept")
