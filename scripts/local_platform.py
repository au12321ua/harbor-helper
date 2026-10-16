"""Private fixed-commit local deployment; no inherited provider credentials."""

import argparse
import ctypes
import fcntl
import json
import os
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STOP_SCHEDULER = """
import sys
from pathlib import Path
from harbor_helper.persistence.store import Store
from harbor_helper.execution.runs import stop_supervisor
root = Path(sys.argv[1])
if (root / 'service.json').is_file():
    store = Store(root)
    print(stop_supervisor(store))
else:
    print('Scheduler: not initialized')
"""


def fail(message):
    raise RuntimeError(message)


def open_pidfd(pid):
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    # Some Linux Python builds omit os.pidfd_open despite kernel/glibc support.
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        call = libc.pidfd_open
    except AttributeError:
        fail("This Linux/Python build lacks pidfd support; cannot manage processes safely.")
    call.argtypes = [ctypes.c_int, ctypes.c_uint]
    call.restype = ctypes.c_int
    fd = call(pid, 0)
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return fd


def birth(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def matches(record):
    pid = record["pid"]
    if birth(pid) != record["birth"]:
        return False
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        return [x.decode() for x in argv] == record["argv"] and Path(
            f"/proc/{pid}/cwd"
        ).resolve() == Path(record["code"])
    except OSError:
        return False


def read_record(base):
    path = base / "http.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        assert isinstance(data["pid"], int) and data["pid"] > 0
        assert isinstance(data["birth"], str) and data["birth"]
        assert isinstance(data["argv"], list) and all(isinstance(x, str) for x in data["argv"])
        assert Path(data["code"]).parent == base / "releases"
        assert data["root"] == str(base / "state")
        assert 1 <= data["port"] <= 65535
        return data
    except (OSError, ValueError, KeyError, AssertionError, TypeError):
        fail(f"Invalid process record: {path}; inspect it before retrying. No process stopped.")


def environment(base):
    # No proxy, model key, Hub token, remote profile or caller HOME is inherited.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    env.update(
        HOME=str(base / "home"), PYTHONUNBUFFERED="1", UV_CACHE_DIR=str(Path.home() / ".cache/uv")
    )
    return env


def owns_listener(record):
    try:
        sockets = {os.readlink(p) for p in Path(f"/proc/{record['pid']}/fd").iterdir()}
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            if (
                fields[1] == f"0100007F:{record['port']:04X}"
                and fields[3] == "0A"
                and f"socket:[{fields[9]}]" in sockets
            ):
                return True
    except OSError:
        pass
    return False


def health(record):
    if not owns_listener(record):
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{record['port']}/api/v1/health", timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def setup_notice(base, reveal):
    if (base / "state/service.json").exists():
        return
    path = base / "private/setup-token"
    if reveal and sys.stdout.isatty() and path.exists():
        # Read only the deployment-owned bootstrap file, never an inherited key.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as file:
            info = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                fail("Bootstrap file must be a regular owner-only file.")
            value = file.read(1025).strip()
        if not 32 <= len(value) <= 1024 or not all(c.isalnum() or c in "_-" for c in value):
            fail("Invalid bootstrap file; inspect it locally without resetting state.")
        print(f"First setup bootstrap (local terminal only): {value}")
    else:
        print(f"First setup bootstrap file (read locally): {path}")


def describe(base, record, *, reveal_setup=False):
    running = bool(record and matches(record))
    print(f"HTTP: {'running' if running else 'stopped'}")
    if record and birth(record["pid"]) and not running:
        print("HTTP record identity mismatch; no process will be signalled.")
    scheduler = base / "state/scheduler.json"
    try:
        data = json.loads(scheduler.read_text())
        active = bool(data.get("birth") and birth(data["pid"]) == data["birth"])
        print(f"Scheduler: {'running' if active else 'stopped'}")
    except FileNotFoundError:
        print("Scheduler: not started")
    except (ValueError, KeyError, TypeError):
        print(f"Scheduler: invalid record; inspect {scheduler}")
    if running:
        print(f"Browser: http://127.0.0.1:{record['port']}/")
    setup_notice(base, reveal_setup)
    print(f"Logs: {base / 'logs'} (scheduler log: {base / 'state/supervisor.log'})")
    command = (
        f"{shlex.quote(str(REPO / 'scripts/start-local.sh'))} --directory {shlex.quote(str(base))}"
    )
    print(f"Status: {command} status\nStop: {command} stop")


