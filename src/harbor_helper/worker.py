"""Compatibility entry for historical ``python -m harbor_helper.worker`` callers."""

import sys

from harbor_helper.execution import worker as _implementation

if __name__ == "__main__":
    sys.exit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
