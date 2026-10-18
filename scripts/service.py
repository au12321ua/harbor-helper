#!/usr/bin/env python3
"""Install and operate one owned Linux user-systemd instance (no sudo)."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import local_platform
import ops


def systemctl(*arguments):
    return subprocess.run(
        ["systemctl", "--user", *map(str, arguments)], check=True, text=True, capture_output=True
    ).stdout.strip()


def unit_name(record, part):
    return f"harbor-helper-{record['instance']}-{part}.service"


def unit_text(base, record, part):
    code = base / "releases" / record["release"]
    argv = [
        str(code / ".venv/bin/python"),
        "-m",
        "harbor_helper.commands.main",
        "service",
        "scheduler" if part == "scheduler" else "serve",
        "--root",
        str(base / "state"),
    ]
    if part == "http":
        argv += [
            "--host",
            record["host"],
            "--port",
            str(record["port"]),
            "--setup-token-file",
            str(base / "private/setup-token"),
            "--master-key-file",
            str(base / "private/master.key"),
        ]

    # systemd quoting, including literal specifiers and dollar signs.
    def quote(value):
        return (
            '"'
            + str(value)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("%", "%%")
            .replace("$", "$$")
            + '"'
        )

    environment = [
        "/usr/bin/env",
        "-i",
        f"HOME={base / 'home'}",
        f"PATH={record['path']}",
        "LANG=C.UTF-8",
        "PYTHONUNBUFFERED=1",
        *argv,
    ]
    return f"""# harbor-helper instance {record["owner"]}
[Unit]
Description=Harbor Helper {record["instance"]} {part}
After=network.target
[Service]
Type=simple
WorkingDirectory={code}
ExecStart={" ".join(quote(a) for a in environment)}
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=270
UMask=0077
StandardOutput=append:{base}/logs/{part}.log
StandardError=append:{base}/logs/{part}.log
[Install]
WantedBy=default.target
"""


def validate(base, record):
    ops.require(
        record["format"] == "harbor-helper-systemd-v1" and record["directory"] == str(base),
        "instance ownership mismatch",
    )
    ops.require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", record["instance"]), "invalid instance")
    for part in ("http", "scheduler"):
        path = base / "units" / unit_name(record, part)
        ops.require(
            path.is_file()
            and not path.is_symlink()
            and path.read_text() == unit_text(base, record, part),
            "unit ownership/content mismatch",
        )
        actual = systemctl("show", unit_name(record, part), "--property=FragmentPath", "--value")
        ops.require(
            not actual or Path(actual).resolve() == path, "systemd unit belongs to another instance"
        )


def units(base, record):
    for part in ("http", "scheduler"):
        (base / "units" / unit_name(record, part)).write_text(unit_text(base, record, part))
    systemctl("daemon-reload")


def release(base, source):
    local_platform.REPO = ops.plain(source)
    return local_platform.release(base, local_platform.environment(base)).name


def run_python(base, record, script, *arguments):
    python = base / "releases" / record["release"] / ".venv/bin/python"
    return subprocess.check_output(
        [str(python), "-c", script, str(base / "state"), *arguments],
        env=local_platform.environment(base),
        text=True,
    ).strip()


OBSERVE = """
import json, sys
from harbor_helper.service.data import ServiceData
from harbor_helper.service.shutdown import observe
print(json.dumps(observe(ServiceData(sys.argv[1]))))
"""
REQUEST = """
import json,sys
from harbor_helper.service.data import ServiceData
from harbor_helper.service.shutdown import request
from harbor_helper.service.admission import set_maintenance
x=ServiceData(sys.argv[1])
if sys.argv[2]=='close':
    with x.store.control(): set_maintenance(x, {'paused':True, 'reason':'Service maintenance'})
