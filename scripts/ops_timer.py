"""Stable owned timer entry: resolve the live release, skip durable upgrade ownership."""

import json
import sys
from pathlib import Path


def main():
    arguments = sys.argv[1:]
    base = Path(arguments[arguments.index("--directory") + 1])
    path = base / "updates/journal.json"
    if path.exists():
        value = json.loads(path.read_text())
        if value.get("phase") not in {"succeeded", "failed", "cancelled"}:
            print(json.dumps({"skipped": "upgrade_in_progress"}))
            return
    import ops

    if arguments[0] == "backup":
        release = json.loads((base / "instance.json").read_text())["release"]
        index = arguments.index("--release") + 1
        arguments[index] = release
    sys.argv = [sys.argv[0], *arguments]
    ops.main()


if __name__ == "__main__":
    main()
