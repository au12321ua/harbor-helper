"""Compatibility entry for historical ``python -m harbor_helper.service_sources`` callers."""

import sys

from harbor_helper.service import sources as _implementation

if __name__ == "__main__":
    sys.exit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
