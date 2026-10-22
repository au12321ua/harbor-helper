"""Build the public OpenAPI document without a deployment (for CI and generators)."""

import tempfile
from pathlib import Path

from maestro.api.app import create_app
from maestro.application import Maestro
from maestro.config import Settings


def document() -> dict:
    with tempfile.TemporaryDirectory() as root:
        base = Path(root)
        settings = Settings(
            data_dir=base / "data", cache_dir=base / "cache", master_key_dir=base / "keys"
        )
        settings.data_dir.mkdir()
        service = Maestro.build(settings)
        try:
            return create_app(service, run_worker=False).openapi()
        finally:
            service.db.dispose()