else: request(x,sys.argv[2],{'id':'host-administrator','username':'host-administrator'})
"""


def maintenance(base, record, args):
    value = json.loads(run_python(base, record, OBSERVE))
    print(json.dumps(value, ensure_ascii=False), flush=True)
    if not value["maintenance"]["paused"]:
        if not args.close_admissions and (
            not sys.stdin.isatty()
            or input("Close new admissions persistently? Type yes: ") != "yes"
        ):
            raise ValueError(
                "Declined: no maintenance change made; use --close-admissions explicitly"
            )
        run_python(base, record, REQUEST, "close")
    if not args.mode and not sum(v for k, v in value["counts"].items() if k != "audit_incomplete"):
        args.mode = "wait"
    if not args.mode:
        raise ValueError("Choose --mode wait|cancel|abort explicitly; admissions remain closed")
    run_python(base, record, REQUEST, args.mode)
    if args.mode == "abort":
        return False
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        value = json.loads(run_python(base, record, OBSERVE))
        if value["intent"]["phase"] == "complete":
            print(json.dumps(value), flush=True)
            return True
        time.sleep(1)
    raise ValueError(
        "Wait ended; durable stop intent remains active. Inspect status, --mode abort, or explicitly --mode cancel"
    )


def stop(base, record):
    for part in ("scheduler", "http"):
        systemctl("stop", unit_name(record, part))


def safe_offline(base):
    with ops.ro_db(base / "state") as db:
        data = {"runs": ops.rows(db, "runs"), "submissions": ops.rows(db, "submissions")}
    ops.require(not ops.writers(base, data), "state writers/identities not confirmed stopped")
    ops.require(
        all(r["status"] in ops.TERMINAL for r in data["runs"])
        and all(r["status"] != "preparing" for r in data["submissions"]),
        "unfinished work/resources: retain cleanup records",
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["install", "start", "stop", "status", "maintain", "upgrade", "uninstall"]
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--instance")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Temporary units in XDG_RUNTIME_DIR; no login-profile changes",
    )
    parser.add_argument("--part", choices=["http", "scheduler", "all"], default="all")
    parser.add_argument("--close-admissions", action="store_true")
    parser.add_argument("--mode", choices=["wait", "cancel", "abort"])
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument("--backups", type=Path)
    parser.add_argument(
        "--fresh-state",
        action="store_true",
        help="After verified backup, retain old state and explicitly initialize a new state",
    )
    parser.add_argument("--purge", action="store_true")
    parser.add_argument(
        "--confirm-delete", help="Independent purge confirmation: exact absolute instance directory"
    )
    args = parser.parse_args()
    base = ops.plain(args.directory)
    ops.require(
        str(base) not in {"/", str(Path.home())} and not any(c in str(base) for c in '\n\r%$"\\ '),
        "unsafe instance directory",
    )
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    ops.require(
        base.stat().st_uid == os.getuid() and not base.stat().st_mode & 0o077,
        "instance requires owner-only directory",
    )
    with (base / ".manager.lock").open("a") as lock, ExitStack() as leases:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = base / "instance.json"
        if args.action == "install" and not manifest.exists():
            ops.require(
                args.instance and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", args.instance),
                "--instance requires a unique lowercase name",
            )
            ops.require(1 <= args.port <= 65535, "invalid port")
            ops.require(
                {p.name for p in base.iterdir()} <= {".manager.lock"},
                "refuse to adopt nonempty directory",
            )
            record = {
                "format": "harbor-helper-systemd-v1",
                "owner": uuid.uuid4().hex,
                "directory": str(base),
                "instance": args.instance,
                "host": args.host,
                "port": args.port,
                "runtime": args.runtime,
                "path": os.defpath + ":/usr/local/bin",
            }
            for part in ("http", "scheduler"):
                ops.require(
                    not systemctl(
                        "show", unit_name(record, part), "--property=FragmentPath", "--value"
                    ),
                    "unit name already in use",
                )
            for name in ("home", "state", "private", "logs", "releases", "units", "manager"):
                (base / name).mkdir(mode=0o700)
            record["release"] = subprocess.check_output(
                ["git", "-C", str(args.source), "rev-parse", "HEAD^{commit}"], text=True
            ).strip()
            record["installed"] = False
            ops.write_json(manifest, record)
        else:
            record = ops.read_json(manifest)
        if args.action == "install" and not record.get("installed", True):
            ops.require(
                release(base, args.source) == record["release"],
                "reinstall requires the matching old release; use upgrade to change versions",
            )
            ops.write_json(base / "state/release.json", {"release": record["release"]})
            for filename in ("service.py", "local_platform.py", "ops.py"):
                shutil.copyfile(Path(__file__).with_name(filename), base / "manager" / filename)
            units(base, record)
            for part in ("http", "scheduler"):
                options = ["--runtime"] if record["runtime"] else []
                systemctl("enable", *options, base / "units" / unit_name(record, part))
            ops.write_json(manifest, record)
            record["installed"] = True
            ops.write_json(manifest, record)
        if not record.get("installed", True):
            ops.require(
                args.action == "uninstall", "instance uninstalled; install matching release first"
            )
            print("Already uninstalled; retained data unchanged")
            return
        validate(base, record)
        if args.action == "start":
            for part in ("http", "scheduler") if args.part == "all" else (args.part,):
                systemctl("start", unit_name(record, part))
        elif args.action == "stop":
            for part in ("scheduler", "http") if args.part == "all" else (args.part,):
                systemctl("stop", unit_name(record, part))
        elif args.action == "maintain":
            maintenance(base, record, args)
        elif args.action == "upgrade":
            ops.require(args.mode in {"wait", "cancel"}, "upgrade requires --mode wait|cancel")
            maintenance(base, record, args)
            stop(base, record)
            lease = leases.enter_context((base / "state/writer.lock").open("a"))
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            safe_offline(base)
            output = args.backups or base.parent / (base.name + "-backups")
            saved = ops.backup(
                SimpleNamespace(
                    directory=base,
                    output=output,
                    release=record["release"],
                    kind="offline",
                    lock_timeout=5,
                )
            )
            snapshot = Path(saved["snapshot"])
            ops.restore(
                SimpleNamespace(
                    snapshot=snapshot,
                    master_file=output / (snapshot.name + ".master"),
                    target=output / (snapshot.name + "-restore-check"),
                    release=record["release"],
                )
            )
            next_release = release(base, args.source)
            # All fallible backup/installation work precedes the version switch.
            previous = record.copy()
            old_state = None
            if args.fresh_state:
                old_state = base / ("state-retained-" + uuid.uuid4().hex)
                (base / "state").rename(old_state)
                (base / "state").mkdir(mode=0o700)
            record["release"] = next_release
            try:
                ops.write_json(base / "state/release.json", {"release": next_release})
                units(base, record)
                ops.write_json(manifest, record)
            except Exception:
                units(base, previous)
                if not old_state:
                    ops.write_json(base / "state/release.json", {"release": previous["release"]})
                if old_state:
                    (base / "state/release.json").unlink(missing_ok=True)
                    (base / "state").rmdir()
                    old_state.rename(base / "state")
                raise
            print(
                json.dumps(
                    {
                        "backup": saved,
                        "release": next_release,
                        "retained_state": str(old_state) if old_state else None,
                        "next": "start explicitly; maintenance remains closed",
                    }
                )
            )
        elif args.action == "uninstall":
            stop(base, record)
            lease = leases.enter_context((base / "state/writer.lock").open("a"))
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (base / "state/service.json").exists():
                safe_offline(base)
            if args.purge:
                paths = [base / name for name in ("state", "private", "home", "logs")]
                print("PURGE exact paths: " + json.dumps(list(map(str, paths))), flush=True)
                ops.require(
                    args.confirm_delete == str(base),
                    "purge requires independent --confirm-delete with the exact displayed instance directory",
                )
                if (base / "state/service.json").exists():
                    safe_offline(base)
                else:
                    ops.require(
                        not any((base / "state/runs").glob("*")),
                        "unknown run resources; retain state",
                    )
            for part in ("http", "scheduler"):
                systemctl(
                    "disable",
                    *(["--runtime"] if record["runtime"] else []),
                    unit_name(record, part),
                )
                (base / "units" / unit_name(record, part)).unlink()
            systemctl("daemon-reload")
            shutil.rmtree(base / "releases")
            record["installed"] = False
            ops.write_json(manifest, record)
            if args.purge:
                for path in paths:
                    shutil.rmtree(path)
            print(
                "Uninstalled; backups and retained-state directories preserved. Manager and ownership manifest retained for audit."
            )
            return
        for part in ("http", "scheduler"):
            print(
                part
                + ": "
                + systemctl(
                    "show", unit_name(record, part), "--property=ActiveState,SubState,MainPID"
                )
            )
        if (base / "state/service.json").exists():
            print(run_python(base, record, OBSERVE))
        print(f"Browser: http://{record['host']}:{record['port']}")
        print("Bootstrap file: " + str(base / "private/setup-token"))
        print(
            "Installed manager: python3 "
            + str(base / "manager/service.py")
            + " ACTION --directory "
            + str(base)
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Operation refused/failed: {error}", file=sys.stderr)
        sys.exit(1)
