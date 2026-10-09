"""Compatibility for Harbor import paths frozen in historical job files."""

import sys

from harbor_helper.execution import environments as _implementation

sys.modules[__name__] = _implementation