def stop(base, record, env):
    if record and birth(record["pid"]):
        if not matches(record):
            fail(f"HTTP identity mismatch in {base / 'http.json'}; no process stopped.")
        # A pidfd binds the signal to this process even if the PID is subsequently reused.
        fd = open_pidfd(record["pid"])
        try:
            if not matches(record):
                fail("HTTP identity changed; no process stopped.")
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        finally:
            os.close(fd)
        deadline = time.monotonic() + 15
        while birth(record["pid"]) == record["birth"]:
            if time.monotonic() > deadline:
                fail("HTTP stop timed out; record retained, no force kill.")
            time.sleep(0.1)
    if (base / "state/service.json").exists():
        if not record:
            fail("No release record for initialized state; cannot confirm scheduler stop.")
        python = Path(record["code"]) / ".venv/bin/python"
        result = subprocess.run(
            [str(python), "-c", STOP_SCHEDULER, str(base / "state")],
            cwd=record["code"],
            env=env,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode:
            fail(
                "HTTP stopped; scheduler stop refused. Restart to cancel/wait for tasks. "
                + result.stderr.strip().splitlines()[-1]
            )
        print("Scheduler: stopped (idle check confirmed)")
    print("HTTP: stopped")


def check_master(base):
    service = base / "state/service.json"
    if not service.exists():
        return
    try:
        data = json.loads(service.read_text())
        path = Path(data["master_file"])
        info = path.lstat()
        assert path == base / "private/master.key"
        assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
        assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == 32
    except (OSError, KeyError, ValueError, AssertionError, TypeError):
        fail(
            "Existing state master reference is missing/invalid or not owner-only; "
            "restore the original master, do not initialize again."
        )


def release(base, env):
    uv = shutil.which("uv")
    if not uv:
        fail("Install uv first: https://docs.astral.sh/uv/getting-started/installation/")
    commit = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD^{commit}"], text=True
    ).strip()
    code = base / "releases" / commit
    if not code.exists():
        stage = base / "releases" / f".export-{os.getpid()}"
        stage.mkdir()
        try:
            archive = subprocess.Popen(
                ["git", "-C", str(REPO), "archive", commit], stdout=subprocess.PIPE
            )
            extract = subprocess.run(
                ["tar", "-x", "-C", str(stage)], stdin=archive.stdout, check=False
            )
            archive.stdout.close()
            if archive.wait() or extract.returncode:
                fail("Fixed-commit export failed.")
            stage.rename(code)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    if not (code / "src/harbor_helper/static/index.html").is_file():
        fail("Committed production static missing; build and commit frontend first.")
    if (code / ".installed").exists() and (code / ".venv/bin/python").exists():
        return code
    with (base / "logs/install.log").open("a") as log:
        result = subprocess.run(
            [uv, "sync", "--locked", "--no-dev", "--python", sys.executable],
            cwd=code,
            env=env,
            stdout=log,
            stderr=log,
            check=False,
        )
    if result.returncode:
        fail(f"Locked dependency installation failed; inspect {base / 'logs/install.log'}")
    (code / ".installed").touch()
    return code


def start(base, record, env, port):
    check_master(base)
    if record and matches(record):
        if port is not None and port != record["port"]:
            fail("Instance already running on another port; stop before changing port.")
        if not health(record):
            fail("Recorded HTTP is alive but not healthy; inspect logs/status before restarting.")
        print("Already running")
        describe(base, record, reveal_setup=True)
        return
    if record and birth(record["pid"]):
        fail("Recorded PID belongs to a different process; inspect http.json. No signal sent.")
    # Same-code API recovery can observe an existing detached scheduler. A code
    # upgrade must first confirm that the old scheduler is idle and stopped.
    commit = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD^{commit}"], text=True
    ).strip()
    if record and Path(record["code"]).name != commit:
        stop(base, record, env)
    elif not record and (base / "state/service.json").exists():
        fail("Initialized state has no release record; inspect it, do not reset.")
    check_master(base)
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port or 0))
        except OSError:
            fail(f"Port {port} unavailable; choose --port or stop its owner.")
        chosen = probe.getsockname()[1]
    if not hasattr(signal, "pidfd_send_signal"):
        fail("This Python build lacks pidfd_send_signal; use a supported Linux Python.")
    os.close(open_pidfd(os.getpid()))
    code = release(base, env)
    argv = [
        str(code / ".venv/bin/python"),
        "-m",
        "harbor_helper.commands.main",
        "service",
        "serve",
        "--root",
        str(base / "state"),
        "--setup-token-file",
        str(base / "private/setup-token"),
        "--master-key-file",
        str(base / "private/master.key"),
        "--host",
        "127.0.0.1",
        "--port",
        str(chosen),
    ]
    with (base / "logs/http.log").open("a") as log:
        process = subprocess.Popen(
            argv,
            cwd=code,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    identity = birth(process.pid)
    if identity is None:
        fail(f"HTTP exited before startup; inspect {base / 'logs/http.log'}")
    record = {
        "pid": process.pid,
        "birth": identity,
        "argv": argv,
        "code": str(code),
        "root": str(base / "state"),
        "port": chosen,
    }
    (base / "http.json").write_text(json.dumps(record, indent=2) + "\n")
    deadline = time.monotonic() + 60
    # /proc/cmdline can briefly be empty during exec. Wait on our Popen
    # child, requiring full identity plus socket ownership only for readiness.
    while process.poll() is None and time.monotonic() < deadline:
        if matches(record) and health(record):
            describe(base, record, reveal_setup=True)
            return
        time.sleep(0.2)
    stop(base, record, env)
    fail(f"HTTP startup failed; inspect {base / 'logs/http.log'}")


def main():
    if sys.platform != "linux" or not (3, 12) <= sys.version_info[:2] <= (3, 13):
        fail("Local startup requires Linux and Python 3.12–3.13.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", default="start", choices=["start", "status", "stop", "restart"]
    )
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".local/share/harbor-helper-local"
    )
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        fail("Port must be between 1 and 65535.")
    os.umask(0o077)
    base = args.directory.expanduser().absolute()
    if base.is_symlink():
        fail("Instance directory must not be a symlink.")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = base.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        fail("Instance directory must be owned by current user with mode 0700.")
    base = base.resolve()
    for name in ("home", "state", "private", "logs", "releases"):
        path = base / name
        if path.is_symlink():
            fail(f"Instance component must not be a symlink: {path}")
        path.mkdir(exist_ok=True, mode=0o700)
    env = environment(base)
    with (base / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = read_record(base)
        if args.action == "status":
            describe(base, record)
        elif args.action == "stop":
            stop(base, record, env)
        else:
            if args.action == "restart":
                stop(base, record, env)
            start(base, record, env, args.port)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Local platform: {error}", file=sys.stderr)
        sys.exit(1)
