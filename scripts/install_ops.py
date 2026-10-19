#!/usr/bin/env python3
"""Install private versioned ops executable and two user timers; never manage service processes."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def systemd_quote(value):
    # systemd specifier/env expansion also applies inside quotes.
    return (
        '"'
        + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "disable", "remove"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="stable private tool directory outside any Git checkout",
    )
    parser.add_argument("--backups", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--units", type=Path, default=Path.home() / ".config/systemd/user")
    parser.add_argument("--check-calendar", default="*:0/5")
    parser.add_argument("--backup-calendar", default="daily")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if any("\n" in str(v) or "\r" in str(v) for v in vars(args).values()):
        parser.error("multiline unit value refused")
    if not re.fullmatch("[a-f0-9]{40}", args.release):
        parser.error("release requires full SHA")
    base = args.directory.absolute()
    dest = args.destination.absolute()
    for path in (base, dest, args.backups.absolute(), args.units.absolute()):
        if any(p.is_symlink() for p in (path, *path.parents)):
            parser.error("symlink path refused")
    if any(((p / ".git/HEAD").is_file() or (p / ".git").is_file()) for p in (dest, *dest.parents)):
        parser.error("stable destination must be outside Git")
    name = "hh-ops-" + hashlib.sha256(str(base).encode()).hexdigest()[:16]
    units = args.units.absolute()
    owner = f"# {name} {base}\n"
    names = [
        name + "-" + kind + suffix
        for kind in ("check", "backup")
        for suffix in (".service", ".timer")
    ]
    for unit in names:
        path = units / unit
        if path.exists() and not path.read_text().startswith(owner):
            parser.error("refusing foreign unit collision")
    if args.action in ("disable", "remove"):
        subprocess.run(
            [
                "systemctl",
                "--user",
                "disable",
                "--now",
                *[n for n in names if n.endswith(".timer")],
            ],
            check=True,
        )
        if args.action == "remove":
            for unit in names:
                (units / unit).unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        print(json.dumps({"instance": name, "action": args.action, "tool_retained": str(dest)}))
        return
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dest.stat().st_uid != os.getuid() or dest.stat().st_mode & 0o077:
        parser.error("destination must be owner-only")
    # Dedicated stable dependency environment; never uses the source worktree venv at runtime.
    python = dest / "venv/bin/python"
    if not python.exists():
        subprocess.run(["uv", "venv", "--python", sys.executable, str(dest / "venv")], check=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), "cryptography==46.0.7"], check=True
        )
    subprocess.run(
        [str(python), "-c", "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"],
        check=True,
    )
    source = Path(__file__).with_name("ops.py")
    code_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    code = dest / ("ops-" + code_hash + ".py")
    if code.is_symlink():
        parser.error("stable code symlink refused")
    if code.exists() and code.read_bytes() != source.read_bytes():
        parser.error("stable code collision")
    if not code.exists():
        shutil.copyfile(source, code)
        code.chmod(0o600)
    # A private immutable set keeps the timer code and its ops dependency together.
    timer_set = dest / ("timer-" + code_hash)
    timer_set.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(source, timer_set / "ops.py")
    shutil.copyfile(Path(__file__).with_name("ops_timer.py"), timer_set / "ops_timer.py")
    units.mkdir(parents=True, exist_ok=True)
    for kind, calendar in (("check", args.check_calendar), ("backup", args.backup_calendar)):
        command = [python, timer_set / "ops_timer.py", kind, "--directory", base]
        command += (
            ["--backups", args.backups.absolute()]
            if kind == "check"
            else [
                "--output",
                args.backups.absolute(),
                "--release",
                args.release,
                "--kind",
                "online",
            ]
        )
        service = (
            owner
            + "[Unit]\nDescription=Harbor Helper read-only "
            + kind
            + "\n[Service]\nType=oneshot\nUMask=0077\nNoNewPrivileges=true\nEnvironment=PYTHONUNBUFFERED=1\nExecStart="
            + " ".join(map(systemd_quote, command))
            + "\n"
        )
        timer = (
            owner
            + f"[Unit]\nDescription=Harbor Helper {kind} timer\n[Timer]\nOnCalendar={calendar}\nPersistent=true\nUnit={name}-{kind}.service\n[Install]\nWantedBy=timers.target\n"
        )
        for suffix, content in ((".service", service), (".timer", timer)):
            path = units / (name + "-" + kind + suffix)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(content)
            os.replace(temporary, path)
    subprocess.run(
        ["systemd-analyze", "--user", "verify", *[str(units / n) for n in names]], check=True
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    if args.enable:
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", *[n for n in names if n.endswith(".timer")]],
            check=True,
        )
    print(
        json.dumps(
            {"instance": name, "code_hash": code_hash, "enabled": args.enable, "units": names}
        )
    )


if __name__ == "__main__":
    main()
