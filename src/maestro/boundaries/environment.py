"""Run environment boundary: preparation, labelled resources and cleanup.

M2 only fixes the interface; Docker/Harbor implementations arrive in M3/M4.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class PreparationSpec:
    task_key: str
    spec_digest: str
    definition: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedArtifact:
    spec_digest: str
    location_id: str
    content_digest: str


@dataclass
class CleanupReport:
    released: bool
    remaining: list[str] = field(default_factory=list)


class Environment(Protocol):
    location_id: str

    async def prepare(self, spec: PreparationSpec) -> PreparedArtifact: ...

    async def is_ready(self, spec_digest: str) -> bool: ...

    async def evict(self, spec_digest: str) -> None: ...

    async def cleanup(self, labels: dict[str, str]) -> CleanupReport:
        """Stop and remove every resource carrying these platform labels."""
        ...
