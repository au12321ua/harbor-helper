"""Stable process entry point; scheduling and execution have distinct owners."""

import sys

from harbor_helper.execution.runner import run
from harbor_helper.execution.scheduler import supervise


def main():
    if sys.argv[1] == "supervise":
        supervise(sys.argv[2])
    else:
        run(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
