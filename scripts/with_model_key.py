"""Load one explicitly selected protected file in-process; never write its value."""

import argparse
import json
import os
import sys
from pathlib import Path

from harbor_helper.security.credentials import KEY_ENV, RedactedStream, read_key_file, scan_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--scan", type=Path, help="Scan final evidence; output only counts/boolean")
    parser.add_argument("cli_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        secret = read_key_file(args.key_file)
    except (OSError, ValueError):
        print(
            "Credential file unavailable/invalid; require owner-only regular file", file=sys.stderr
        )
        return 1
    if args.scan:
        result = scan_tree(args.scan, [secret])
        print(json.dumps(result))
        return 0 if result["clean"] else 1
    cli_args = args.cli_args
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    if not cli_args:
        parser.error("Supply existing harbor-helper arguments after --")
    from harbor_helper.commands.main import main as helper_main

    old_value = os.environ.get(KEY_ENV)
    old_argv, old_stdout, old_stderr = sys.argv, sys.stdout, sys.stderr
    os.environ[KEY_ENV] = secret
    sys.argv = ["harbor-helper", *cli_args]
    sys.stdout = RedactedStream(old_stdout, [secret])
    sys.stderr = RedactedStream(old_stderr, [secret])
    try:
        return helper_main()
    except Exception as error:  # noqa: BLE001 - never expose arbitrary credential-bearing errors
        print(f"Credential launcher failed: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        sys.stdout.finish()
        sys.stderr.finish()
        sys.argv, sys.stdout, sys.stderr = old_argv, old_stdout, old_stderr
        if old_value is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = old_value


if __name__ == "__main__":
    sys.exit(main())
