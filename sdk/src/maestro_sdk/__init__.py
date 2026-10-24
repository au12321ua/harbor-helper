"""Python client for Maestro: submit, watch, compare and rerun team experiments.

from maestro_sdk import MaestroClient

client = MaestroClient("https://maestro.example", token=pat)
client.require("runs", "execution")
resolution = client.configs.resolve(config).raise_for_blockers()
submitted = client.runs.submit(name="baseline", resolution_id=resolution.resolution_id)
client.operations.wait(submitted.operation_id)
"""

from maestro_sdk import models
from maestro_sdk.client import (
    BatchSubmission,
    ContractDriftWarning,
    Download,
    MaestroClient,
    Resolution,
    Submission,
)
from maestro_sdk.errors import (
    ApiError,
    BlockersPresent,
    ContentMismatch,
    MaestroError,
    TransportError,
    UnsupportedCapability,
    WaitTimeout,
)

__all__ = [
    "ApiError",
    "BatchSubmission",
    "BlockersPresent",
    "ContentMismatch",
    "ContractDriftWarning",
    "Download",
    "MaestroClient",
    "MaestroError",
    "Resolution",
    "Submission",
    "TransportError",
    "UnsupportedCapability",
    "WaitTimeout",
    "models",
]
