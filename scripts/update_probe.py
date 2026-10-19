"""Target-code entry point. Copy adaptation or explicitly leased live migration only."""

import argparse
import json
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path

import ops


def map_value(value, original, target):
    if isinstance(value, str) and (value == original or value.startswith(original + "/")):
        return str(target) + value[len(original) :]
    if isinstance(value, list):
        return [map_value(item, original, target) for item in value]
    if isinstance(value, dict):
        return {key: map_value(item, original, target) for key, item in value.items()}
    return value


def map_copy(root, original):
    """Rewrite local frozen references only in the disposable copy, never in live state."""
    for path in root.rglob("*.json"):
        if path.is_file():
            value = json.loads(path.read_text())
            changed = map_value(value, original, root)
            if changed != value:
                ops.write_json(path, changed)
    with sqlite3.connect(root / "queue.sqlite") as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise ValueError("Invalid table name")
            columns = list(db.execute(f'PRAGMA table_info("{table}")'))
            json_columns = [
                r[1] for r in columns if r[1] in {"frozen", "config", "request", "result", "recent"}
            ]
            for column in json_columns:
                for rowid, text in db.execute(f'SELECT rowid,"{column}" FROM "{table}"').fetchall():
                    if text is None:
                        continue
                    value = json.loads(text)
                    changed = map_value(value, original, root)
                    if changed != value:
                        db.execute(
                            f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',
                            (json.dumps(changed), rowid),
                        )


def validate(root, *, complete):
    from harbor_helper.service.api import create_app
    from harbor_helper.service.application import Application

    # Exercise the actual shared HTTP assembly in addition to the application constructor.
    application = Application(root)
    data = application.data
    data.master_keys.current()
    master = ops.current_master(root)
    checked = ops.validate_db(root, master)
    counts = {
        "runs": 0,
        "submissions": 0,
        "objects": 0,
        "attachments": 0,
        "credentials": checked["credentials_checked"],
    }
    application.catalog()
    application.attachments.catalog()
    with data.store.connect() as db:
        for row in db.execute("SELECT kind,id,version FROM objects").fetchall():
            data.object(row["kind"], row["id"], row["version"])
            counts["objects"] += 1
        for row in db.execute("SELECT id FROM submissions").fetchall():
            data.submission(row["id"])
            counts["submissions"] += 1
        for row in db.execute("SELECT id FROM attachment_versions").fetchall():
            application.attachments.public(db, row["id"])
            counts["attachments"] += 1
    missing = []
    for row in data.store.runs():
        if (root / "runs" / row["id"] / "manifest.json").exists():
            application.detail(row["id"])
            application.safe_report(row["id"])
        else:
            missing.append(row["id"])
        counts["runs"] += 1
    # Explicit source audit gaps are preserved, not reclassified as migration failure.
    if complete:
        ops.validate_evidence(root, checked, [r["id"] for r in checked["runs"]])
    http = create_app(root)
    if http.state.application is None:
        raise ValueError("Target HTTP application did not construct")
    http.state.application.store.close()
    data.store.close()
    return {"protocol": 1, "complete": complete, "counts": counts, "missing_run_material": missing}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--original")
    parser.add_argument("--master-directory", type=Path)
    parser.add_argument("--lease-fd", type=int)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.original:
        if args.master_directory is None or args.master_directory.resolve().is_relative_to(root):
            raise ValueError("Copy master must be outside copy state")
        config = ops.read_json(root / "service.json")
        config.pop("master_file", None)
        config["master_directory"] = str(args.master_directory)
        ops.write_json(root / "service.json", config)
        (root / ".upgrade.json").unlink(missing_ok=True)
        ops.write_json(root / "release.json", {"release": args.release})
        map_copy(root, args.original)

    def guard(event, arguments):
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "socket.connect",
            "socket.bind",
            "socket.getaddrinfo",
        }:
            raise PermissionError("Upgrade probe forbids network and subprocess execution")
        if args.original and event == "open" and isinstance(arguments[0], str):
            opened = Path(arguments[0]).absolute()
            if opened.is_relative_to(Path(args.original)):
                raise PermissionError("Probe cannot read the original state")

    sys.addaudithook(guard)
    from harbor_helper.persistence.upgrades import migration_lease

    with migration_lease(root, args.lease_fd) if args.lease_fd is not None else nullcontext():
        print(json.dumps(validate(root, complete=args.complete)))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - trusted code still must not print secrets
        print(json.dumps({"failed": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
